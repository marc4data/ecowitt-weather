"""Ecowitt Cloud API v3: request construction and verbatim raw capture.

Deliberately narrow (PHASE0 §2). Build a request, send it, write the response
to disk before anything parses it. No retry framework, no abstraction layer,
no business logic. This is the one part of Phase 0 expected to survive into
Phase 1, so it enforces the constraints rather than leaving them to callers:

  - credentials never reach disk or log output (PHASE0 §4)
  - the raw file exists even when parsing fails (PHASE0 §5)
  - UTC everywhere, never naive datetimes (PHASE0 §11)
  - a non-zero API `code` is a failure regardless of HTTP status (CLAUDE.md §5.1)
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.ecowitt.net/api/v3"

# Generous: the 90d × 5min probe cell may return a very large body, and
# measuring how long that takes is itself a Phase 0 finding (PHASE0 §6).
REQUEST_TIMEOUT_S = 180

# "Be polite to the API. Sequential requests, a small delay between them." (§11)
POLITE_DELAY_S = 2.0

# Redacted from any URL that is written to disk or logged. `mac` is identifying
# but not a credential, and samples/raw/ is gitignored — it stays readable so
# captures remain interpretable. Report generators must never echo it, because
# samples/reports/ IS committed.
SECRET_PARAMS = frozenset({"application_key", "api_key"})
REDACTED = "REDACTED"

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class DiscoveryError(Exception):
    """Base for errors that should terminate a discovery run non-zero."""


class ConfigError(DiscoveryError):
    """Missing or malformed configuration. Exit code 2."""


class ApiError(DiscoveryError):
    """Transport failure, or an API `code` field that is not 0."""


@dataclass(frozen=True)
class Credentials:
    application_key: str
    api_key: str
    mac: str | None = None

    @classmethod
    def from_env(cls, *, require_mac: bool = True) -> Credentials:
        """Load from .env / environment. Fails loudly; never prompts, never defaults."""
        load_dotenv()

        wanted = [
            ("application_key", "ECOWITT_APPLICATION_KEY", True),
            ("api_key", "ECOWITT_API_KEY", True),
            ("mac", "ECOWITT_MAC", require_mac),
        ]
        values: dict[str, str | None] = {}
        missing: list[str] = []

        for attr, env_name, required in wanted:
            raw = (os.environ.get(env_name) or "").strip()
            if not raw:
                if required:
                    missing.append(env_name)
                values[attr] = None
            else:
                values[attr] = raw

        if missing:
            raise ConfigError(
                "Missing required environment variable(s): "
                + ", ".join(missing)
                + ".\nCopy .env.example to .env and fill them in. "
                "See README for how to obtain the MAC."
            )
        return cls(**values)  # type: ignore[arg-type]


@dataclass
class RawResponse:
    """One captured API call. `payload` is None when the body was not valid JSON."""

    endpoint: str
    label: str
    requested_at: datetime
    duration_s: float
    http_status: int
    body_bytes: int
    raw_path: Path
    meta_path: Path
    payload: Any | None = None
    parse_error: str | None = None
    redacted_url: str = ""
    response_headers: dict[str, str] = field(default_factory=dict)

    @property
    def api_code(self) -> Any | None:
        """The API's own `code` field. HTTP 200 does not imply success."""
        if isinstance(self.payload, dict):
            return self.payload.get("code")
        return None

    @property
    def api_message(self) -> Any | None:
        if isinstance(self.payload, dict):
            return self.payload.get("msg") or self.payload.get("message")
        return None

    @property
    def ok(self) -> bool:
        return self.http_status == 200 and self.api_code in (0, "0")

    def failure_reason(self) -> str | None:
        if self.http_status != 200:
            return f"HTTP {self.http_status}"
        if self.parse_error:
            return f"response was not valid JSON: {self.parse_error}"
        if self.api_code not in (0, "0"):
            return f"API code={self.api_code!r} msg={self.api_message!r}"
        return None

    def raise_if_failed(self) -> RawResponse:
        reason = self.failure_reason()
        if reason:
            raise ApiError(f"{self.endpoint} ({self.label}) failed: {reason}. Raw: {self.raw_path}")
        return self


def redact_url(url: str) -> str:
    """Strip credential query parameters from a URL so it is safe to persist."""
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    safe = [(k, REDACTED if k in SECRET_PARAMS else v) for k, v in pairs]
    return urlunsplit(parts._replace(query=urlencode(safe)))


def _slug(text: str) -> str:
    return _UNSAFE_FILENAME.sub("-", text).strip("-") or "unlabeled"


class EcowittClient:
    """Sequential, capture-everything client. One instance per discovery run."""

    def __init__(
        self,
        credentials: Credentials,
        raw_dir: Path,
        *,
        delay_s: float = POLITE_DELAY_S,
        timeout_s: int = REQUEST_TIMEOUT_S,
        session: requests.Session | None = None,
    ) -> None:
        self.credentials = credentials
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.delay_s = delay_s
        self.timeout_s = timeout_s
        self._session = session or requests.Session()
        self._last_request_ended: float | None = None

    def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        *,
        label: str,
        include_mac: bool = True,
    ) -> RawResponse:
        """Send one GET, capture it verbatim, then attempt to parse.

        Never raises on an API-level failure — the caller decides, via
        `raise_if_failed()`, whether a failure is fatal or is itself the finding
        being recorded (PHASE0 §9 expects error responses to be captured).
        """
        query: dict[str, Any] = {
            "application_key": self.credentials.application_key,
            "api_key": self.credentials.api_key,
        }
        if include_mac:
            if not self.credentials.mac:
                raise ConfigError(f"{endpoint} requires ECOWITT_MAC, which is not set.")
            query["mac"] = self.credentials.mac
        query.update(params or {})

        self._respect_delay()

        url = f"{BASE_URL}/{endpoint.lstrip('/')}"
        requested_at = datetime.now(timezone.utc)
        started = time.monotonic()
        try:
            response = self._session.get(url, params=query, timeout=self.timeout_s)
        except requests.RequestException as exc:
            self._last_request_ended = time.monotonic()
            raise ApiError(f"{endpoint} ({label}) transport failure: {exc}") from exc
        duration = time.monotonic() - started
        self._last_request_ended = time.monotonic()

        # Capture first, parse second. If this process dies on the next line,
        # the response is still on disk.
        raw_path, meta_path = self._write_capture(
            endpoint=endpoint,
            label=label,
            requested_at=requested_at,
            duration_s=duration,
            response=response,
        )

        payload: Any | None = None
        parse_error: str | None = None
        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            parse_error = str(exc)

        return RawResponse(
            endpoint=endpoint,
            label=label,
            requested_at=requested_at,
            duration_s=duration,
            http_status=response.status_code,
            body_bytes=len(response.content),
            raw_path=raw_path,
            meta_path=meta_path,
            payload=payload,
            parse_error=parse_error,
            redacted_url=redact_url(response.url),
            response_headers=dict(response.headers),
        )

    def real_time(self, *, call_back: str = "all", label: str = "all", **extra: Any) -> RawResponse:
        return self.get("device/real_time", {"call_back": call_back, **extra}, label=label)

    def history(
        self,
        *,
        start_date: datetime,
        end_date: datetime,
        cycle_type: str,
        call_back: str = "all",
        label: str,
        **extra: Any,
    ) -> RawResponse:
        """`start_date`/`end_date` must be timezone-aware.

        NOTE: the API's expected timezone for these strings is UNVERIFIED — that
        is exactly what PHASE0 §9 is meant to determine. Until it is settled,
        the wire format is emitted from the datetime as given and the caller is
        responsible for knowing which timezone it passed.
        """
        for name, value in (("start_date", start_date), ("end_date", end_date)):
            if value.tzinfo is None:
                raise ConfigError(f"{name} must be timezone-aware (PHASE0 §11).")

        return self.get(
            "device/history",
            {
                "start_date": start_date.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": end_date.strftime("%Y-%m-%d %H:%M:%S"),
                "cycle_type": cycle_type,
                "call_back": call_back,
                **extra,
            },
            label=label,
        )

    def device_list(self, *, label: str = "device-list", **extra: Any) -> RawResponse:
        """List devices on the account.

        UNVERIFIED (CLAUDE.md §5.1 lists only real_time and history). If this
        endpoint exists it yields the console MAC without reading the console.
        A non-zero code here is a finding, not a crash.
        """
        return self.get("device/list", dict(extra), label=label, include_mac=False)

    def _respect_delay(self) -> None:
        if self._last_request_ended is None:
            return
        remaining = self.delay_s - (time.monotonic() - self._last_request_ended)
        if remaining > 0:
            time.sleep(remaining)

    def _write_capture(
        self,
        *,
        endpoint: str,
        label: str,
        requested_at: datetime,
        duration_s: float,
        response: requests.Response,
    ) -> tuple[Path, Path]:
        stamp = requested_at.strftime("%Y%m%dT%H%M%S.%f")[:-3] + "Z"
        base = f"{_slug(endpoint)}_{_slug(label)}_{stamp}"

        # Timestamps alone are not unique: two requests inside the same
        # millisecond would collide and the second would overwrite the first.
        # Losing a capture silently is the one thing this module exists to
        # prevent (PHASE0 §11), so disambiguate rather than trust the clock.
        stem, suffix = base, 0
        while (self.raw_dir / f"{stem}.json").exists():
            suffix += 1
            stem = f"{base}-{suffix}"

        raw_path = self.raw_dir / f"{stem}.json"
        meta_path = self.raw_dir / f"{stem}.meta.json"

        raw_path.write_bytes(response.content)

        meta = {
            "endpoint": endpoint,
            "label": label,
            "request_url_redacted": redact_url(response.url),
            "http_status": response.status_code,
            "response_headers": dict(response.headers),
            "body_bytes": len(response.content),
            "duration_s": round(duration_s, 4),
            "requested_at_utc": requested_at.isoformat(),
            # Kept for the timezone determination in PHASE0 §9: compare against
            # the `time` field on a real-time leaf.
            "requested_at_epoch": requested_at.timestamp(),
            "raw_file": raw_path.name,
        }
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
        return raw_path, meta_path
