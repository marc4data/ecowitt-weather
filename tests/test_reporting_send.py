"""Phase C: who it reaches, and what survives a failure.

Every test here is about a refusal or a fallback, because that is what §5 asks
for: the system must make it difficult to accidentally send three people an
alarming email about a condition that is a week old, and it must leave evidence
behind when it cannot send at all.

Nothing here opens a socket. `send.send` takes its transmitter as an argument
precisely so a test can hand it one that fails.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date, timedelta

import pytest
from conftest import build_day, day_bounds
from test_reporting_report import build

from reporting import config, daily, render, selftest, send


@pytest.fixture
def clean_env(monkeypatch):
    for name in (
        config.ENV_PRODUCTION_TO,
        config.ENV_TEST_TO,
        config.ENV_SMTP_FROM,
        config.ENV_SMTP_PASSWORD,
        config.ENV_SMTP_USER,
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# --- address resolution (§5.2) --------------------------------------------


def test_production_refuses_rather_than_falling_back_to_the_test_list(clean_env):
    clean_env.setenv(config.ENV_TEST_TO, "marc@example.com")
    with pytest.raises(send.Refused) as refusal:
        send.resolve_recipients("production")
    assert config.ENV_PRODUCTION_TO in str(refusal.value)
    # The reason, not just the fact: a production email that reached one person
    # looks exactly like one that reached three.
    assert "looks exactly like" in str(refusal.value)


def test_test_refuses_rather_than_falling_back_to_the_production_list(clean_env):
    clean_env.setenv(config.ENV_PRODUCTION_TO, "marc@x.com,stacy@x.com,tad@x.com")
    with pytest.raises(send.Refused) as refusal:
        send.resolve_recipients("test")
    assert config.ENV_TEST_TO in str(refusal.value)
    assert "family" in str(refusal.value)


def test_each_list_is_used_when_it_is_set(clean_env):
    clean_env.setenv(config.ENV_PRODUCTION_TO, "a@x.com, b@x.com ,c@x.com")
    clean_env.setenv(config.ENV_TEST_TO, "marc@x.com")
    assert send.resolve_recipients("production") == ["a@x.com", "b@x.com", "c@x.com"]
    assert send.resolve_recipients("test") == ["marc@x.com"]


# --- the CLI's own guards (§5.1, §5.3, §8.9) -------------------------------


def test_send_with_for_date_is_refused(capsys):
    args = daily.parse_args(["--send", "--for-date", "2026-08-21"])
    with pytest.raises(SystemExit) as stop:
        daily.resolve_mode(args, date(2026, 8, 21))
    message = str(stop.value)
    assert "REFUSED" in message
    # The refusal explains itself and offers the three things the user probably
    # meant instead.
    assert "--test --for-date" in message
    assert "--force-backfill-send" in message


def test_send_with_for_date_is_allowed_when_forced():
    args = daily.parse_args(["--send", "--for-date", "2026-08-21", "--force-backfill-send"])
    assert daily.resolve_mode(args, date(2026, 8, 21)) == "production"


def test_default_invocation_sends_nothing():
    """§8.5, and the whole reason the harmless mode is the default."""
    assert daily.resolve_mode(daily.parse_args([]), date(2026, 8, 21)) == "dry-run"
    assert (
        daily.resolve_mode(daily.parse_args(["--for-date", "2026-08-21"]), date(2026, 8, 21))
        == "dry-run"
    )


def test_send_and_test_together_are_refused():
    with pytest.raises(SystemExit):
        daily.resolve_mode(daily.parse_args(["--send", "--test"]), date(2026, 8, 21))


def test_future_and_prehistoric_dates_are_refused_differently():
    with pytest.raises(SystemExit) as future:
        daily.resolve_date((date.today() + timedelta(days=1)).isoformat())
    assert "today or later" in str(future.value)

    with pytest.raises(SystemExit) as ancient:
        daily.resolve_date("2026-07-15")
    assert "before the record starts" in str(ancient.value)


def test_selftest_never_reaches_the_production_list():
    with pytest.raises(SystemExit) as stop:
        daily.main(["--selftest", "--send"])
    assert "never goes to the production list" in str(stop.value)


# --- delivery and the local record ----------------------------------------


def test_a_failed_send_still_writes_the_local_record(tmp_path, clean_env, fixture_db):
    """The property this module exists for.

    The JSONL line is written BEFORE anything networked is attempted, so the
    durable evidence that a report was produced survives a dead SMTP server, a
    dead database, and a dead network.
    """
    clean_env.setenv(config.ENV_TEST_TO, "marc@example.com")
    clean_env.setenv(config.ENV_SMTP_FROM, "station@example.com")
    log = tmp_path / "sent.jsonl"
    clean_env.setattr(config, "JSONL_LOG", str(log))

    start, end = day_bounds("2026-08-16")
    report = build(fixture_db, "2026-08-16", build_day(start, end, indoor=95.0, indoor_room=93.0))
    out = render.render(report, with_charts=False)

    def explode(_message):
        raise TimeoutError("nothing answered on 587")

    outcome = send.send(report, out, mode="test", log_conn=None, transmit=explode)

    assert outcome["sent"] is False
    assert "TimeoutError" in outcome["error"]
    assert outcome["logged"] is True

    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert lines[0]["severity"] == "alert"
    assert lines[0]["recipients"] == ["marc@example.com"]
    assert any("failed" in line for line in lines)


def test_a_send_that_works_records_what_went_where(tmp_path, clean_env, fixture_db):
    clean_env.setenv(config.ENV_TEST_TO, "marc@example.com")
    clean_env.setenv(config.ENV_SMTP_FROM, "station@example.com")
    clean_env.setattr(config, "JSONL_LOG", str(tmp_path / "sent.jsonl"))

    start, end = day_bounds("2026-08-05")
    report = build(fixture_db, "2026-08-05", build_day(start, end))
    out = render.render(report, with_charts=False)

    captured = []
    outcome = send.send(report, out, mode="test", log_conn=None, transmit=captured.append)

    assert outcome["sent"] is True
    message = captured[0]
    assert message["To"] == "marc@example.com"
    assert message["Subject"] == out.subject
    assert message.is_multipart()


def test_the_message_is_text_plus_html_with_the_images_inside_the_html(clean_env):
    """multipart/related( multipart/alternative( text, html ), images ).

    The images belong to the HTML alternative, not to the message -- attached to
    the message they would show up as file attachments in a text-only client.
    """
    report = selftest.synthetic_report()
    out = render.render(report, with_charts=False)
    out = render.Rendered(out.subject, out.text, out.html, {"indoor": b"\x89PNG-fake"})

    message = send.build_message(out, sender="station@example.com", to=["marc@example.com"])
    assert message.get_content_type() == "multipart/alternative"
    text_part, html_part = message.get_payload()
    assert text_part.get_content_type() == "text/plain"
    assert html_part.get_content_type() == "multipart/related"

    inner = html_part.get_payload()
    assert inner[0].get_content_type() == "text/html"
    assert inner[1].get_content_type() == "image/png"
    assert inner[1]["Content-ID"] == "<indoor>"


def test_no_sender_is_a_refusal(tmp_path, clean_env, fixture_db):
    clean_env.setenv(config.ENV_TEST_TO, "marc@example.com")
    start, end = day_bounds("2026-08-05")
    report = build(fixture_db, "2026-08-05", build_day(start, end))
    out = render.render(report, with_charts=False)
    with pytest.raises(send.Refused):
        send.send(report, out, mode="test", log_conn=None, transmit=lambda _m: None)


def test_diagnose_names_the_fix_not_the_exception():
    import smtplib

    assert "App Password" in send.diagnose(smtplib.SMTPAuthenticationError(535, b"nope"))
    assert "587" in send.diagnose(TimeoutError())


def test_a_data_failure_does_not_summon_the_neighbours(monkeypatch, fixture_db):
    """A missed ingestion run must not print three phone numbers.

    Found by replaying 1 August 2026, whose only failure is "no ingestion run
    covered this window" -- the pipeline did not exist yet. The email told three
    people to call an HVAC company about a cron job.
    """
    monkeypatch.setenv(
        config.ENV_CONTACTS,
        '[{"who": "Some HVAC Co", "reach": "(555) 555-0100", "what": "services the A/C"}]',
    )
    # A clean house, but no ingestion run recorded for the window.
    start, end = day_bounds("2026-08-05")
    report = build(fixture_db, "2026-08-05", build_day(start, end), runs=0)

    assert report.severity == "alert"
    assert "runs covering the day" in [i["check"] for i in report.attention["items"]]
    joined = " ".join(report.actions)
    assert "555-0100" not in joined, "a data failure must not print the contact list"
    assert "not house problems" in joined
    assert "Check the timers" in joined


def test_a_house_failure_does_summon_them(monkeypatch, fixture_db):
    monkeypatch.setenv(
        config.ENV_CONTACTS,
        '[{"who": "Some HVAC Co", "reach": "(555) 555-0100", "what": "services the A/C"}]',
    )
    start, end = day_bounds("2026-08-16")
    report = build(fixture_db, "2026-08-16", build_day(start, end, indoor=95.0, indoor_room=93.0))
    joined = " ".join(report.actions)
    assert "555-0100" in joined
    assert "check whether the A/C is running" in joined


def test_an_incident_cannot_be_older_than_the_record(fixture_db):
    """§4's commissioning-versus-failure distinction, applied to the run length."""
    start, end = day_bounds("2026-08-01")
    report = build(fixture_db, "2026-08-01", build_day(start, end, indoor=95.0, indoor_room=93.0))
    for item in report.attention["items"]:
        assert item["days"] == 1, f"{item['check']} claims {item['days']} days on day one"


def test_triage_is_skipped_without_a_key(monkeypatch, fixture_db):
    """No key is a valid state, not an error: the email sends without the prose."""
    from reporting import triage

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    start, end = day_bounds("2026-08-16")
    report = build(fixture_db, "2026-08-16", build_day(start, end, indoor=95.0, indoor_room=93.0))
    assert triage.triage(report) is None


def test_triage_never_raises_even_when_the_api_does(monkeypatch, fixture_db):
    """The property the whole module exists for."""
    from reporting import triage

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    monkeypatch.setattr(triage, "TIMEOUT_S", 0.001)  # fail fast, hit no network
    start, end = day_bounds("2026-08-16")
    report = build(fixture_db, "2026-08-16", build_day(start, end, indoor=95.0, indoor_room=93.0))
    assert triage.triage(report) is None  # degraded, not crashed


def test_the_workspace_error_explains_itself():
    """A 400 asking for a workspace id must name the fix, not the exception."""
    from reporting import triage

    advice = " ".join(
        triage._diagnose(RuntimeError("anthropic-workspace-id is required when authenticating"))
    )
    assert "ANTHROPIC_WORKSPACE_ID" in advice
    assert "wrkspc_" in advice
    assert "nothing is wrong with it" in advice


def test_triage_output_carries_no_instruction(monkeypatch, fixture_db):
    """The email must not say "what to do" twice, the second time less precisely.

    The check-derived section below carries the real contacts and advice that was
    written once and reviewed; a model paraphrase above it competes with the
    thing that is actually correct.
    """
    from reporting import render, triage

    assert "what_to_do" not in triage.SYSTEM_PROMPT
    assert "DO NOT tell the reader what to do" in triage.SYSTEM_PROMPT

    start, end = day_bounds("2026-08-16")
    report = build(fixture_db, "2026-08-16", build_day(start, end, indoor=95.0, indoor_room=93.0))
    report = dataclasses.replace(
        report,
        summary={
            "what_happened": "The house has been over 85F since Thursday.",
            "impact": "Nothing is damaged yet.",
            "model": "claude-opus-5",
        },
    )
    out = render.render(report, with_charts=False)

    # Exactly one instruction section, and it is the one built from the checks.
    assert out.text.count("WHAT TO DO") == 1
    assert "check whether the A/C is running" in out.text
    assert out.html.count("What to do") == 1


def test_a_reply_reaches_a_person_not_the_robot(monkeypatch, fixture_db):
    """Sending from a dedicated account must not make replies vanish.

    The footer tells three people to "tell Marc". If the sender is an unattended
    mailbox and there is no Reply-To, hitting reply is the same as doing nothing.
    """
    monkeypatch.setenv(config.ENV_SMTP_FROM, "m4d.systems@example.com")
    monkeypatch.setenv(config.ENV_REPLY_TO, "marc@example.com")

    out = render.render(selftest.synthetic_report(), with_charts=False)
    message = send.build_message(out, sender="m4d.systems@example.com", to=["marc@example.com"])
    assert message["Reply-To"] == "marc@example.com"
    # And the Message-ID is anchored to a domain that actually exists.
    assert message["Message-ID"].endswith("@example.com>")


def test_no_reply_to_header_when_none_is_configured(monkeypatch):
    monkeypatch.delenv(config.ENV_REPLY_TO, raising=False)
    out = render.render(selftest.synthetic_report(), with_charts=False)
    message = send.build_message(out, sender="a@b.com", to=["c@d.com"])
    assert message["Reply-To"] is None


def test_a_display_name_sender_demands_an_explicit_smtp_user(monkeypatch, fixture_db):
    """`Lake House <x@y>` is a valid From and an invalid Gmail login."""
    monkeypatch.setenv(config.ENV_TEST_TO, "marc@example.com")
    monkeypatch.setenv(config.ENV_SMTP_FROM, "Lake House <m4d.systems@example.com>")
    monkeypatch.delenv(config.ENV_SMTP_USER, raising=False)

    start, end = day_bounds("2026-08-05")
    report = build(fixture_db, "2026-08-05", build_day(start, end))
    out = render.render(report, with_charts=False)
    with pytest.raises(send.Refused) as refusal:
        send.send(report, out, mode="test", log_conn=None, transmit=lambda _m: None)
    assert config.ENV_SMTP_USER in str(refusal.value)

    # With the username given explicitly, it proceeds.
    monkeypatch.setenv(config.ENV_SMTP_USER, "m4d.systems@example.com")
    sent = []
    outcome = send.send(report, out, mode="test", log_conn=None, transmit=sent.append)
    assert outcome["sent"] is True
    assert sent[0]["From"] == "Lake House <m4d.systems@example.com>"
