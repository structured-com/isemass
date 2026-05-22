from __future__ import annotations

import requests
import urllib3

from isemass.coa import (
    HEADERS,
    REQUEST_TIMEOUT_SECONDS,
    CoaResult,
    build_coa_url,
    extract_macs,
    perform_coa_request,
    results_to_json_data,
    run_coa_requests,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        text: str = "",
        reason: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.reason = reason
        self.headers = headers


def test_extract_macs_normalizes_deduplicates_and_preserves_order() -> None:
    text = """
    unrelated text
    aa:bb:cc:dd:ee:ff
    AA-BB-CC-DD-EE-FF
    1234.5678.90ab
    00:11:22:33:44:55
    """

    assert extract_macs(text) == [
        "AA:BB:CC:DD:EE:FF",
        "12:34:56:78:90:AB",
        "00:11:22:33:44:55",
    ]


def test_build_coa_url() -> None:
    assert (
        build_coa_url(host="ise-mnt.example.com", node="ise-psn01", mac="AA:BB:CC:DD:EE:FF")
        == "https://ise-mnt.example.com/admin/API/mnt/CoA/Reauth/ise-psn01/AA:BB:CC:DD:EE:FF/0"
    )


def test_perform_coa_request_constructs_request_and_returns_success() -> None:
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(
            status_code=200,
            text="<remoteCoA><results>true</results></remoteCoA>",
            headers={"Content-Type": "application/xml"},
        )

    result = perform_coa_request(
        mac="AA:BB:CC:DD:EE:FF",
        host="ise-mnt.example.com",
        node="ise-psn01",
        username="api-user",
        password="api-password",
        verify_tls=False,
        request_func=fake_get,
    )

    assert captured == {
        "url": "https://ise-mnt.example.com/admin/API/mnt/CoA/Reauth/ise-psn01/AA:BB:CC:DD:EE:FF/0",
        "headers": HEADERS,
        "verify": False,
        "auth": ("api-user", "api-password"),
        "timeout": REQUEST_TIMEOUT_SECONDS,
    }
    assert result.success is True
    assert result.result_message == "CoA Succeeded"
    assert result.mac == "AA:BB:CC:DD:EE:FF"
    assert result.request_url == captured["url"]
    assert result.verify_tls is False
    assert result.response_status_code == 200
    assert result.response_headers == {"Content-Type": "application/xml"}
    assert result.response_text == "<remoteCoA><results>true</results></remoteCoA>"
    assert result.ise_result_value == "true"
    assert result.error_type is None
    assert result.error_message is None


def test_perform_coa_request_classifies_false_result_as_coa_failed() -> None:
    result = perform_coa_request(
        mac="AA:BB:CC:DD:EE:FF",
        host="ise-mnt.example.com",
        node="ise-psn01",
        username="api-user",
        password="api-password",
        verify_tls=True,
        request_func=lambda *args, **kwargs: FakeResponse(
            status_code=200,
            text="<remoteCoA><results>false</results></remoteCoA>",
        ),
    )

    assert result.success is False
    assert result.result_message == "CoA attempted but no response from network device"
    assert result.ise_result_value == "false"


def test_perform_coa_request_classifies_invalid_session_response() -> None:
    result = perform_coa_request(
        mac="AA:BB:CC:DD:EE:FF",
        host="ise-mnt.example.com",
        node="ise-psn01",
        username="api-user",
        password="api-password",
        verify_tls=True,
        request_func=lambda *args, **kwargs: FakeResponse(
            status_code=400,
            text=(
                "No NAS_IP_ADDRESS associated with the calling station id "
                "AA:BB:CC:DD:EE:FF. This CoA request can not be delivered."
            ),
        ),
    )

    assert result.success is False
    assert result.result_message == "MAC address not a valid session"


def test_perform_coa_request_classifies_malformed_xml_as_undefined_failure() -> None:
    result = perform_coa_request(
        mac="AA:BB:CC:DD:EE:FF",
        host="ise-mnt.example.com",
        node="ise-psn01",
        username="api-user",
        password="api-password",
        verify_tls=True,
        request_func=lambda *args, **kwargs: FakeResponse(status_code=200, text="<not-xml"),
    )

    assert result.success is False
    assert result.result_message == "Undefined failure"


def test_perform_coa_request_classifies_missing_result_as_undefined_failure() -> None:
    result = perform_coa_request(
        mac="AA:BB:CC:DD:EE:FF",
        host="ise-mnt.example.com",
        node="ise-psn01",
        username="api-user",
        password="api-password",
        verify_tls=True,
        request_func=lambda *args, **kwargs: FakeResponse(
            status_code=200,
            text="<remoteCoA><other>true</other></remoteCoA>",
        ),
    )

    assert result.success is False
    assert result.result_message == "Undefined failure"


def test_perform_coa_request_classifies_401_as_invalid_credentials() -> None:
    result = perform_coa_request(
        mac="AA:BB:CC:DD:EE:FF",
        host="ise-mnt.example.com",
        node="ise-psn01",
        username="api-user",
        password="api-password",
        verify_tls=True,
        request_func=lambda *args, **kwargs: FakeResponse(
            status_code=401,
            text="Unauthorized",
            reason="Unauthorized",
        ),
    )

    assert result.success is False
    assert result.result_message == "Invalid API credentials"
    assert result.response_status_code == 401
    assert result.response_text == "Unauthorized"


def test_perform_coa_request_classifies_403_as_invalid_credentials() -> None:
    result = perform_coa_request(
        mac="AA:BB:CC:DD:EE:FF",
        host="ise-mnt.example.com",
        node="ise-psn01",
        username="api-user",
        password="api-password",
        verify_tls=True,
        request_func=lambda *args, **kwargs: FakeResponse(
            status_code=403,
            text="Forbidden",
            reason="Forbidden",
        ),
    )

    assert result.success is False
    assert result.result_message == "Invalid API credentials"
    assert result.response_status_code == 403


def test_perform_coa_request_classifies_generic_http_error_as_undefined_failure() -> None:
    result = perform_coa_request(
        mac="AA:BB:CC:DD:EE:FF",
        host="ise-mnt.example.com",
        node="ise-psn01",
        username="api-user",
        password="api-password",
        verify_tls=True,
        request_func=lambda *args, **kwargs: FakeResponse(
            status_code=500,
            text="Server error",
            reason="Internal Server Error",
        ),
    )

    assert result.success is False
    assert result.result_message == "Undefined failure"
    assert result.response_status_code == 500


def test_perform_coa_request_classifies_ssl_error_as_certificate_failure() -> None:
    def fake_get(*args, **kwargs):
        raise requests.exceptions.SSLError("certificate verify failed")

    result = perform_coa_request(
        mac="AA:BB:CC:DD:EE:FF",
        host="ise-mnt.example.com",
        node="ise-psn01",
        username="api-user",
        password="api-password",
        verify_tls=True,
        request_func=fake_get,
    )

    assert result.success is False
    assert result.result_message == "HTTPS certificate validation failed"
    assert result.error_type == "SSLError"
    assert result.error_message == "certificate verify failed"


def test_perform_coa_request_classifies_timeout_as_request_failed() -> None:
    def fake_get(*args, **kwargs):
        raise requests.Timeout("timed out")

    result = perform_coa_request(
        mac="AA:BB:CC:DD:EE:FF",
        host="ise-mnt.example.com",
        node="ise-psn01",
        username="api-user",
        password="api-password",
        verify_tls=True,
        request_func=fake_get,
    )

    assert result.success is False
    assert result.result_message == "Undefined failure"
    assert result.error_type == "Timeout"
    assert result.error_message == "timed out"


def test_perform_coa_request_classifies_request_exception_as_request_failed() -> None:
    def fake_get(*args, **kwargs):
        raise requests.ConnectionError("connection refused")

    result = perform_coa_request(
        mac="AA:BB:CC:DD:EE:FF",
        host="ise-mnt.example.com",
        node="ise-psn01",
        username="api-user",
        password="api-password",
        verify_tls=True,
        request_func=fake_get,
    )

    assert result.success is False
    assert result.result_message == "Undefined failure"
    assert result.error_type == "ConnectionError"
    assert result.error_message == "connection refused"


def test_results_to_json_data_preserves_mac_order_and_serializes_fields() -> None:
    results = [
        CoaResult(
            mac="00:11:22:33:44:55",
            success=False,
            seconds=0.2,
            result_message="Invalid API credentials",
            request_url="https://example.test/second",
            verify_tls=True,
            response_status_code=401,
            response_headers={"Content-Type": "text/plain"},
            response_text="Unauthorized",
            error_type=None,
            error_message=None,
        ),
        CoaResult(
            mac="AA:BB:CC:DD:EE:FF",
            success=True,
            seconds=0.1,
            result_message="CoA Succeeded",
            request_url="https://example.test/first",
            verify_tls=False,
            response_status_code=200,
            response_headers={"Content-Type": "application/xml"},
            response_text="<remoteCoA><results>true</results></remoteCoA>",
            ise_result_value="true",
        ),
    ]

    data = results_to_json_data(
        results,
        mac_order=["AA:BB:CC:DD:EE:FF", "00:11:22:33:44:55"],
    )

    assert [entry["mac_address"] for entry in data] == [
        "AA:BB:CC:DD:EE:FF",
        "00:11:22:33:44:55",
    ]
    assert data[0]["success"] is True
    assert data[0]["request_method"] == "GET"
    assert data[0]["ise_result_value"] == "true"
    assert data[1]["success"] is False
    assert data[1]["result_message"] == "Invalid API credentials"
    assert data[1]["response_status_code"] == 401


def test_run_coa_requests_suppresses_urllib3_warning_when_insecure(monkeypatch) -> None:
    disabled_warning_categories = []

    def fake_disable_warnings(category):
        disabled_warning_categories.append(category)

    def fake_perform_coa_request(**kwargs):
        return CoaResult(
            mac=kwargs["mac"],
            success=True,
            seconds=0.0,
            result_message="mocked success",
        )

    monkeypatch.setattr("isemass.coa.urllib3.disable_warnings", fake_disable_warnings)
    monkeypatch.setattr("isemass.coa.perform_coa_request", fake_perform_coa_request)

    list(
        run_coa_requests(
            macs=["AA:BB:CC:DD:EE:FF"],
            host="ise-mnt.example.com",
            node="ise-psn01",
            username="api-user",
            password="api-password",
            max_workers=1,
            insecure=True,
        )
    )

    assert disabled_warning_categories == [urllib3.exceptions.InsecureRequestWarning]
