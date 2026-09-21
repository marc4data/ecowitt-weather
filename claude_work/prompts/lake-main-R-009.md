# lake-main-R-009 — round 3: let Marc deploy with one command

**Session:** `main` · **Register:** R-009

## 🚨 Read this first — how your reply ends, whatever happens

End your reply with these three things, in this order (CLAUDE.md §14, R-012):

1. `Report written: [lake-main-R-009-report.md](claude_work/reports/lake-main-R-009-report.md)`
2. ```
   project-round-close lake-main-R-009
   ```
3. `**Start YYYY-MM-DD H:MM AM/PM / End H:MM AM/PM : MM:SS**` — `TZ=America/Los_Angeles`

## Step 0

Commit Cowork's edits: the register and this prompt.

## Why this round exists

The classifier refused the deploy twice without asking Marc. Cowork's call:
**Marc runs the deploy himself** in his own terminal — his server, his gate.
No settings rule granting Code standing deploy rights.

He shouldn't have to type five values to do it, since retyping is how a bad
address reached the unit once (02_DAILY_EMAIL_AS_BUILT §5.3). So:

## The change — `deploy_report.sh --from-unit`

- New flag. When given, read `LAKEHOUSE_EMAIL_TO`, `LAKEHOUSE_EMAIL_TEST_TO`,
  `LAKEHOUSE_EMAIL_FROM`, `LAKEHOUSE_STATION_URL` and `LAKEHOUSE_REPLY_TO` back
  from the installed `ecowitt-report.service` over IAP. Use the same
  `systemctl show … -p Environment --value` plus `shlex.split` pattern that
  `infra/run_as_unit.sh:29-39` already uses — reuse it, don't reinvent it.
- **Refuse** if the unit isn't installed or any of the three required values is
  missing, naming which one. `--from-unit` is for redeploys; a first install
  still takes them from the environment.
- If a value is **also** set in the environment and differs from the unit,
  refuse and say which one differs. Don't pick one silently.
- The values never appear in output, logs, the report or a commit. Print
  `<3 addresses, from the unit>` style summaries only.
- Everything after that is unchanged: `VERIFY=send`, timer guard, the VERSION
  file.
- Update the usage comment at the top and `infra/README.md` with the redeploy
  command.

## Prove it without deploying

**Don't run the deploy.** Prove the new flag up to the point of installing:

- Add a `--from-unit --print-plan` path (or equivalent) that reads the unit,
  runs every refusal check, prints what it *would* do with the values redacted,
  and exits 0 without installing. Run it against the real VM (a read over IAP
  worked in round 1).
- 🚨 **Staged break:** point it at a unit name that doesn't exist and show it
  refuses with a clear message. Name what went red — a shell script may not
  have a pytest; if so, the staged break is the refusal output itself, quoted.
- `bash -n` is not evidence — round 2 found it passing on a broken quote.
  Render the IAP command with a dummy value and read it.

## Report

Round 3 section in `claude_work/reports/lake-main-R-009-report.md`. Give the
**exact command Marc will run**, in a fenced block, runnable from the repo root.

**Commit locally. Don't push.** Pushing waits for the deploy's proofs (round 4).

## Then end your reply exactly as the top of this prompt says.
