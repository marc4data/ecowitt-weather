"""Minimal Phase 0 tests. Recorded fixtures only — never the live API.

Scope is deliberately small: the two things that are silently catastrophic if
wrong are credential leakage to disk and losing a raw capture when parsing
fails. Both are tested here.
"""

from __future__ import annotations

import json

import pytest

from discovery.client import (
    REDACTED,
    ApiError,
    ConfigError,
    Credentials,
    DiscoveryError,
    EcowittClient,
    RawResponse,
    redact_url,
)

APP_KEY = "APPKEY-should-never-appear"
API_KEY = "APIKEY-should-never-appear"
MAC = "AA:BB:CC:DD:EE:FF"


class FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200, url: str = ""):
        self.content = content
        self.status_code = status_code
        self.url = url
        self.headers = {"Content-Type": "application/json"}


class FakeSession:
    """Stands in for requests.Session. Records calls, returns canned bodies."""

    def __init__(self, response: FakeResponse):
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        query = "&".join(f"{k}={v}" for k, v in (params or {}).items())
        self._response.url = f"{url}?{query}"
        return self._response


@pytest.fixture
def credentials() -> Credentials:
    return Credentials(application_key=APP_KEY, api_key=API_KEY, mac=MAC)


def _client(tmp_path, credentials, body: bytes, status: int = 200) -> EcowittClient:
    return EcowittClient(
        credentials,
        tmp_path / "raw",
        delay_s=0,
        session=FakeSession(FakeResponse(body, status)),
    )


def test_redact_url_strips_both_credentials():
    url = (
        "https://api.ecowitt.net/api/v3/device/real_time"
        f"?application_key={APP_KEY}&api_key={API_KEY}&mac={MAC}&call_back=all"
    )
    result = redact_url(url)

    assert APP_KEY not in result
    assert API_KEY not in result
    assert result.count(REDACTED) == 2
    # mac and functional params survive — captures must stay interpretable
    assert "call_back=all" in result


def test_no_credential_reaches_disk(tmp_path, credentials):
    client = _client(tmp_path, credentials, json.dumps({"code": 0, "data": {}}).encode())
    response = client.real_time()

    for path in (response.raw_path, response.meta_path):
        text = path.read_text(encoding="utf-8")
        assert APP_KEY not in text
        assert API_KEY not in text

    assert REDACTED in response.meta_path.read_text(encoding="utf-8")


def test_raw_file_written_even_when_body_is_not_json(tmp_path, credentials):
    client = _client(tmp_path, credentials, b"<html>gateway timeout</html>")
    response = client.real_time()

    # Capture first, parse second: the body survives the parse failure.
    assert response.raw_path.read_bytes() == b"<html>gateway timeout</html>"
    assert response.payload is None
    assert response.parse_error
    assert not response.ok


def test_nonzero_api_code_is_failure_despite_http_200(tmp_path, credentials):
    body = json.dumps({"code": 40010, "msg": "Illegal MAC"}).encode()
    client = _client(tmp_path, credentials, body)
    response = client.real_time()

    assert response.http_status == 200
    assert not response.ok
    assert "40010" in (response.failure_reason() or "")
    with pytest.raises(ApiError):
        response.raise_if_failed()


def test_captures_are_additive_not_overwriting(tmp_path, credentials):
    client = _client(tmp_path, credentials, json.dumps({"code": 0}).encode())
    first = client.real_time(label="same-label")
    second = client.real_time(label="same-label")

    assert first.raw_path != second.raw_path
    assert len(list((tmp_path / "raw").glob("*.json"))) == 4  # 2 raw + 2 meta


def test_history_rejects_naive_datetimes(tmp_path, credentials):
    from datetime import datetime, timezone

    client = _client(tmp_path, credentials, b"{}")
    with pytest.raises(ConfigError, match="timezone-aware"):
        client.history(
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
            cycle_type="5min",
            label="naive",
        )


def test_missing_mac_is_config_error_not_a_silent_default(tmp_path):
    client = _client(tmp_path, Credentials(APP_KEY, API_KEY, mac=None), b"{}")
    with pytest.raises(ConfigError, match="ECOWITT_MAC"):
        client.real_time()


def test_device_list_omits_mac(tmp_path, credentials):
    client = _client(tmp_path, credentials, json.dumps({"code": 0}).encode())
    client.device_list()

    _, params = client._session.calls[0]
    assert "mac" not in params


def test_api_code_zero_as_string_counts_as_success():
    response = RawResponse(
        endpoint="device/real_time",
        label="t",
        requested_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        duration_s=0.0,
        http_status=200,
        body_bytes=0,
        raw_path=__import__("pathlib").Path("x"),
        meta_path=__import__("pathlib").Path("y"),
        payload={"code": "0"},
    )
    assert response.ok


def test_console_offset_sign_is_not_flipped(tmp_path, monkeypatch):
    """The API reads date strings as console-local: UTC = string - offset.

    A sign flip here does not fail loudly — it doubles the windowing error and
    the probe silently measures the wrong hours. Pin the direction.
    """
    import json
    from datetime import datetime, timedelta, timezone

    from discovery import probe

    console_offset = timedelta(hours=-5)  # UTC-5
    anchor = datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc)
    sent_start = anchor - timedelta(hours=18)
    # What the API actually serves for that string, per UTC = string - offset.
    first_point = int((sent_start - console_offset).timestamp())

    body = json.dumps(
        {
            "code": 0,
            "msg": "success",
            "data": {
                "outdoor": {
                    "temperature": {
                        "unit": "ºF",
                        "list": {str(first_point + n * 300): "78.0" for n in range(12)},
                    }
                }
            },
        }
    ).encode()

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return anchor if tz else anchor.replace(tzinfo=None)

    monkeypatch.setattr(probe, "datetime", FrozenDatetime)
    client = _client(tmp_path, Credentials(APP_KEY, API_KEY, MAC), body)
    detected = probe.detect_console_utc_offset(client)

    assert detected == console_offset, f"expected UTC-5, got {detected}"


def test_console_tz_prefers_device_info_over_measurement(tmp_path, credentials):
    """An IANA zone from /device/info must win over a measured fixed offset.

    A fixed offset is right only until the next DST transition, and is already
    wrong for any historical window straddling one — which is what backfill
    does. If this silently fell back to measurement, backfill would be an hour
    off for half the year and nothing would fail.
    """
    import json
    from zoneinfo import ZoneInfo

    from discovery import probe

    body = json.dumps(
        {"code": 0, "msg": "success", "data": {"date_zone_id": "America/Chicago"}}
    ).encode()
    client = _client(tmp_path, credentials, body)

    tz, source = probe.resolve_console_tz(client)

    assert tz == ZoneInfo("America/Chicago")
    assert "device/info" in source
    # One request only: measurement must not have been attempted.
    assert len(client._session.calls) == 1


def test_console_tz_falls_back_when_zone_missing(tmp_path, credentials):
    """No date_zone_id -> fall back to measurement rather than guessing UTC."""
    import json

    from discovery import probe

    body = json.dumps({"code": 0, "msg": "success", "data": {"name": "station"}}).encode()
    client = _client(tmp_path, credentials, body)

    # Measurement then fails on the empty history body, which must surface as a
    # DiscoveryError rather than a silent UTC default.
    with pytest.raises(DiscoveryError):
        probe.resolve_console_tz(client)
