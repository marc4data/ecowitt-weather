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

---

# Round 2 — WARNING in capitals shipped to the repo; the deploy refused again

**Start 2026-09-21 8:49 AM.** Round 1's text above is unchanged.

## R2.1 🛑 Still not shipped — same gate, second refusal

```
Permission for this action was denied by the Claude Code auto mode classifier.
Reason: [Production Deploy]
```

The prompt said: *"let the permission prompt reach Marc; he approves it in this
window. If it's refused again without a prompt reaching him, stop."* **No
approval prompt surfaced** — the denial is automatic and comes from the
classifier, and its own text names the remedy as a settings rule rather than an
in-conversation approval. So: stopped, exactly as instructed. Nothing was routed
around.

**What I observed, precisely:** the tool call returned the classifier's refusal.
I cannot see whether anything was displayed to Marc; I only know no approval
came back. Stating that rather than asserting he was never asked.

**The VM is untouched**, re-checked after the refusal:
`ROLLING_NOT_ACCUMULATING` count `0`, and `no VERSION file`.

## R2.2 Step 0 done — WARNING is in capitals

Marc: *"WARN should be in CAPS."*

`Lake house Ecowitt System checks are good with a WARNING for Sat, Sep 12th - indoor humidity 49–69 %`

Changed at [render.py:97](src/reporting/render.py#L97) and in the docstring at
[:62](src/reporting/render.py#L62) and [:71](src/reporting/render.py#L71).

**The docstring argued the opposite and could not be left standing.** Round 1
wrote *"'warning' is lower case — two shouting words would flatten three states
back into one alarm."* That is now wrong about the code. It is replaced with
Marc's decision and a one-line record of the earlier argument, so nobody
re-opens it as though it had never been made — and with what actually separates
the two loud states now: the **verb**, "are good with" against "need", not the
case of one word.

The test follows that. [test_reporting_render.py:73](tests/test_reporting_render.py#L73)
asserted `"WARNING" not in out.subject`, which would now fail for the right
string; it asserts `"need ATTENTION" not in out.subject` instead.

### Staged break

| break | test that went red |
|---|---|
| lower-case the subject again | `test_a_warning_day_reads_as_good_with_a_warning_not_as_attention` — `assert 'are good with a WARNING for Sat, Sep 12th' in 'REPLAY — … are good with a warning for Sat, Sep 12th …'` |

Restored. `114 passed`. `ruff` 16, all in `notebooks/audit.ipynb`. No residue.

## R2.3 Step 2.4 done early, so it ships *with* this deploy

Round 1 found the install records no commit. `deploy_report.sh` now writes one:

| where | what |
|---|---|
| [deploy_report.sh:136](infra/deploy_report.sh#L136) | `DEPLOY_COMMIT="$(git rev-parse HEAD …)"`, suffixed `-dirty` when the tree is not clean |
| [deploy_report.sh:160](infra/deploy_report.sh#L160) | writes it to `/opt/ecowitt/app/VERSION` |
| [deploy_report.sh:187](infra/deploy_report.sh#L187) | the install line now names the commit |

Written **before** the slow venv build, so a deploy that dies building pandas
still leaves the truth about which tree is on disk. A dirty tree is marked
rather than quietly reported as its last commit — the failure mode would
otherwise be a VERSION file that is confidently wrong.

⚠️ **`bash -n` passed on a version of this that was broken.** The first attempt
put double quotes inside the already double-quoted `--command="…"`, which would
have terminated the string early. It still parsed as valid bash, so the syntax
check said nothing. Caught by rendering the command with a dummy value and
reading what came out, which is the only check that was actually about the
thing. Single quotes now; the commit still expands locally before it is sent.

## R2.4 What is committed and waiting

| commit | |
|---|---|
| `a87dd3f` | Cowork's round 2 prompt, register, and the CLAUDE.md correction that the email is RUNNING |
| `976d17a` | WARNING in capitals; the deploy records its commit |

**Not pushed.** Step 3 is gated on steps 1–2 passing, and they cannot.

## R2.5 What unblocks this

The classifier's message names its own remedy: *"the user can add a Bash
permission rule to their settings."* Two ways, both Marc's:

1. **Allow the deploy, then re-run the round.** A rule in
   `.claude/settings.json` covering `./infra/deploy_report.sh`.
2. **Run it himself**, in his own terminal, where no classifier sits in the way.
   The command reads the five values back from the unit rather than retyping
   them, which is the part round 1 verified.

Either way the deploy sends **one `--test` email to the test address**, not to
the household. The household sees the change at 07:00 the next morning — and
sees the old email if this never runs, because the timer is already on.

---

**Round 2 — Start 2026-09-21 8:49 AM / End 8:53 AM : 03:38**

---

# Round 3 — `--from-unit`, so Marc deploys with one command

**Start 2026-09-21 8:58 AM.** Rounds 1 and 2 above are unchanged.
**The deploy was not run, as instructed.** Nothing was installed and nothing
was sent.

## R3.1 The command Marc runs

From the repo root, in his own terminal:

```bash
./infra/deploy_report.sh --from-unit
```

That is the whole thing. No values to type. To see what it would do first,
without installing or sending:

```bash
./infra/deploy_report.sh --from-unit --print-plan
```

## R3.2 What `--from-unit` does

Reads `LAKEHOUSE_EMAIL_TO`, `LAKEHOUSE_EMAIL_TEST_TO`, `LAKEHOUSE_EMAIL_FROM`,
`LAKEHOUSE_STATION_URL` and `LAKEHOUSE_REPLY_TO` back out of the installed
`ecowitt-report.service` over IAP, and puts them straight back.

It reuses `infra/run_as_unit.sh:29-39`'s shape rather than reinventing it —
`systemctl show … -p Environment --value` plus `shlex.split` — pointed the other
way: that script runs on the VM and execs with the unit's environment, this one
brings the values back to the laptop. **`shlex` is the load-bearing part.**
Round 1 split the same output on whitespace and reported two present values as
missing, because a display name in `From` legitimately contains spaces.

The values are `eval`'d straight into variables. They never reach a file, a log,
this repo or the script's output — it prints counts:

```
    3 addresses + 2 optional, from the unit, unchanged
```

## R3.3 🚨 Three refusals, all exercised against the real VM

The prompt asked for a staged break. A shell script has no pytest here, so **the
refusal output itself is the evidence**, quoted, with its exit status.

**1 — the unit is not installed** (`UNIT=ecowitt-nonesuch.service`):

```
==> Reading the addresses back from ecowitt-nonesuch.service on ecowitt-db
REFUSED: ecowitt-nonesuch.service reported no Environment. Is the report deployed
on this box? --from-unit is for redeploys; a first install takes the values from
the environment.
```

`exit status: 2`

**2 — a value set in both places, disagreeing** (`LAKEHOUSE_EMAIL_TO` exported
to something else):

```
==> Reading the addresses back from ecowitt-report.service on ecowitt-db
REFUSED: LAKEHOUSE_EMAIL_TO is set in your environment AND in the unit, and they
differ. Unset it, or deploy without --from-unit. Not choosing for you.
```

`exit status: 2`

This is the one worth having. A redeploy that silently picks one of two
disagreeing recipient lists changes who gets the morning email, and nothing
downstream would show it.

**3 — a required address missing from the unit** names which one. Not
exercised against production, because making it fire would mean editing the
live unit file to remove a recipient. Stated as untested rather than implied to
be proven — it shares the refusal path the other two took, which is evidence
about the path, not about that branch.

`UNIT` is overridable for exactly this reason: refusal 1 runs the real code
against a real absence, rather than a second code path invented to be tested.

## R3.4 `--print-plan`, run against the live VM

```
==> Reading the addresses back from ecowitt-report.service on ecowitt-db
    3 addresses + 2 optional, from the unit, unchanged

==> Checking prerequisites
  secret ecowitt-readonly-password    ok
  secret ecowitt-emailer-password     ok
  secret lakehouse-smtp-password      ok
  database  table=email_log role=ecowitt_emailer

==> PLAN ONLY — nothing has been installed and nothing has been sent.

  instance          ecowitt-db (us-central1-a), project ecowitt-504320
  unit read         ecowitt-report.service
  addresses         <3 addresses + optional, from the unit, unchanged>
  commit to deploy  701c947-dirty
  verify mode       send (one --test email from the VM, to the test address)
  timer             enabled ONLY if that verify succeeds
```

`exit status: 0`

**The exit sits after the preflight, not before it** — so the plan run exercised
the secret checks and the database role check too. An earlier exit would have
proven only that the flag parses.

✅ **`701c947-dirty` is the VERSION marker from round 2 working**, caught in the
act: the tree was dirty because `deploy_report.sh` itself was still uncommitted
at that moment. After this round's commit a real run records a clean hash.

## R3.5 `bash -n` was not trusted this time

Round 2 found `bash -n` passing on a broken quote, so the IAP command was
rendered with dummy values and read:

```
WOULD RUN: gcloud compute ssh DUMMY-VM --zone=DUMMY-ZONE --tunnel-through-iap \
           --quiet --command=systemctl show ecowitt-report.service -p Environment --value
```

And the parser was fed a display name containing spaces, to confirm it survives
the round trip:

```
LAKEHOUSE_EMAIL_TO=a@b
LAKEHOUSE_EMAIL_TEST_TO=m@x
LAKEHOUSE_EMAIL_FROM='Lake House <s@x>'
LAKEHOUSE_STATION_URL=https://z
```

The quoting is re-applied by `shlex.quote` on the way out, so `eval` puts it
back intact — which is the exact thing round 1 got wrong.

### Two ordering bugs, found by reading rather than by `bash -n`

Both would have passed a syntax check and failed at runtime:

1. **`say()` was defined after its first caller.** The new block sits at line 75
   and `say` was defined at 205, so the first line of a `--from-unit` run would
   have been `say: command not found`. Moved to line 41, beside `SSH`.
2. **The refusal message was being echoed twice.** `$(…)` does not capture
   stderr, and python's `sys.exit("msg")` writes there — so the message was
   already on screen and `echo "$assignments" >&2` added an empty line after it.

## R3.6 Also updated

- The usage comment at the top of `deploy_report.sh` now documents the redeploy
  path, which is the usual case.
- `infra/README.md` gains **"Redeploying a box that is already installed"** with
  both commands and what the refusals protect.

## R3.7 What I did not do

- **Did not run the deploy.** Not attempted at all this round — the prompt said
  not to, and Cowork's call is that the gate is Marc's.
- **Did not push.** Waiting on the deploy's proofs, per the prompt.
- Added no settings rule granting Code standing deploy rights.

---

**Round 3 — Start 2026-09-21 8:58 AM / End 9:03 AM : 04:20**
