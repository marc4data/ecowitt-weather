# lake-main-R-009 — round 2: WARNING in capitals, then ship

**Session:** `main` · **Register:** R-009, R-010, R-012

## 🚨 Read this first — how your reply ends, even if you stop

End your reply with these three things, in this order, whatever happens: shipped,
stopped, refused or failed (CLAUDE.md §14, R-012). Round 1 skipped them.

1. `Report written: [lake-main-R-009-report.md](claude_work/reports/lake-main-R-009-report.md)`
2. ```
   /anthropic-skills:project-round-close lake-main-R-009
   ```
3. `**Start YYYY-MM-DD H:MM AM/PM / End H:MM AM/PM : MM:SS**` — `TZ=America/Los_Angeles`

## Step 0 — commit Cowork's edits, then one word

Commit the register, CLAUDE.md and this prompt (CLAUDE.md §14).

Marc approved both household texts, with one change: *"WARN should be in
CAPS."* The warning subject becomes:

`Lake house Ecowitt System checks are good with a WARNING for Sat, Sep 12th - indoor humidity 49–69 %`

Change `render.py:97` and the docstring at `:62`/`:71`, and update
`test_reporting_render.py:73`. Stage the break (lower-case it again), name the
red test, restore. `pytest` green. Commit locally.

## Step 1 — the deploy, which needs Marc's permission

Round 1 was refused by Claude Code's auto-mode classifier (`[Production
Deploy]`). That's correct behaviour: the gate belongs to Marc. **Don't route
around it.** When you reach `./infra/deploy_report.sh`, let the permission
prompt reach Marc; he approves it in this window. If it's refused again without
a prompt reaching him, stop and end your reply as above.

Use round 1's verified approach unchanged:

- Read the five env values back from `ecowitt-report.service` with `shlex.split`
  — not a split on spaces, which round 1 caught shredding the display name.
  Values never appear in any file, report or commit.
- `VERIFY=send`, never `--skip-verify`. One `--test` email goes to Marc only.
- The timer is **already on**. If the test send fails, the new code is installed
  but the old timer still runs — say so plainly and stop; don't try to roll back.

## Step 2 — prove it on the VM

1. `ROLLING_NOT_ACCUMULATING` is in the installed `ecowitt_daily.py`.
2. Dry replay of 12 Sep through `infra/run_as_unit.sh --for-date 2026-09-12`
   (no `--test`, no `--send`). State the subject (expected: `are good with a
   WARNING … indoor humidity`), the rain check line (expected `[ok  ] … none`),
   and the rain title (expected `… most in the last day: 0.09 in`).
3. `systemctl list-timers 'ecowitt-*'` — the report timer still has its next run
   at 07:0x Central.
4. **Write the deployed commit hash to `/opt/ecowitt/app/VERSION`** during the
   install, so the next round can tell what's running without guessing. Round 1
   found no record. If that means changing `deploy_report.sh`, make the change,
   commit it, and note that the change itself shipped in this deploy.

## Step 3 — push

Only after steps 1–2 pass: push `daily-email` to origin. Don't merge to `master`.

## Report

Add a **Round 2** section to `claude_work/reports/lake-main-R-009-report.md`.
Keep round 1 as it is. Include the test email's send time or Message-ID — that
email is how Marc first sees all of this.

## Then end your reply exactly as the top of this prompt says.
