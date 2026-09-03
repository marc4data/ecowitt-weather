"""Optional: have Claude write the top of the ACTION email in plain English.

§6.3 — Claude writes the opening of an ACTION email in plain English, and the
email sends in its plain form when it cannot. Same rule as cfdb: **the summary
is an enhancement to the alert, never a precondition for it.**

⚠️ IT DELIBERATELY DOES NOT WRITE "WHAT TO DO", which §6.3 originally asked of
it. The email already has a what-to-do section built from the failing checks and
the configured contacts -- real phone numbers, and advice written once and
reviewed -- and printing a second, chattier version above it made the same email
say the same thing twice, the second time less precisely. A model paraphrasing
an instruction that is already exact is a downgrade, not an enhancement.
So Claude describes the situation; the code prescribes the response.

Three constraints, all consequences of running inside the send path:

  1. **It may never suppress an email.** Every path returns None rather than
     raising, and the caller falls back to the wording the checks produced
     themselves. An alert that failed to send because its summariser broke is
     strictly worse than a plainly-worded alert.
  2. **A hard timeout.** A hung HTTP call must cost seconds, not the morning
     email.
  3. **The SDK is imported lazily.** cfdb's `alert_triage.py` uses `urllib` to
     avoid any third-party dependency in the alert path, and the reasoning is
     sound -- but a lazy import inside a try/except buys the same protection
     (a missing or broken `anthropic` install degrades to the plain email)
     without hand-rolling an API client that would then have to be kept
     current. If the import fails, nothing is lost but the prose.

What is sent: the day's failing checks, their measurements, and the indoor
figures. No credentials, and nothing about the household -- addresses and
contacts never leave the machine.
"""

from __future__ import annotations

import json
import os

# Opus 5. This runs a handful of times a month at most -- once per bad morning
# -- so the cost of the better model is a rounding error against the cost of
# a badly-worded email about a house nobody is in.
MODEL = os.environ.get("LAKEHOUSE_TRIAGE_MODEL", "claude-opus-5")

# Deliberately short. A summary that arrives late is worth less than the email
# it is delaying, and the email is already fully written without it.
TIMEOUT_S = float(os.environ.get("LAKEHOUSE_TRIAGE_TIMEOUT", "25"))

MAX_TOKENS = 1024

SYSTEM_PROMPT = """\
You are writing the top of an email about a lake house in rural Oklahoma that \
nobody is living in. It goes to three people: one is technical, two are not. \
They want to know whether the house is all right and whether anybody needs to \
drive out there.

The house is monitored by a weather station. The checks below have already run \
and already reached their verdicts -- your job is to say what they mean in \
plain English, not to re-decide them. Do not contradict a verdict, do not \
invent a cause the data does not support, and do not add numbers that are not \
given to you.

Reply with ONLY a JSON object, no prose and no code fence, with exactly these \
keys:

  "what_happened": 1-2 sentences. What is actually wrong, in words a \
non-technical reader can act on. Name the house, not the metric: "the house \
has been over 85F since Thursday", not "indoor.temperature exceeded the \
threshold".
  "impact":       1-2 sentences. What this means for the house if nobody acts, \
and what is still fine. Be concrete and be calm. Say plainly when the answer \
is "nothing is damaged yet" -- that is usually the most useful sentence here.

DO NOT tell the reader what to do or who to call. The email already carries an \
instruction written for it, further down, and a second one in your words would \
compete with it. Describe the situation and stop there.

Be direct. Do not hedge, do not restate the measurements, and do not pad. If \
the input is too thin to say anything useful, say so in what_happened."""


def _redact(text: str) -> str:
    """Strip any environment secret that has leaked into a message.

    Matched by value rather than by pattern: a password is unrecognisable out
    of context, but this process knows exactly what its own are. Short values
    are skipped -- a two-character secret would match half the text.
    """
    for name in (
        "ECOWITT_REPORT_DSN",
        "ECOWITT_EMAIL_LOG_DSN",
        "LAKEHOUSE_SMTP_PASSWORD",
        "ECOWITT_RO_PASSWORD",
        "ANTHROPIC_API_KEY",
    ):
        value = os.environ.get(name)
        if value and len(value) >= 8:
            text = text.replace(value, f"<{name} redacted>")
    return text


def _facts(report) -> str:
    """The report as input: verdicts, measurements, and the house. Nothing else."""
    items = [
        {
            "check": item["check"],
            "verdict": item.get("verdict"),
            "measured": item.get("measured"),
            "why_this_check_exists": item.get("note"),
            "consecutive_days": item.get("days"),
        }
        for item in report.attention.get("items", [])
    ]
    house = {k: v for k, v in report.house.items() if v is not None}
    if since := house.get("breach_since"):
        house["breach_since"] = str(since)

    payload = {
        "date_reported": report.for_date.isoformat(),
        "timezone": report.zone,
        "failing_and_warning_checks": items,
        "indoor": house,
        "checks_that_passed": (
            [row.check for row in report.checks.itertuples() if row.verdict == "PASS"]
            if report.checks is not None and not report.checks.empty
            else []
        ),
        "contact_configured": bool(
            [line for line in report.actions if "No contact is configured" not in line]
        ),
    }
    return _redact(json.dumps(payload, indent=2, default=str))


def triage(report) -> dict | None:
    """Two plain-English paragraphs, or None. Never raises.

    None is a perfectly good outcome: the email already says everything it
    needs to, in the words the checks themselves produced.
    """
    if report.severity != "alert":
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None

    try:
        # Imported here, not at module scope, so a missing or broken install
        # costs the prose rather than the email.
        import anthropic

        # An IDENTITY-LINKED key is rejected with a 400 -- on every endpoint,
        # `models.list` included -- unless the request names the workspace it
        # acts in. That is a property of how the key was issued, not of its
        # prefix: the one on this machine is an ordinary-looking
        # `sk-ant-api03-...` Console key and still requires the header. A
        # workspace-scoped key carries its own workspace and needs nothing, so
        # the header is sent only when the variable is set.
        headers = {}
        if workspace := os.environ.get("ANTHROPIC_WORKSPACE_ID"):
            headers["anthropic-workspace-id"] = workspace

        client = anthropic.Anthropic(
            timeout=TIMEOUT_S, max_retries=1, default_headers=headers or None
        )
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            # Low effort: this is a short rewrite of facts that are already
            # settled, not an analysis. It also keeps the call inside the
            # timeout above.
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": _facts(report)}],
        )
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if text.startswith("```"):
            text = text.split("```")[1].removeprefix("json").strip()
        summary = json.loads(text)
    except Exception as exc:  # never raise from the alert path
        print(f"triage did not run ({type(exc).__name__}: {exc}); sending the plain email")
        return None

    if not isinstance(summary, dict):
        return None
    wanted = ("what_happened", "impact")
    # Partial output is discarded rather than half-used: an email with an empty
    # heading reads worse than one that never had the heading.
    if not all(isinstance(summary.get(key), str) and summary[key].strip() for key in wanted):
        return None
    return {key: summary[key].strip() for key in wanted} | {"model": MODEL}


# --------------------------------------------------------------------------
# Diagnosis
# --------------------------------------------------------------------------


def describe() -> int:
    """`python -m reporting.triage --check` — is this configured, and does it work?

    The same shape as `python -m discovery check` and cfdb's `alerting --check`:
    report the configuration, attempt the real thing, and turn whatever comes
    back into the next action rather than a stack trace. Never prints a secret.
    """
    from dotenv import load_dotenv

    load_dotenv(override=False)

    print("What this is")
    print("  Optional. On an ACTION email only, Claude rewrites the opening three")
    print("  paragraphs in plain English. Everything else in the email is written")
    print("  by the checks themselves and does not involve the API at all.")
    print("  With this switched off, the email still sends. Nothing is lost but prose.")
    print()

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "")
    print("Configuration")
    print(f"  ANTHROPIC_API_KEY        {'set, ' + str(len(key)) + ' chars' if key else '(unset)'}")
    if key:
        print(f"  ...prefix                {key[:12]}…")
    print(f"  ANTHROPIC_WORKSPACE_ID   {'set' if workspace else '(unset)'}")
    print(f"  model                    {MODEL}")
    print(f"  timeout                  {TIMEOUT_S:.0f}s, then the plain email goes out")
    print()

    if not key:
        print("Not configured, and that is a valid state — ACTION emails will simply")
        print("be written in the checks' own words. Set ANTHROPIC_API_KEY in .env to")
        print("switch it on.")
        return 0

    print("Live check")
    try:
        import anthropic

        headers = {"anthropic-workspace-id": workspace} if workspace else None
        client = anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=0, default_headers=headers)
        response = client.messages.create(
            model=MODEL,
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        )
        said = "".join(b.text for b in response.content if b.type == "text").strip()
        print(f"  OK — the API answered {said!r}.")
        print(
            f"  Billed {response.usage.input_tokens} in / "
            f"{response.usage.output_tokens} out for this check."
        )
        return 0
    except Exception as exc:  # a diagnostic must never raise either
        print(f"  FAILED — {type(exc).__name__}")
        print(f"  {str(exc)[:300]}")
        print()
        print("What to do")
        for line in _diagnose(exc):
            print(f"  {line}")
        return 1


def _diagnose(exc: BaseException) -> list[str]:
    """Turn an API failure into the thing to actually go and fix."""
    text = str(exc)
    if "anthropic-workspace-id" in text:
        return [
            "This key is identity-linked, so every request must name the workspace",
            "it acts in. The key itself is fine — nothing is wrong with it.",
            "",
            "Find the id: console.anthropic.com -> Settings -> Workspaces -> open the",
            "workspace. The id is in the page and in the URL, and starts 'wrkspc_'.",
            "",
            "Then put it in .env beside the key:",
            "    ANTHROPIC_WORKSPACE_ID=wrkspc_...",
            "",
            "Or sidestep it entirely by creating a workspace-scoped API key in the",
            "Console instead, which carries its workspace and needs no header.",
        ]
    if "authentication_error" in text or "401" in text:
        return [
            "The key was rejected outright. Check it was copied whole (a Console",
            "key is ~108 characters) and has not been revoked.",
        ]
    if "credit balance" in text or "billing" in text.lower():
        return [
            "The account has no credit. Add some in the Console, or leave triage",
            "off — the email sends without it.",
        ]
    if "not_found" in text or "404" in text:
        return [
            f"The model {MODEL!r} was not found for this account. Set",
            "LAKEHOUSE_TRIAGE_MODEL to one the account can reach.",
        ]
    if "rate_limit" in text or "429" in text:
        return ["Rate limited. This runs at most once a day, so it should not recur."]
    return [
        "Unexpected. The email path is unaffected — an ACTION email will still",
        "go out, written by the checks rather than by Claude.",
    ]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m reporting.triage",
        description="Check whether the Claude rewrite of ACTION emails is set up.",
    )
    parser.add_argument(
        "--check", action="store_true", help="report the configuration and make one live call"
    )
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 0
    return describe()


if __name__ == "__main__":
    import sys

    sys.exit(main())
