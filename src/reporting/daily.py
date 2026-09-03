"""The entry point. One module, invoked two ways.

    python -m reporting.daily                              dry-run, yesterday
    python -m reporting.daily --for-date 2026-08-21         dry-run, that day
    python -m reporting.daily --test                        Marc only
    python -m reporting.daily --test --for-date 2026-08-21  Marc only, that day
    python -m reporting.daily --send                        PRODUCTION, all three

The Airflow DAG and the systemd timer both call THIS, so nothing about the
report knows which one invoked it. If that stops being true, the Airflow version
stops being a demonstration of the production path and becomes a second
implementation.

§5 is a safety requirement, not a convenience feature: the system must make it
difficult to accidentally send three people an alarming email about a condition
that is a week old. Hence a harmless default, two address lists that never
substitute for each other, a refusal on `--send --for-date`, and a banner on
every replay.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import config, data, render
from . import report as report_mod
from . import send as send_mod


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m reporting.daily",
        description="Build the daily lakehouse email. Sends nothing unless told to.",
    )
    parser.add_argument(
        "--for-date",
        metavar="YYYY-MM-DD",
        help="report on this local calendar day instead of yesterday",
    )
    parser.add_argument(
        "--test", action="store_true", help=f"send to {config.ENV_TEST_TO} (Marc only)"
    )
    parser.add_argument(
        "--send", action="store_true", help=f"PRODUCTION: send to {config.ENV_PRODUCTION_TO}"
    )
    parser.add_argument(
        "--force-backfill-send",
        action="store_true",
        help="allow --send with --for-date (see §5.3 before using this)",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="send a SYNTHETIC action email to the test address; needs no database",
    )
    parser.add_argument(
        "--no-triage",
        action="store_true",
        help="skip the Claude rewrite of an ACTION email's opening",
    )
    parser.add_argument(
        "--no-charts", action="store_true", help="skip the PNGs; the text alternative is unaffected"
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        help=f"where a dry run writes the email (default {config.PREVIEW_DIR})",
    )
    return parser.parse_args(argv)


def resolve_date(raw: str | None) -> date:
    """Yesterday, or the requested day -- refusing anything outside the record.

    A future date and a date before the station existed are different mistakes
    and get different messages, because "no data" would be a misleading answer
    to both (§8.9).
    """
    if raw is None:
        return report_mod.yesterday()
    try:
        wanted = date.fromisoformat(raw)
    except ValueError:
        raise SystemExit(f"--for-date {raw!r} is not a date. Use YYYY-MM-DD.") from None

    today = datetime.now(ZoneInfo(config.DISPLAY_ZONE)).date()
    if wanted >= today:
        raise SystemExit(
            f"--for-date {wanted} is today or later. A day can only be reported on "
            "once it has finished; the newest reportable day is "
            f"{report_mod.yesterday()}."
        )
    if wanted < config.HISTORY_START:
        raise SystemExit(
            f"--for-date {wanted} is before the record starts ({config.HISTORY_START}). "
            "There is no data for it, and an empty report would look like a broken "
            "pipeline rather than a day that never existed."
        )
    return wanted


def resolve_mode(args: argparse.Namespace, for_date: date) -> str:
    """dry-run | test | production, with §5.3's refusal enforced here.

    `--send --for-date` is refused rather than warned about. The whole point of
    `--for-date` is reproducing a past condition to look at the email it makes;
    an ACTION email dated today but describing 21 August tells three people the
    house is broken NOW. Best case that is confusing. Worst case somebody drives
    out to Eufaula.
    """
    if args.send and args.test:
        raise SystemExit("--send and --test are different address lists. Pick one.")
    if not args.send and not args.test:
        return "dry-run"
    if args.test:
        return "test"

    if args.for_date and for_date != report_mod.yesterday():
        if not args.force_backfill_send:
            raise SystemExit(
                f"REFUSED: --send with --for-date {for_date}.\n\n"
                "A production email describing a day that is not yesterday tells three\n"
                "people the house is broken now, when it may have been broken a week ago.\n\n"
                "  To look at that day's email:      --for-date "
                f"{for_date}            (writes to disk, sends nothing)\n"
                "  To send it to yourself only:      --test --for-date "
                f"{for_date}\n"
                "  If you genuinely mean it:         --send --for-date "
                f"{for_date} --force-backfill-send"
            )
        print(
            f"WARNING: sending a PRODUCTION email for {for_date}, which is not "
            "yesterday. It carries a REPLAY banner."
        )
    return "production"


def run_selftest(args: argparse.Namespace) -> int:
    """Prove the delivery path, with no database and no real condition.

    Always the test list. There is no flag that widens this: the most valuable
    moment to ask "does the alerting still work" is when something is broken,
    and a self-test that could reach the family on a bad day would be a trap
    rather than a check.
    """
    from . import selftest

    built = selftest.synthetic_report()
    rendered = render.render(built, with_charts=False)
    print(f"selftest  {rendered.subject}")

    if not (args.test or args.send):
        # Its own directory: a synthetic email must never overwrite the preview
        # of the real one for the same day.
        from pathlib import Path

        path = send_mod.write_preview(
            rendered, built.for_date, Path(args.out or config.PREVIEW_DIR) / "selftest"
        )
        print(f"  wrote {path}  — nothing was sent (add --test to actually send)")
        return 0

    outcome = send_mod.send(built, rendered, mode="test", log_conn=None)
    if not outcome["sent"]:
        print(f"  NOT SENT — {outcome['error']}")
        return 1
    print(f"  sent to {', '.join(outcome['recipients'])}")
    return 0


def _load_env() -> None:
    """Read `.env` on a workstation, the way `discovery.client` already does.

    Does NOT override anything already in the environment, which is what makes
    it safe on the VM: systemd supplies the address lists and `run_report.sh`
    supplies the secrets, and a stale `.env` that somehow got deployed could not
    quietly redirect the household's email to somewhere else.

    Missing python-dotenv is not fatal -- exported variables still work.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except ImportError:  # never fail the report over a convenience
        pass


def main(argv: list[str] | None = None) -> int:
    _load_env()
    args = parse_args(argv)
    if args.selftest:
        if args.send:
            raise SystemExit(
                "--selftest never goes to the production list. Drop --send; "
                "--selftest --test sends the synthetic email to the test address."
            )
        return run_selftest(args)

    for_date = resolve_date(args.for_date)
    mode = resolve_mode(args, for_date)

    generated_at = datetime.now(ZoneInfo(config.DISPLAY_ZONE))
    conn = data.connect_read()
    built = report_mod.build_report(conn, for_date, generated_at=generated_at, mode=mode)

    # An enhancement, never a precondition. `triage` promises not to raise, but
    # that promise lives in another module and one careless edit there would
    # cost the email -- the exact failure this whole project is built against --
    # so it is enforced here too.
    if not args.no_triage and built.severity == "alert":
        try:
            from dataclasses import replace

            from . import triage as triage_mod

            if summary := triage_mod.triage(built):
                built = replace(built, summary=summary)
        except Exception as exc:  # never raise from the report path
            print(f"triage raised, sending the plain email ({type(exc).__name__}: {exc})")

    rendered = render.render(built, with_charts=not args.no_charts)

    print(f"{built.for_date}  {built.severity.upper():5}  {rendered.subject}")
    if built.is_replay:
        print("  (replay — the email carries its banner in both bodies)")

    if mode == "dry-run":
        path = send_mod.write_preview(rendered, for_date, args.out)
        print(f"  wrote {path}  — nothing was sent")
        return 0

    with data.email_log_writer() as log_conn:
        outcome = send_mod.send(built, rendered, mode=mode, log_conn=log_conn)

    if outcome["duplicate"]:
        print(f"  already sent ({mode}) for {for_date} — no second email")
        return 0
    if not outcome["sent"]:
        print(f"  NOT SENT — {outcome['error']}")
        return 1
    print(
        f"  sent to {', '.join(outcome['recipients'])}"
        f"{'' if outcome['recorded'] else '  (email_log NOT written)'}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except send_mod.Refused as refusal:
        # A refusal is a decision, not a crash: it prints its reason and exits
        # non-zero so a timer's failure is visible, without a traceback that
        # would make a deliberate safety stop look like a bug.
        print(f"REFUSED: {refusal}", file=sys.stderr)
        sys.exit(2)
