"""Cisco ISE CoA API helpers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from time import perf_counter
import re
from typing import Any, Callable, Iterable
from xml.etree import ElementTree

import requests

HEADERS = {
    "Accept": "application/xml",
}
REQUEST_TIMEOUT_SECONDS = 30

# REGEX for all formats of MAC address.
# "?:" removes groups so re.findall returns complete MAC address strings.
RE_MAC_COLON = r"(?:[0-9A-Fa-f]{2}:){5}(?:[0-9A-Fa-f]{2})"
RE_MAC_DASH = r"(?:[0-9A-Fa-f]{2}-){5}(?:[0-9A-Fa-f]{2})"
RE_MAC_CISCO = r"(?:[0-9A-Fa-f]{4}\.){2}(?:[0-9A-Fa-f]{4})"
RE_MAC_ALL = RE_MAC_COLON + r"|" + RE_MAC_DASH + r"|" + RE_MAC_CISCO
RE_MAC_PATTERN = re.compile(RE_MAC_ALL)


class CoaStatus(StrEnum):
    """Normalized CoA request outcome."""

    REQUEST_FAILED = "request_failed"
    COA_FAILED = "coa_failed"
    SUCCEEDED = "succeeded"


@dataclass(frozen=True)
class CoaResult:
    """Result for one MAC address CoA request."""

    mac: str
    status: CoaStatus
    seconds: float
    detail: str


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
    except requests.RequestException as exc:
        return CoaResult(
            mac=mac,
            status=CoaStatus.REQUEST_FAILED,
            seconds=_elapsed_seconds(start),
            detail=f"API request failed: {exc}",
        )
    
    # TEMP TESTING. MIGHT BE USED FOR VERBOSITY LATER
    # print(response.status_code, response.headers, response.text)

    seconds = _elapsed_seconds(start)
    status_code = getattr(response, "status_code", None)
    if status_code is None or not 200 <= status_code < 300:
        reason = getattr(response, "reason", "")
        reason_text = f" {reason}" if reason else ""
        return CoaResult(
            mac=mac,
            status=CoaStatus.REQUEST_FAILED,
            seconds=seconds,
            detail=f"HTTP {status_code}{reason_text}",
        )

    result_value = _extract_remote_coa_result(getattr(response, "text", ""))
    if result_value is None:
        return CoaResult(
            mac=mac,
            status=CoaStatus.COA_FAILED,
            seconds=seconds,
            detail="ISE response did not include remoteCoA.results",
        )

    if result_value.casefold() == "true":
        return CoaResult(
            mac=mac,
            status=CoaStatus.SUCCEEDED,
            seconds=seconds,
            detail="ISE remoteCoA.results=true",
        )

    return CoaResult(
        mac=mac,
        status=CoaStatus.COA_FAILED,
        seconds=seconds,
        detail=f"ISE remoteCoA.results={result_value}",
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
                    status=CoaStatus.REQUEST_FAILED,
                    seconds=0.0,
                    detail=f"Unexpected worker error: {exc}",
                )


def _elapsed_seconds(start: float) -> float:
    return round(perf_counter() - start, 2)


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
