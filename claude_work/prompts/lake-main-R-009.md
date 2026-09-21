# lake-main-R-009 — ship R-001 and R-002 to the VM

**Session:** `main` · **Register:** `claude_work/lake_request_register.md` (R-009)

**First, commit Cowork's edits sitting in the tree** — this prompt and the
register (CLAUDE.md §14).

**Marc's go is the handoff cell itself.** He only pastes it after approving
R-002's new household text in the Cowork close. That approval is why this round
exists; the prompt doesn't ask for it again.

## R-010 is closed

Cowork reviewed `caf487d` on 2026-09-21. Marc approved both household texts in that close.

## What's shipping

| request | commit | what the household will see |
|---|---|---|
| R-001 | `05d95dd` | rain chart as a trailing 24-hour total, titled `Rain in any 24 hours` |
| R-002 | `38334f1` | no more "rain totals went backwards" on days it only rained |
| R-010, R-011 + R-002 text | `caf487d` | three subject forms; rain headline = largest 24 h in the last day; gauge-state wording |

Both are reviewed by Cowork (register rows R-001, R-002). Nothing else ships —
if `git log origin/daily-email..daily-email` shows commits other than the round
work and Cowork's register/prompt edits, **stop and list them**.

## The deploy

`infra/deploy_report.sh` installs with the timer off, sends one `--test` email
from the VM to the test address, and enables the timer only if that email went
out. Use it as designed (`VERIFY=send`, the default). **Don't use
`--skip-verify`.**

🚨 **Don't retype the four environment values.** `LAKEHOUSE_EMAIL_TO`,
`LAKEHOUSE_EMAIL_TEST_TO`, `LAKEHOUSE_EMAIL_FROM` and `LAKEHOUSE_STATION_URL`
(plus `LAKEHOUSE_REPLY_TO` if set) are already in the installed unit on
`ecowitt-db`. Read them back over IAP from `ecowitt-report.service` and pass
those values in. Retyping them is how an address with a comment glued to it got
into a unit file once (02_DAILY_EMAIL_AS_BUILT §5.3); `infra/run_as_unit.sh`
exists for the same reason and shows how to read them.

⚠️ **The repo is public. The addresses and the station URL must not land in any
file, the report, or a commit.** In the report, write them as
`<3 addresses, unchanged>`. Say whether they were unchanged — don't say what
they are.

## Prove it on the VM, not on the laptop

A green deploy proves the email went out. It doesn't prove the email is the new
one. After the deploy, and still on the VM:

1. **The exemption is there.** Grep the installed
   `/opt/ecowitt/app/notebooks/ecowitt_daily.py` for `ROLLING_NOT_ACCUMULATING`.
   The deploy tarball includes that file (deploy_report.sh:135), but check it
   landed.
2. **Replay 12 Sep, dry, with the unit's own environment.** Use
   `infra/run_as_unit.sh`, no `--test` and no `--send`, for
   `--for-date 2026-09-12`. If it won't pass a date through, say so and render
   yesterday instead. State:
   - the subject line (expected: led by indoor humidity, not rain);
   - the rain check's line (expected: `[ok  ] … none`);
   - the rain chart title (expected: the R-011 headline);
   - the subject's opening words match the R-010 form for that day's severity.
3. **The timer is back on.** `systemctl list-timers 'ecowitt-*'` shows
   `ecowitt-report.timer` with its next run at 07:00 Central.

**If any of these fails, say which one and stop — don't try to fix it on
the box.** Marc gets tomorrow's 07:00 email from whatever is running either
way, so an honest "not shipped" beats a half-shipped fix.

## Then

- **Push `daily-email` to origin.** The work has been reviewed now, so
  CLAUDE.md §14 allows it. **Don't merge to `master`** — that's a separate
  decision.
- **Out of scope:** R-008 (password rotation — Marc hasn't decided), R-010 (how
  the subject reads on WARN-only days), all of which R-010 already handled.

## Definition of done

- The `--test` email from the VM went out, with its Message-ID or send time in
  the report. **That email is how Marc sees R-001 working.**
- The three proofs above, stated one by one.
- The pushed commit hash, and the commit the VM is running if the install
  records one.
- Report to `claude_work/reports/lake-main-R-009-report.md`.
- The **staged break** for this round is the deploy script's own guard, and it
  doesn't need re-running on production. Instead, name the line in
  `deploy_report.sh` that keeps the timer off when the test send fails, and
  quote it. If there's no such line, that's the finding.

## Traps

- The IAP tunnel and `gcloud compute ssh` both run from the laptop. Docker still
  holds local port 5433 (R-006), so don't use `nb.ensure_db()` here.
- The e2-micro takes 5–10 minutes to build pandas and matplotlib. Name that job
  if you're asked for a close while it's still running.
- Clock in **America/Los_Angeles**, explicitly.

## How the reply ends

```
/anthropic-skills:project-round-close lake-main-R-009
```

    **Start YYYY-MM-DD H:MM AM/PM / End H:MM AM/PM : MM:SS**

`TZ=America/Los_Angeles date +"%Y-%m-%d %-I:%M:%S %p"`
