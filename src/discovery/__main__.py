"""CLI entry point for Phase 0 discovery.

Subcommands are separate on purpose. Field inventory needs real-time samples
≥5 minutes apart (PHASE0 §7), so a single monolithic run would block for ten
minutes and lose everything on one failure. Each subcommand is short and
re-runnable; timestamped filenames make re-runs additive, never destructive.

Exit codes:  0 success  ·  1 run failed  ·  2 configuration problem
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import ApiError, ConfigError, Credentials, DiscoveryError, EcowittClient, RawResponse

DEFAULT_RAW_DIR = Path("samples/raw")


def _summarize(response: RawResponse) -> None:
    print(f"  HTTP status   : {response.http_status}")
    print(f"  API code      : {response.api_code!r}")
    if response.api_message:
        print(f"  API message   : {response.api_message!r}")
    print(f"  Body size     : {response.body_bytes:,} bytes")
    print(f"  Duration      : {response.duration_s:.2f}s")
    print(f"  Raw capture   : {response.raw_path}")


def _top_level_shape(payload: Any, prefix: str = "data", depth: int = 2) -> list[str]:
    """Shallow key listing, so `check` reports shape without asserting one."""
    node = payload.get(prefix) if isinstance(payload, dict) else None
    if not isinstance(node, dict):
        return []
    lines: list[str] = []
    for key, value in node.items():
        if isinstance(value, dict) and depth > 1:
            children = ", ".join(list(value.keys())[:8])
            lines.append(f"    {key}: {{{children}}}")
        else:
            lines.append(f"    {key}: {type(value).__name__}")
    return lines


def cmd_check(args: argparse.Namespace) -> int:
    """Credential smoke test: one real_time call with call_back=all."""
    credentials = Credentials.from_env(require_mac=True)
    client = EcowittClient(credentials, args.raw_dir)

    print("Calling /device/real_time with call_back=all ...")
    response = client.real_time(label="check-all")
    _summarize(response)

    reason = response.failure_reason()
    if reason:
        print(f"\nFAILED: {reason}", file=sys.stderr)
        return 1

    shape = _top_level_shape(response.payload)
    if shape:
        print("\n  data keys:")
        print("\n".join(shape))
    else:
        print("\n  NOTE: no `data` object in the response — inspect the raw capture.")

    print("\nOK. Credentials and MAC are valid.")
    return 0


def cmd_devices(args: argparse.Namespace) -> int:
    """Attempt /device/list to recover the console MAC without the console.

    This endpoint is not documented in CLAUDE.md §5.1. A failure here is a
    recorded observation for api_behavior.md (D4), not a broken run — so this
    returns 0 either way and says which happened.
    """
    credentials = Credentials.from_env(require_mac=False)
    client = EcowittClient(credentials, args.raw_dir)

    print("Calling /device/list (UNVERIFIED endpoint) ...")
    response = client.device_list()
    _summarize(response)

    reason = response.failure_reason()
    if reason:
        print(f"\nNot usable: {reason}")
        print("Read the MAC off the console's Weather Server page instead.")
        return 0

    print(json.dumps(response.payload, indent=2, ensure_ascii=False)[:4000])
    print("\nLook for a `mac` field above and put it in .env as ECOWITT_MAC.")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Granularity probe (D2). Writes samples/reports/granularity.md."""
    from datetime import datetime, timedelta, timezone

    from . import probe

    credentials = Credentials.from_env(require_mac=True)
    client = EcowittClient(credentials, args.raw_dir)

    if args.console_offset is None:
        print("Detecting console UTC offset ...")
        offset = probe.detect_console_utc_offset(client)
    else:
        offset = timedelta(hours=args.console_offset)
    print(f"  console offset: {offset.total_seconds() / 3600:+.2f} h")

    total = len(probe.SPANS) * len(probe.CYCLE_TYPES) + len(probe.RETENTION_AGES_DAYS)
    print(f"Running {total} probe requests (ascending span, sequential) ...")
    run_state = probe.run(client, offset=offset)

    for result in run_state.results:
        note = result.error or f"n={result.point_count:,} honored={result.honored}"
        print(
            f"  {result.kind:9} {result.cycle_type:5} {result.span_label:8} "
            f"code={result.api_code} {note}"
        )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        probe.render_markdown(run_state, generated_at=datetime.now(timezone.utc)),
        encoding="utf-8",
    )
    print(f"\nMax span honoring 5min : {run_state.max_honored_span}")
    print(f"Silent downgrade       : {'YES' if run_state.silent_downgrade else 'no'}")
    print(f"Report                 : {args.report}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="discovery", description=__doc__)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help=f"where verbatim captures are written (default: {DEFAULT_RAW_DIR})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="verify credentials with one real_time call").set_defaults(
        func=cmd_check
    )
    sub.add_parser("devices", help="try to recover the console MAC from the account").set_defaults(
        func=cmd_devices
    )

    probe_parser = sub.add_parser("probe", help="granularity probe (D2)")
    probe_parser.add_argument(
        "--report",
        type=Path,
        default=Path("samples/reports/granularity.md"),
        help="where the D2 report is written",
    )
    probe_parser.add_argument(
        "--console-offset",
        type=float,
        default=None,
        help="console UTC offset in hours (e.g. -5). Detected automatically if omitted.",
    )
    probe_parser.set_defaults(func=cmd_probe)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except (ApiError, DiscoveryError) as exc:
        print(f"Discovery failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
