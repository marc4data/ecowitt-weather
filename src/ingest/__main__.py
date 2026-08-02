"""Phase 1 ingestion CLI.

    python -m ingest incremental          # hourly: last 4h
    python -m ingest reconcile            # daily: previous 24h, 12h chunks
    python -m ingest backfill --days 7    # explicit window, 12h chunks
    python -m ingest gaps --days 30       # find missing slots, refetch them

Exit codes:  0 success  ·  1 run failed  ·  2 configuration problem

Every mode writes exactly one run_log row. A crash leaves it visibly wedged in
'running' rather than leaving no row at all — §7's whole point is that absence
of a row means the job did not run.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from discovery.client import ConfigError, Credentials, DiscoveryError, EcowittClient
from discovery.probe import resolve_console_tz

from . import config, db
from .pipeline import ResolutionError, chunks, fetch_and_load

RAW_DIR = "samples/raw"


def _floor_5min(when: datetime) -> datetime:
    return when.replace(minute=(when.minute // 5) * 5, second=0, microsecond=0)


def _run(
    args: argparse.Namespace,
    *,
    mode: str,
    trigger: str,
    windows: list[tuple[datetime, datetime]],
    source: str = "observed",
) -> int:
    settings = config.Settings.from_env()
    client = EcowittClient(Credentials.from_env(), args.raw_dir, delay_s=settings.polite_delay_s)
    console_tz, tz_source = resolve_console_tz(client)
    print(f"console timezone: {console_tz} ({tz_source})")

    conn = db.connect(settings.dsn)
    try:
        span_start = min(w[0] for w in windows)
        span_end = max(w[1] for w in windows)
        with db.run_logged(
            conn,
            trigger=trigger,
            mode=mode,
            window_start=span_start,
            window_end=span_end,
            cycle_type=config.CYCLE_TYPE,
        ) as state:
            total = state["counts"]
            for index, (start, end) in enumerate(windows, 1):
                label = f"{mode}-{start:%Y%m%dT%H%M}-{end:%H%M}"
                print(f"[{index}/{len(windows)}] {start:%Y-%m-%d %H:%M} -> {end:%H:%M} UTC")
                chunk = fetch_and_load(
                    client,
                    conn,
                    run_id=state["run_id"],
                    station_id=settings.station_id,
                    console_tz=console_tz,
                    start_utc=start,
                    end_utc=end,
                    label=label,
                    source=source,
                )
                c = chunk.counts
                print(
                    f"    points={chunk.point_count} spacing={chunk.observed_delta_s}s "
                    f"inserted={c.inserted} updated={c.updated} "
                    f"unchanged={c.unchanged} rejected={c.rejected}"
                )
                total.inserted += c.inserted
                total.updated += c.updated
                total.unchanged += c.unchanged
                total.rejected += c.rejected
                if chunk.observed_delta_s is not None:
                    state["observed_delta_s"] = chunk.observed_delta_s

            print(
                f"\nrun {state['run_id']}: fetched={total.fetched} "
                f"inserted={total.inserted} updated={total.updated} "
                f"unchanged={total.unchanged} rejected={total.rejected}"
            )
            if total.updated and mode != "incremental":
                print(
                    f"NOTE: {total.updated} values changed on re-fetch. See change_log — "
                    "a reconciliation reporting many updates is a signal, not routine."
                )
    finally:
        conn.close()
    return 0


def cmd_incremental(args: argparse.Namespace) -> int:
    end = _floor_5min(datetime.now(timezone.utc))
    return _run(
        args,
        mode="incremental",
        trigger="scheduled",
        windows=[(end - config.INCREMENTAL_WINDOW, end)],
    )


def cmd_reconcile(args: argparse.Namespace) -> int:
    end = _floor_5min(datetime.now(timezone.utc))
    return _run(
        args,
        mode="reconcile",
        trigger="reconcile",
        windows=chunks(end - timedelta(days=1), end, config.CHUNK),
    )


def cmd_backfill(args: argparse.Namespace) -> int:
    end = _floor_5min(datetime.now(timezone.utc))
    return _run(
        args,
        mode="backfill",
        trigger="backfill",
        windows=chunks(end - timedelta(days=args.days), end, config.CHUNK),
        source="backfilled",
    )


def cmd_gaps(args: argparse.Namespace) -> int:
    """Find missing 5-minute slots and refetch only the chunks containing them."""
    settings = config.Settings.from_env()
    conn = db.connect(settings.dsn)
    try:
        end = _floor_5min(datetime.now(timezone.utc))
        start = end - timedelta(days=args.days)
        missing = db.missing_slots(conn, settings.station_id, start, end)
    finally:
        conn.close()

    if not missing:
        print(f"No missing slots in the last {args.days} days.")
        return 0

    # Collapse slots into the chunks that contain them, so a day with two
    # scattered dropouts costs two requests rather than 288.
    wanted: set[datetime] = set()
    for slot in missing:
        anchor = start + config.CHUNK * ((slot - start) // config.CHUNK)
        wanted.add(anchor)
    windows = sorted((a, min(a + config.CHUNK, end)) for a in wanted)

    pct = 100.0 * len(missing) / max(1, int((end - start) / timedelta(minutes=5)))
    print(f"{len(missing)} missing slots ({pct:.1f}%) across {len(windows)} chunk(s)")
    return _run(args, mode="gap-sweep", trigger="backfill", windows=windows, source="backfilled")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ingest", description=__doc__)
    parser.add_argument("--raw-dir", default=RAW_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("incremental", help="hourly pull, last 4h").set_defaults(func=cmd_incremental)
    sub.add_parser("reconcile", help="daily re-fetch of the previous 24h").set_defaults(
        func=cmd_reconcile
    )
    bf = sub.add_parser("backfill", help="explicit window in 12h chunks")
    bf.add_argument("--days", type=int, default=7)
    bf.set_defaults(func=cmd_backfill)
    gp = sub.add_parser("gaps", help="refetch chunks containing missing slots")
    gp.add_argument("--days", type=int, default=30)
    gp.set_defaults(func=cmd_gaps)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except ResolutionError as exc:
        print(f"RESOLUTION MISMATCH: {exc}", file=sys.stderr)
        return 1
    except (DiscoveryError, RuntimeError) as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
