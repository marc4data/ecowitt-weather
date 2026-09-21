# lake-main-R-009 — report

**Ship R-001 and R-002 to the VM**

**Session:** `main` · **Branch:** `daily-email`

---

## 🛑 NOT SHIPPED. The deploy was blocked by the harness, not by the VM.

Everything up to the deploy is done and checked. The deploy itself was refused:

```
Permission for this action was denied by the Claude Code auto mode classifier.
Reason: [Production Deploy]
```

That is Claude Code's own permission layer on this machine, gating an action
that reaches Marc's server. It is not a failure of `deploy_report.sh`, of the
VM, of `gcloud`, or of the credentials — none of those were reached. **Naming
the tool and the exact refusal rather than calling it a capability limit**, per
the project's own rule about one tool's refusal.

Working around it was not attempted. The deploy is the gated action itself, so
there is no safer route to the same end — only a more roundabout one, which
would defeat the point of the gate.

**Nothing was pushed either.** The prompt orders the push *after* the deploy
proofs; producing step 6 while steps 4 and 5 are impossible would put the
branch on origin in a state that reads as shipped. Held deliberately, not
forgotten.

## 1. What was completed

| step | state |
|---|---|
| Commit Cowork's edits (prompt + register) | ✅ `8f62215` |
| Verify what would ship | ✅ 10 commits, all round work or Cowork edits — none unexpected |
| Public-repo secret scan on the outgoing diff | ✅ clean |
| Read the five env values back from the unit | ✅ all five present, **unchanged, values withheld** |
| Name the deploy script's timer guard | ✅ §4 below |
| Pre-deploy baseline on the VM | ✅ §3 below — and it is worth reading |
| **Run the deploy** | 🛑 **refused by the harness** |
| The three post-deploy proofs | ⛔ not reachable |
| Push `daily-email` | ⛔ held, see above |

## 2. ⚠️ The env values — a false alarm I caught before reporting it

My first read of the unit's environment said **`LAKEHOUSE_EMAIL_FROM` and
`LAKEHOUSE_STATION_URL` were ABSENT**, which would have contradicted the prompt
and blocked the deploy on its own.

It was wrong, and the instrument was mine. I split systemd's `Environment`
output on spaces (`tr ' ' '\n'`). Those two values legitimately *contain*
spaces — `LAKEHOUSE_EMAIL_FROM` is a display name plus an address — so the
split shredded them into fragments that no longer looked like keys.

Re-read with `shlex.split`, which honours systemd's quoting: **all five are
present.** The prompt was right and I was about to file a finding against it.

Third time this session that a filter, not the thing filtered, was the fault.

## 3. 🚨 The baseline, and it is larger than the round assumed

Read-only over IAP, before any change:

| | |
|---|---|
| `ROLLING_NOT_ACCUMULATING` in the installed `ecowitt_daily.py` | **absent** — R-002 is not on the VM |
| installed rain chart title (`src/reporting/charts.py:411`) | `Rain by the hour — last 7 days · {week_total:.2f} in in total` |
| install records a commit? | **no** — no `VERSION` or `.commit` file under `/opt/ecowitt/app` |

**That title is the pre-R-001 title.** So the VM is not merely missing R-002 —
it is running code from before R-001 as well. All four requests are unshipped,
which matches the prompt's table.

### And the timer is already on

```
NEXT                        LEFT      LAST                        PASSED
Tue 2026-09-22 12:02:09 UTC 20h left  Mon 2026-09-21 12:01:47 UTC 3h 38min ago   ecowitt-report.timer
```

`12:02 UTC` is **07:02 Central**. The report timer is enabled and ran this
morning.

⚠️ **This changes what the deploy is.** `deploy_report.sh`'s send-verify exists
to enable a timer that is off; here the timer is already running, so the deploy
is an **update to a live system that mails three people tomorrow at 07:00**, not
a first enable. Consequences worth stating before anyone runs it:

- Doing nothing is not neutral. **Tomorrow's 07:00 email goes out either way** —
  as the old one, with `Rain by the hour`, the week total, two subject forms,
  and "rain totals went backwards" on days it only rained.
- ⚠️ **CLAUDE.md's header is stale.** It still says the daily email is
  *"built 2026-08-28, ready to deploy, NOT YET RUNNING."* It is running, and has
  been for long enough to produce the September emails R-002 and R-003 were
  raised about. Not corrected here — it is one line, but it is a claim about
  production and Cowork owns the narrative; flagged rather than edited.

## 4. The staged break, as the prompt defined it

The prompt asked for the line in `deploy_report.sh` that keeps the timer off
when the test send fails, quoted rather than re-run against production.

[infra/deploy_report.sh:192-210](infra/deploy_report.sh#L192):

```bash
case "$VERIFY" in
send)
    say "Sending one --test email from the VM to $LAKEHOUSE_EMAIL_TEST_TO"
    if run_on_vm --test; then
        say "That email arrived. Enabling the timer."
        "${SSH[@]}" --command="sudo systemctl enable --now ecowitt-report.timer"
    else
        cat >&2 <<'EOF2'

REFUSED TO ENABLE THE TIMER: the test send failed.
...
EOF2
        exit 1
    fi
    ;;
```

**The guard exists.** `systemctl enable` sits inside the `then` branch of
`if run_on_vm --test`, so a failed send cannot reach it, and the `else` branch
exits 1. `VERIFY` defaults to `send` at line 39, so the guard is on by default
and only `--skip-verify` (line 237, which the prompt forbids) bypasses it.

⚠️ **One caveat the prompt could not have known**, following from §3: this guard
protects the *enable*. With the timer already enabled, a failed test send leaves
the script exiting 1 **with the new code already installed** (line 175,
`installed; timer not enabled yet`, runs before the verify) and the timer still
on from before. The guard cannot disable what it did not enable. That is not a
reason to avoid the deploy — but it means "the deploy failed" and "the old code
is still what sends" are not the same statement here, and only the first is
guaranteed.

## 5. What I need, and it is Marc's to give

The deploy is one command and everything it needs is verified. It requires
permission for `./infra/deploy_report.sh` to run, which the auto-mode classifier
holds. It sends **one `--test` email to the test address**, not to the
household; the household sees the change at 07:00 tomorrow.

Held with it: the `git push` of `daily-email` to origin, for the reason in the
header.

---

**Start 2026-09-21 8:38 AM / End 8:42 AM : 03:39**
