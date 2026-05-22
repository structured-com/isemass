"""Cisco ISE CoA API helpers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
from pathlib import Path
from time import perf_counter
import re
from typing import Any, Callable, Iterable
from xml.etree import ElementTree

import requests
import urllib3

HEADERS = {
    "Accept": "application/xml",
}
REQUEST_METHOD = "GET"
REQUEST_TIMEOUT_SECONDS = 30
MAC_NOT_VALID_SESSION_TEXT = "No NAS_IP_ADDRESS associated with the calling station id"

# REGEX for all formats of MAC address.
# "?:" removes groups so re.findall returns complete MAC address strings.
RE_MAC_COLON = r"(?:[0-9A-Fa-f]{2}:){5}(?:[0-9A-Fa-f]{2})"
RE_MAC_DASH = r"(?:[0-9A-Fa-f]{2}-){5}(?:[0-9A-Fa-f]{2})"
RE_MAC_CISCO = r"(?:[0-9A-Fa-f]{4}\.){2}(?:[0-9A-Fa-f]{4})"
RE_MAC_ALL = RE_MAC_COLON + r"|" + RE_MAC_DASH + r"|" + RE_MAC_CISCO
RE_MAC_PATTERN = re.compile(RE_MAC_ALL)


@dataclass(frozen=True)
class CoaResult:
    """Result for one MAC address CoA request."""

    mac: str
    success: bool
    result_message: str
    seconds: float
    request_method: str = REQUEST_METHOD
    request_url: str | None = None
    verify_tls: bool | None = None
    response_status_code: int | None = None
    response_headers: dict[str, str] | None = None
    response_text: str | None = None
    ise_result_value: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation of this result."""
        return {
            "mac_address": self.mac,
            "success": self.success,
            "result_message": self.result_message,
            "seconds": self.seconds,
            "request_method": self.request_method,
            "request_url": self.request_url,
            "verify_tls": self.verify_tls,
            "response_status_code": self.response_status_code,
            "response_headers": self.response_headers,
            "response_text": self.response_text,
            "ise_result_value": self.ise_result_value,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


RequestFunc = Callable[..., Any]


def normalize_mac(mac: str) -> str:
    """Normalize a supported MAC address string to uppercase colon format."""
    compact = mac.replace(":", "").replace("-", "").replace(".", "").upper()
    return ":".join(compact[index : index + 2] for index in range(0, len(compact), 2))


def extract_macs(text: str) -> list[str]:
    """Extract unique MAC addresses from text while preserving first-seen order."""
    unique_macs: list[str] = []
    seen: set[str] = set()

    for match in RE_MAC_PATTERN.findall(text):
        normalized = normalize_mac(match)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_macs.append(normalized)

    return unique_macs


def extract_macs_from_file(path: Path) -> list[str]:
    """Read text from path and extract unique MAC addresses."""
    return extract_macs(path.read_text(encoding="utf-8"))


def build_coa_url(*, host: str, node: str, mac: str) -> str:
    """Build the Cisco ISE CoA Reauth API URL."""
    return f"https://{host}/admin/API/mnt/CoA/Reauth/{node}/{mac}/0"


def perform_coa_request(
    *,
    mac: str,
    host: str,
    node: str,
    username: str,
    password: str,
    verify_tls: bool,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    request_func: RequestFunc = requests.get,
) -> CoaResult:
    """Perform one Cisco ISE CoA request and classify the result."""
    url = build_coa_url(host=host, node=node, mac=mac)
    start = perf_counter()

    try:
        response = request_func(
            url,
            headers=HEADERS,
            verify=verify_tls,
            auth=(username, password),
            timeout=timeout,
        )
    except requests.exceptions.SSLError as exc:
        return CoaResult(
            mac=mac,
            success=False,
            result_message="HTTPS certificate validation failed",
            seconds=_elapsed_seconds(start),
            request_url=url,
            verify_tls=verify_tls,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
    except requests.RequestException as exc:
        return CoaResult(
            mac=mac,
            success=False,
            result_message="Undefined failure",
            seconds=_elapsed_seconds(start),
            request_url=url,
            verify_tls=verify_tls,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    seconds = _elapsed_seconds(start)
    status_code = getattr(response, "status_code", None)
    response_headers = _response_headers(response)
    response_text = getattr(response, "text", None)
    result_value = _extract_remote_coa_result(response_text or "")
    success, result_message = _classify_coa_response(
        response_status_code=status_code,
        response_text=response_text,
        ise_result_value=result_value,
    )

    return CoaResult(
        mac=mac,
        success=success,
        result_message=result_message,
        seconds=seconds,
        request_url=url,
        verify_tls=verify_tls,
        response_status_code=status_code,
        response_headers=response_headers,
        response_text=response_text,
        ise_result_value=result_value,
    )


def run_coa_requests(
    *,
    macs: Iterable[str],
    host: str,
    node: str,
    username: str,
    password: str,
    max_workers: int,
    insecure: bool,
) -> Iterable[CoaResult]:
    """Run CoA requests concurrently and yield results as they complete."""
    verify_tls = not insecure
    if insecure:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_mac = {
            executor.submit(
                perform_coa_request,
                mac=mac,
                host=host,
                node=node,
                username=username,
                password=password,
                verify_tls=verify_tls,
            ): mac
            for mac in macs
        }

        for future in as_completed(future_to_mac):
            mac = future_to_mac[future]
            try:
                yield future.result()
            except Exception as exc:
                yield CoaResult(
                    mac=mac,
                    success=False,
                    result_message="Undefined failure",
                    seconds=0.0,
                    request_url=build_coa_url(host=host, node=node, mac=mac),
                    verify_tls=verify_tls,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )


def results_to_json_data(
    results: Iterable[CoaResult],
    *,
    mac_order: Iterable[str],
) -> list[dict[str, Any]]:
    """Serialize results, ordered by the original MAC input order."""
    result_list = list(results)
    result_by_mac = {result.mac: result for result in result_list}
    ordered_results: list[CoaResult] = []
    seen: set[str] = set()

    for mac in mac_order:
        result = result_by_mac.get(mac)
        if result is None:
            continue
        ordered_results.append(result)
        seen.add(mac)

    ordered_results.extend(result for result in result_list if result.mac not in seen)
    return [result.to_json_dict() for result in ordered_results]


def write_results_json(
    path: Path,
    results: Iterable[CoaResult],
    *,
    mac_order: Iterable[str],
) -> None:
    """Write pretty JSON results, creating parent directories as needed."""
    data = results_to_json_data(results, mac_order=mac_order)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _elapsed_seconds(start: float) -> float:
    return round(perf_counter() - start, 2)


def _response_headers(response: Any) -> dict[str, str] | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    return {str(key): str(value) for key, value in dict(headers).items()}


def _classify_coa_response(
    *,
    response_status_code: int | None,
    response_text: str | None,
    ise_result_value: str | None,
) -> tuple[bool, str]:
    if response_status_code in (401, 403):
        return False, "Invalid API credentials"

    if response_text and MAC_NOT_VALID_SESSION_TEXT in response_text:
        return False, "MAC address not a valid session"

    if ise_result_value is not None:
        normalized_result = ise_result_value.casefold()
        if normalized_result == "true":
            return True, "CoA Succeeded"
        if normalized_result == "false":
            return False, "CoA attempted but no response from network device"

    return False, "Undefined failure"


def _extract_remote_coa_result(xml_text: str) -> str | None:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return None

    remote_coa = _find_first_element(root, "remoteCoA")
    if remote_coa is None:
        return None

    results = _find_first_element(remote_coa, "results")
    if results is None or results.text is None:
        return None

    return results.text.strip()


def _find_first_element(root: ElementTree.Element, local_name: str) -> ElementTree.Element | None:
    for element in root.iter():
        if _local_name(element.tag) == local_name:
            return element
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]
