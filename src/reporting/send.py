"""Deliver the email: address resolution, the multipart build, and the record.

Three things are carried over from cfdb's `src/alerting.py` intact, because they
are what make an alerting path trustworthy rather than merely present:

  1. **The local JSONL record is written BEFORE anything networked is
     attempted.** Durable evidence that the report existed survives a dead SMTP
     server, a dead database and a dead network.
  2. **Nothing here may raise.** An exception in the send path would mask the
     condition the email exists to report (§8.1).
  3. **`diagnose()`** turns an SMTP failure into the thing to actually go and
     fix, rather than a class name.

What is NOT carried over is the shape of the message. cfdb sends
`set_content(body)` -- plain text only. This needs multipart/alternative (text
plus HTML) wrapped in multipart/related (for the inline charts), so that a
client which blocks images still shows a complete email.
"""

from __future__ import annotations

import json
import os
import smtplib
import socket
from datetime import date, datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from . import config, data


class Refused(Exception):
    """A send this module declines to make. Always fatal, never a fallback."""


# --------------------------------------------------------------------------
# Who it goes to (§5.2)
# --------------------------------------------------------------------------


def resolve_recipients(mode: str) -> list[str]:
    """The address list for this mode, or a refusal.

    FAIL CLOSED IN BOTH DIRECTIONS, and never substitute one list for the other.

    A production email that silently reached one person looks exactly like a
    production email that reached three. And a test that escaped to the family
    is far more expensive than a test that did not run -- so neither list is a
    default, and an unset variable is a stop rather than a guess.
    """
    if mode == "production":
        addresses = config.recipients(config.ENV_PRODUCTION_TO)
        if not addresses:
            raise Refused(
                f"{config.ENV_PRODUCTION_TO} is not set, so there is no production "
                f"address list. Refusing to send — this will NOT fall back to "
                f"{config.ENV_TEST_TO}, because a production email that reached one "
                "person looks exactly like one that reached three."
            )
        return addresses
    if mode == "test":
        addresses = config.recipients(config.ENV_TEST_TO)
        if not addresses:
            raise Refused(
                f"{config.ENV_TEST_TO} is not set. Refusing to send — this will NOT "
                f"fall back to {config.ENV_PRODUCTION_TO}. A test escaping to the "
                "family costs far more than a test that did not run."
            )
        return addresses
    raise Refused(f"mode {mode!r} does not send")


# --------------------------------------------------------------------------
# The message
# --------------------------------------------------------------------------


def _sender_domain(sender: str) -> str:
    """'Lake House <station@example.com>' -> 'example.com'."""
    address = sender.split("<")[-1].rstrip(">").strip()
    domain = address.rpartition("@")[2]
    return domain or "localhost"


def build_message(
    rendered, *, sender: str, to: list[str], message_id: str | None = None
) -> EmailMessage:
    """multipart/related( multipart/alternative( text, html ), images ).

    The order inside the alternative part matters: clients display the LAST part
    they understand, so the plain text goes first and the HTML second. Every
    image is `inline` with a Content-ID the HTML references, which is what makes
    the charts render without a click and without a login.
    """
    message = EmailMessage()
    message["Subject"] = rendered.subject
    message["From"] = sender
    message["To"] = ", ".join(to)
    message["Date"] = formatdate(localtime=True)
    # The Message-ID's domain is taken from the sender rather than invented.
    # `lakehouse.local` does not resolve, and a receiving spam filter that
    # checks it finds nothing -- which is a needless strike against a brand-new
    # sending address that has no reputation yet.
    message["Message-ID"] = message_id or make_msgid(domain=_sender_domain(sender))

    # A reply has to reach a person. The sending account is automation-only, so
    # without this the family's replies go into a mailbox nobody opens.
    if reply_to := os.environ.get(config.ENV_REPLY_TO, "").strip():
        message["Reply-To"] = reply_to

    message.set_content(rendered.text)
    message.add_alternative(rendered.html, subtype="html")

    # add_related on the HTML part turns the alternative into a related
    # container around it -- the images belong to the HTML alternative, not to
    # the message, or a text-only client would show them as attachments.
    html_part = message.get_payload()[1]
    for name, png in rendered.images.items():
        html_part.add_related(png, "image", "png", cid=f"<{name}>", filename=f"{name}.png")
    return message


# --------------------------------------------------------------------------
# The local record -- always written
# --------------------------------------------------------------------------


def record_local(event: dict, path: Path | None = None) -> bool:
    """Append one line to the local log. Never raises.

    Resolved at call time rather than bound as a default argument, so the path
    stays redirectable in a test.
    """
    target = path or Path(config.JSONL_LOG)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, default=str) + "\n")
        return True
    except Exception as exc:  # never raise from the send path
        print(f"WARNING: could not write the local send log: {exc}")
        return False


def diagnose(exc: BaseException) -> str:
    """An SMTP failure, as the thing to go and fix."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (
            "Credentials rejected. Gmail requires an App Password (16 characters, "
            "2-Step Verification enabled) — an account password always fails here."
        )
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return f"Sender refused. {config.ENV_SMTP_FROM} usually has to match the SMTP user."
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "Recipient refused. Check the address list for a typo."
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return (
            "Server rejected STARTTLS. Port 465 expects TLS from the first byte; "
            "this client upgrades an open connection, so use 587."
        )
    if isinstance(exc, (socket.gaierror, socket.herror)):
        return f"Host did not resolve. Check {config.ENV_SMTP_HOST} (Gmail is smtp.gmail.com)."
    if isinstance(exc, (ConnectionRefusedError, socket.timeout, TimeoutError)):
        return (
            f"Nothing answered. Check {config.ENV_SMTP_PORT} (587 for STARTTLS) and any firewall."
        )
    return "Unexpected SMTP error — see the exception above."


def _transmit(message: EmailMessage) -> None:
    host = os.environ.get(config.ENV_SMTP_HOST, config.DEFAULT_SMTP_HOST)
    port = int(os.environ.get(config.ENV_SMTP_PORT, config.DEFAULT_SMTP_PORT))
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        user = os.environ.get(config.ENV_SMTP_USER) or os.environ.get(config.ENV_SMTP_FROM)
        password = os.environ.get(config.ENV_SMTP_PASSWORD)
        if user and password:
            server.login(user, password)
        server.send_message(message)


# --------------------------------------------------------------------------


def send(report, rendered, *, mode: str, log_conn=None, transmit=_transmit) -> dict:
    """Send one email and record it. Returns an outcome; never raises.

    `transmit` is injected so a test can force an SMTP failure and assert that
    the local record was still written -- the property that matters most here.

    Order is deliberate and is the same order cfdb uses: resolve, record
    locally, check for a duplicate, send, then write `email_log`. The durable
    local evidence exists before anything that can hang or fail.
    """
    outcome = {
        "mode": mode,
        "for_date": report.for_date,
        "severity": report.severity,
        "sent": False,
        "duplicate": False,
        "logged": False,
        "recorded": False,
        "recipients": [],
        "error": None,
    }

    try:
        to = resolve_recipients(mode)
    except Refused as refusal:
        outcome["error"] = str(refusal)
        raise  # a refusal is meant to be fatal

    sender = os.environ.get(config.ENV_SMTP_FROM)
    if not sender:
        raise Refused(f"{config.ENV_SMTP_FROM} is not set, so the email has no sender.")

    # A display name is fine in the From header and fatal as an SMTP username.
    # Gmail would reject `Lake House <station@example.com>` as a login, and the
    # error arrives as a bare authentication failure that names nothing useful --
    # at 07:00, unattended. Refuse here instead, where the message can explain.
    if "<" in sender and not os.environ.get(config.ENV_SMTP_USER):
        raise Refused(
            f"{config.ENV_SMTP_FROM} carries a display name ({sender!r}), so it "
            f"cannot double as the SMTP username. Set {config.ENV_SMTP_USER} to "
            "the bare address as well."
        )

    message_id = make_msgid(domain="lakehouse.local")
    outcome["recipients"] = to

    event = {
        "at": datetime.now(timezone.utc).isoformat(),
        "for_date": report.for_date.isoformat(),
        "mode": mode,
        "severity": report.severity,
        "subject": rendered.subject,
        "recipients": to,
        "message_id": message_id,
        "is_replay": report.is_replay,
        "headline": report.headline,
    }
    outcome["logged"] = record_local(event)

    # Idempotency keys on (for_date, mode), never on the date alone: a test send
    # must not consume that day's production send (§5.6).
    if data.already_sent(log_conn, report.for_date, mode):
        outcome["duplicate"] = True
        record_local({**event, "suppressed": "already sent for this (for_date, mode)"})
        print(f"already sent a {mode} email for {report.for_date} — not sending again")
        return outcome

    try:
        transmit(build_message(rendered, sender=sender, to=to, message_id=message_id))
        outcome["sent"] = True
    except Exception as exc:  # never raise from the send path
        outcome["error"] = f"{type(exc).__name__}: {exc}"
        print(f"ALERT: could not send the daily email: {exc}\n       {diagnose(exc)}")
        record_local({**event, "failed": outcome["error"]})
        return outcome

    outcome["recorded"] = data.record_sent(
        log_conn,
        for_date=report.for_date,
        mode=mode,
        severity=report.severity,
        recipients=to,
        message_id=message_id,
    )
    return outcome


# --------------------------------------------------------------------------
# Preview (§8.5 — the default, and the harmless one)
# --------------------------------------------------------------------------


def write_preview(rendered, for_date: date, directory: Path | None = None) -> Path:
    """Write the rendered email to disk and return the HTML path.

    The whole point of a pure formatter is being able to see tomorrow's email
    today, so the dry run produces the real thing -- same subject, same bodies,
    same images -- rather than a description of it.
    """
    target = Path(directory or config.PREVIEW_DIR) / for_date.isoformat()
    target.mkdir(parents=True, exist_ok=True)
    (target / "subject.txt").write_text(rendered.subject + "\n", encoding="utf-8")
    (target / "email.txt").write_text(rendered.text, encoding="utf-8")

    # The images are written beside the HTML and the cid: references rewritten
    # to point at them, so double-clicking the file shows what the email looks
    # like rather than three broken-image icons.
    html = rendered.html
    for name, png in rendered.images.items():
        (target / f"{name}.png").write_bytes(png)
        html = html.replace(f'src="cid:{name}"', f'src="{name}.png"')
    (target / "email.html").write_text(html, encoding="utf-8")
    return target / "email.html"
