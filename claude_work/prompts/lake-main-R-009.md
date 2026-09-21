# lake-main-R-009 — round 4: read SMTP_USER back too, then prove and push

**Session:** `main` · **Register:** R-009, R-012

## 🚨 Read this first — how your reply ends, whatever happens

End your reply with these three things, in this order (CLAUDE.md §14, R-012):

1. `Report written: [lake-main-R-009-report.md](claude_work/reports/lake-main-R-009-report.md)`
2. The return cell, **exactly this, no slash, no prefix** — Marc pastes it into Cowork:
   ```
   project-round-close lake-main-R-009
   ```
3. `**Start YYYY-MM-DD H:MM AM/PM / End H:MM AM/PM : MM:SS**` — `TZ=America/Los_Angeles`

## Step 0

Commit Cowork's edits (register, this prompt).

## What happened

Marc's first `--from-unit` deploy installed `9833547-dirty` and the test send
refused: `LAKEHOUSE_EMAIL_FROM carries a display name … Set LAKEHOUSE_SMTP_USER`.
`--from-unit` reads five keys (deploy_report.sh:92-93) but not
`LAKEHOUSE_SMTP_USER`, so line 129 defaulted it to the display-name From and
line 277 wrote that into the installed unit. Marc re-ran with `LAKEHOUSE_SMTP_USER` set: same refusal, because of the
`run_on_vm` bug below. He then sent a test with `infra/run_as_unit.sh --test`
and enabled the timer by hand — step 2 checks both.

## Step 1 — fix the script

🚨 **The real bug, found after Marc's second run:** `run_on_vm()`
(deploy_report.sh:292-300) passes a hand-picked list of four variables for the
test send and never passes `LAKEHOUSE_SMTP_USER` or `LAKEHOUSE_REPLY_TO`. With a
display-name From, the verify can't pass whatever is set. **Make `run_on_vm` send
with the installed unit's own environment**, the way `run_as_unit.sh` does, so
the verify tests exactly what 07:00 will run. A hand-picked list that drifts from
the unit is the defect, not the missing name.

Then also:

- Add `LAKEHOUSE_SMTP_USER` to what `--from-unit` reads back, as **optional**,
  with the same env-disagreement refusal as the others.
- 🚨 **Refuse, before installing, when the From carries a display name and no
  bare SMTP user is available** from the env or the unit. The send would fail
  anyway; failing after the install leaves a broken unit on a live box, which
  is what just happened. Staged break: run `--print-plan` with the SMTP user
  withheld; quote the refusal.
- **Fix the closing message.** "Everything is installed and the timer is OFF"
  is only true on a first install. The script never disables a timer. State the
  timer's real state, read from the VM with `systemctl is-enabled`.
- Audit the unit template for any other `CHANGEME-*` line whose value
  `--from-unit` doesn't read back, and list them. Missing one is how this broke.

## Step 2 — prove it on the VM (read-only)

- VERSION contents; `ROLLING_NOT_ACCUMULATING` in the installed file;
  `systemctl is-enabled ecowitt-report.timer` and `list-timers`.
- The installed unit's `LAKEHOUSE_SMTP_USER` is a bare address, not a display
  name. State only "bare address" or "display name" — not the value.
- The test email from Marc's second run: send time from `email_log` (mode
  `test`) or the journal.
- Dry replay of 12 Sep through `infra/run_as_unit.sh --for-date 2026-09-12`:
  subject, rain check line, rain title.

**If the timer is not enabled or the unit is still broken, say so in the first
line of your reply** — tomorrow's 07:00 email depends on it. Don't deploy; give
Marc the command to run.

## Step 3 — push

Only if step 2 passes: push `daily-email` to origin. Don't merge to `master`.

## Report

Round 4 section in `claude_work/reports/lake-main-R-009-report.md`.

## Then end your reply exactly as the top of this prompt says.
