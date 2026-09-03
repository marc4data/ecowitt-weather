"""Settings for the daily lakehouse email.

Two kinds of thing live here and they are deliberately separated:

  * **Facts about the house and the send path** -- addresses, contacts, room
    names, SMTP. These are configuration in the ordinary sense.
  * **Nothing about detection.** Every threshold is in
    `notebooks/ecowitt_daily.py` next to the check that uses it, so the notebook
    and this email cannot disagree about what "too hot" means. Two copies of a
    threshold is exactly the failure this project keeps designing against.

No address list has a default. An unset variable is a stop, not a guess (§5.2).
"""

from __future__ import annotations

import json
import os
from datetime import date

# --- identity ---------------------------------------------------------------

SUBJECT_PREFIX = "[lakehouse]"
# Deliberately imprecise. This repository is public and the house stands empty;
# a region is a region; a lake plus a name is close to a doorstep.
HOUSE = "the lakehouse in rural Oklahoma"

# The station's own zone. Every time in the email is a clock time at the house,
# and the zone is no longer printed: three readers who all know where the house
# is do not need "America/Chicago" on a line that says 6:40 AM. It stays here
# because every timestamp is still converted through it.
DISPLAY_ZONE = "America/Chicago"

# How often the station reports. Stated in the email because it is the answer to
# "why does the chart's peak differ from the table's" -- and because a reader
# should know whether a number is one reading or an average of twelve.
SAMPLE_INTERVAL_MIN = 5

# The station's own page on ecowitt.net, linked from the email for anyone who
# wants to poke at the live readings.
#
# ⚠️ NOT hard-coded here on purpose. The URL carries the station id, and this
# repository is public -- the id leads to a page identifying a house that stands
# empty, which is the thing the coordinates were removed from the docs to avoid.
# Set it in `.env` locally and in the unit file on the VM, the same way the
# email addresses are handled.
ENV_STATION_URL = "LAKEHOUSE_STATION_URL"


def station_url() -> str:
    return os.environ.get(ENV_STATION_URL, "").strip()


# First stored observation. `--for-date` before this is refused (§8.9) -- an
# empty report for a day that predates the station is a bug report, not a day
# with no data.
HISTORY_START = date(2026, 8, 1)

# --- recipients (§5.2) ------------------------------------------------------
# Two lists, no fallback between them, in either direction.
#
#   production  a real email about the house, to all three people
#   test        Marc only, always, under every circumstance
#
# The asymmetry is the point: the cost of a test escaping to the family is much
# higher than the cost of a test not running. So neither list may substitute for
# the other, and a missing one refuses rather than degrading.
ENV_PRODUCTION_TO = "LAKEHOUSE_EMAIL_TO"
ENV_TEST_TO = "LAKEHOUSE_EMAIL_TEST_TO"

# --- SMTP -------------------------------------------------------------------
# Gmail with an app password, per the cfdb `src/alerting.py` pattern. Gmail app
# passwords are 16 characters; an account password will always be rejected.
ENV_SMTP_HOST = "LAKEHOUSE_SMTP_HOST"
ENV_SMTP_PORT = "LAKEHOUSE_SMTP_PORT"
ENV_SMTP_USER = "LAKEHOUSE_SMTP_USER"
ENV_SMTP_PASSWORD = "LAKEHOUSE_SMTP_PASSWORD"
ENV_SMTP_FROM = "LAKEHOUSE_EMAIL_FROM"

# Where a reply should go, when the sender is a mailbox nobody reads.
#
# Sending from a dedicated account keeps the personal Sent folder clean, but it
# also means "hit reply" now lands somewhere unattended -- while the footer of
# every email tells three people to "tell Marc". Reply-To puts that right, and
# is the one header that makes an automated sender still answerable.
ENV_REPLY_TO = "LAKEHOUSE_REPLY_TO"

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587  # STARTTLS. 465 expects TLS from the first byte.

# --- database ---------------------------------------------------------------
# Read-only for the data, a separate narrowly-granted role for `email_log`
# (§8.4). Widening `ecowitt_ro` to write one table would give an exploratory
# session write access to `observation`, which §8 exists to prevent.
#
# Unset on a workstation, both fall back to the notebooks' tunnel + Secret
# Manager path. On the VM they are set by `infra/run_report.sh`, which fetches
# the passwords from Secret Manager into the environment and never writes them
# to disk.
ENV_READ_DSN = "ECOWITT_REPORT_DSN"
ENV_EMAIL_LOG_DSN = "ECOWITT_EMAIL_LOG_DSN"

# --- the local record -------------------------------------------------------
# Written BEFORE anything networked is attempted, so the durable evidence that a
# report was produced exists even when the database and SMTP are both gone. The
# cfdb alerting log is append-only for the same reason.
JSONL_LOG = os.environ.get("LAKEHOUSE_EMAIL_LOG", "data/reports/sent.jsonl")

# Where `--dry-run` (the default) writes the rendered email (§8.5).
PREVIEW_DIR = os.environ.get("LAKEHOUSE_PREVIEW_DIR", "data/reports/preview")

# --- when it goes out (§11.2 — proposed, NOT confirmed) ---------------------
# ⚠️ This string is what the footer promises three people, so it must match
# `infra/ecowitt-report.timer` exactly. Change both or neither.
#
# 07:00 Central is after the 10:00 UTC reconcile pass, so the email reports
# reconciled data rather than racing it. Whether it is a sensible hour for
# Stacy and Tad is unresolved — they may not be in Central time.
SEND_TIME_HUMAN = "07:00 Central"

# --- which failure leads ----------------------------------------------------
# When several checks fail on the same day, this decides which one becomes the
# subject line and heads the "what is wrong" list. Without it the order is
# whatever order the checks happen to run in, and 21 August 2026 -- a day the
# house sat at 93 ºF -- leads with an irregular rain accumulator.
#
# The order is: is the house all right, then can we still see the house, then is
# the data fit to answer either question. Anything unlisted sorts last, so a new
# check is merely unranked rather than accidentally promoted above the house.
CHECK_PRIORITY = [
    "indoor within protection band",  # the house itself
    "indoor climate holding",  # the house, earlier
    "indoor humidity in band",
    "sensors reporting recently",  # can we see it at all
    "no sensor dropped out",
    "battery levels",  # will we still see it next week
    "grid coverage",  # is the day fit to report on
    "day fully landed",
    "longest single gap",
    "runs covering the day",
    "values physically possible",
    "rows quarantined",
    "values corrected after the fact",
    "rain accumulators only reset to zero",
]


def priority(check: str) -> int:
    """Sort key. Unlisted checks sort after every listed one, keeping their order."""
    return CHECK_PRIORITY.index(check) if check in CHECK_PRIORITY else len(CHECK_PRIORITY)


# --- what the rooms are called (§11.3 — resolved 2026-08-28) ----------------
# ch1 = Basement, ch2 = Living Room, ch3 = Office/Bedroom.
#
# Defined ONCE, in `notebooks/ecowitt_nb.ROOM_NAMES`, and applied there to
# `meta[metric]['location']` -- the field every consumer already reads. So the
# checks, the chart legends, the notebook's detail table and this email all name
# the same room without any of them mapping it themselves. Nothing to add here;
# this note exists so the next person looks in the right place.


# --- what to do about it (§6.3 step 3) --------------------------------------
# ⚠️ THE CONTACT LIST NEVER LIVES IN THIS FILE. It is other people's names and
# phone numbers, plus who knows where the key is hidden -- which is physical
# security information about a house that stands empty. This repository is
# intended to be public, and §10's rule ("secrets never enter the repo") applies
# at least as strongly to a neighbour's phone number as to a database password.
#
# So it arrives the same way every other private value does: from the
# environment, put there by Secret Manager on the VM and by the gitignored
# `.env` locally. See .env.example for the format.
#
#   LAKEHOUSE_CONTACTS='[
#     {"who": "Some HVAC Co", "what": "services the A/C"},
#     {"who": "A neighbour",  "what": "nearest to the house; knows where the key is"}
#   ]'
#
# `reach` is an optional third field and is deliberately unused: this system
# stores nothing it does not need, and a phone number in a secret store, an
# email body and a rendered screenshot is three copies of somebody else's
# contact details. The people who receive these emails already know how to
# reach a neighbour; naming WHO is the part they cannot infer.
#
# When it is unset the ACTION email prints an explicit "no contact is
# configured" line rather than quietly omitting the section: a missing
# instruction should look missing.
ENV_CONTACTS = "LAKEHOUSE_CONTACTS"


def contacts() -> list[tuple[str, str, str]]:
    """(who, how to reach them, what they can do), from the environment.

    `reach` is optional and normally empty -- see the note above. It stays in
    the shape so an entry that genuinely needs it (an after-hours line nobody
    memorises) can carry one without a code change.

    Never raises. A malformed list costs the email its contact block, which is
    a degraded ACTION email; letting it raise would cost the email entirely,
    which is the failure this whole project is built against.
    """
    raw = os.environ.get(ENV_CONTACTS, "").strip()
    if not raw:
        return []
    try:
        return [
            (entry["who"], entry.get("reach", ""), entry.get("what", ""))
            for entry in json.loads(raw)
        ]
    except Exception as exc:  # never raise from the report path
        print(
            f"WARNING: {ENV_CONTACTS} is set but could not be read "
            f"({type(exc).__name__}: {exc}); sending without the contact block"
        )
        return []


# Which failures mean somebody has to physically go to the house.
#
# ⚠️ THIS IS WHAT GATES THE CONTACT LIST, and it matters. Every other check in
# this system is about the DATA -- a missed ingestion run, a gap in the grid, a
# quarantined row. Printing "call the HVAC company" under a failure that means
# "the pipeline did not run last night" is worse than printing nothing: it sends
# a neighbour to an empty house because a cron job missed, and after that
# happens once nobody believes the next one.
#
# Caught by replaying 1 August 2026, whose only failure is `runs covering the
# day` (the pipeline did not exist yet) and whose action list read as three
# phone numbers.
HOUSE_CHECKS = frozenset(
    {
        "indoor within protection band",
        "indoor climate holding",
        "indoor humidity in band",
    }
)


def needs_a_person(failing_checks) -> bool:
    """True when a failure is about the house rather than about the data."""
    return any(check in HOUSE_CHECKS for check in failing_checks)


# Advice that does not depend on knowing anyone -- safe to state because it is
# about this system rather than about the house. Every check that can FAIL
# should have an entry, or its ACTION email arrives with an empty "what to do".
GENERIC_ACTIONS = {
    "indoor within protection band": (
        "Someone needs to get to the house and check whether the A/C is running "
        "— start with the breaker, then the thermostat."
    ),
    "indoor climate holding": (
        "The thermostat area is climbing and the rooms agree. Cooling may be "
        "failing; worth someone looking before it is properly hot."
    ),
    "sensors reporting recently": (
        "The station or its WiFi is down. Power-cycling the console usually "
        "brings it back; the data it did not report is gone once the cloud "
        "ages it out."
    ),
    "grid coverage": (
        "The pipeline missed part of the day. It usually recovers on the next "
        "run; if it does not, the weekly gap sweep will try again while the "
        "cloud still holds 5-minute data."
    ),
    "longest single gap": (
        "A single long hole rather than scattered misses — usually the station "
        "losing WiFi for a while. Nothing to do unless it repeats."
    ),
    "runs covering the day": (
        "This is the pipeline, not the house: no ingestion run covered that "
        "window. Check the timers on ecowitt-db. Nobody needs to drive out."
    ),
    "day fully landed": (
        "The day was reported on before it finished landing. The numbers above "
        "may still move; the next reconcile pass will settle them."
    ),
    "rows quarantined": (
        "Rows were rejected and kept rather than dropped. They need a look in "
        "the quarantine table — this is a data question, not a house one."
    ),
    "values physically possible": (
        "A reading was outside what its sensor can physically report, which "
        "usually means a failing sensor or a changed unit rather than weather."
    ),
    "rain accumulators only reset to zero": (
        "A rain total went backwards without resetting to zero. A known quirk "
        "of the piezo gauge; it affects rainfall figures only."
    ),
    "battery levels": (
        "A cell is near its floor. Replacing it is not urgent, but the sensor "
        "goes quiet when it runs out — alkaline AAs, no lithium."
    ),
}


def recipients(env_var: str) -> list[str]:
    """Split a comma-separated address list. Empty when unset -- never a default.

    The caller decides what an empty list means, and in every case it means
    refuse (§5.2). This function does not get to make that call, because the
    single most dangerous behaviour available here would be a helpful fallback.
    """
    raw = os.environ.get(env_var, "")
    return [address.strip() for address in raw.split(",") if address.strip()]


def smtp_configured() -> bool:
    """Enough settings to attempt a send."""
    return bool(os.environ.get(ENV_SMTP_FROM) and os.environ.get(ENV_SMTP_PASSWORD))
