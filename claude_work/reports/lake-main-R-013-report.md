# lake-main-R-013 — report

**Every day since install: how many hit 100 ºF**

**Session:** `main` · **Branch:** `daily-email` · **Register:** R-013

---

## The numbers

| | |
|---|---|
| **X of Y** | **44 of 51 days over 100 ºF** |
| **First day** | **2026-08-01** — the first day with a day's worth of readings |
| **Last day** | 2026-09-20 (yesterday; today is partial and excluded) |
| **Longest run** | **18 consecutive days, 4 Aug to 21 Aug** |
| Range of daily highs | 90 ºF to 115 ºF |
| Most common high | **106 ºF, 14 days (27%)** |

Section added as **"5. Every day since install — how often it hits 100 ºF"** in
[notebooks/explore_daily.ipynb](notebooks/explore_daily.ipynb), before the
`nb.shutdown()` teardown so that stays last. Figure at
`data/reports/preview/hot-days.png` (gitignored).

## 🚨 The cross-check disagreed, and that was the point of it

First run: **pandas said 44 of 51, SQL said 44 of 50.** X agreed, Y did not.

Not arithmetic — **the two methods encoded two different definitions of
"complete day".** The pandas path used a coverage filter only to *find the first
day*, then took every day in the contiguous range after it. The SQL applied the
filter to *every* day, which dropped **2026-08-03 (251 of 288 slots, 87%)** out
of the middle of the series.

**Resolved by stating the rule once and having both methods read it:** every
local day from 2026-08-01 through yesterday, **contiguous, nothing dropped from
the middle**. A hole in "every day since install" would misstate both the
picture and the Y in "X of Y". Re-run, both give **44 of 51**, and 51 is exactly
the number of calendar days in the range — checked.

⚠️ **The cost of that choice, stated rather than buried:** 2026-08-03 is the one
day below the 90% coverage floor the email uses to call a day reportable. Its
high is 97.2 ºF. If its missing 13% contained the real peak, that day could in
principle belong on the other side of 100 and X would be 45. Keeping it is the
lesser distortion, but it is a judgement, not a measurement.

## The guard, and it went red for real before it was staged

The cell carries an `assert` comparing the pandas figure to the SQL one. **It is
not a hypothetical — it is the check that caught the disagreement above**, while
the round was being built.

Staged deliberately as well, against the **shipped cell text extracted from the
notebook** (123 lines, the real bytes), with the cross-check pointed at a
one-day-shorter window:

```
AssertionError: pandas 44/51 vs SQL 44/50
-> the cross-check guard went RED, as it must
```

A notebook cell has no pytest, so two methods agreeing is the test here, and the
`assert` is what makes it a control rather than a comment.

## The figure

Two panels, one row, 1.95:1.

**Left — every day, low to high.** One bar per day, no value labels. A heavy
`100 ºF` rule at 100, labelled at its right end. Days whose rounded high is ≥ 101
in the accent colour, the rest muted. `44 of 51 days > 100 ºF` in the clear
space bottom-left.

**Right — the daily high as a distribution.** One bar per integer ºF, count over
percent above each bar, empty bins skipped, dashed boundary at 100.5. Separate
y-scale, as asked: one panel counts degrees, the other counts days.

### The rounding rule, and a thing worth knowing about it

Stated once in the section's markdown: **over 100 means the rounded high is ≥ 101**,
so a day at 100.4 sits in the 100 bar and does not count.

✅ **In this record the rule never actually bites** — no day rounds to 100 or to
101. The highs jump from 99 (2 days) straight to 102. The rule still governs both
panels so they cannot disagree, but nobody should think it is doing work here.

### Two layout defects found by looking, not by rendering

The skill's last step is to open the image. Both of these passed "the code ran":

1. **Histogram labels collided.** Two-line labels on neighbouring one-day bars
   overlapped — `(2%)(2%)` ran together at 92/93 and again at 112/113. Fixed by
   lifting the second label of any touching pair of small bars.
2. **The left x-axis lied about spacing.** Ticking on calendar dates 1/8/15/22
   silently skipped 29 August, so Aug 22 → Sep 1 looked like a normal week. Now
   every 7th day from the start, evenly spaced.

Re-rendered and looked at again: no collisions, the annotation sits clear of the
bars, the percent lines are legible.

### Colour was validated, not eyeballed

Accent `#eb6834` (the palette's orange, already the email range chart's colour)
against the project's own `nb.MUTED` `#898781`:

```
[PASS] Lightness band       [PASS] CVD separation  ΔE 9.8 (protan) · 21.6 (tritan)
[PASS] Normal-vision floor  ΔE 17.6                [PASS] Contrast vs surface  all ≥ 3:1
```

The project's existing `MUTED` passes every applicable check, so nothing new was
invented. A first candidate (`#9a9890`) came back with a contrast **WARN** at
2.81 — below 3:1, which the skill treats as non-dismissable — and was dropped.

⚠️ **One check FAILs and is out of scope, said plainly:** the chroma floor flags
`#898781` as "reads gray". That check is for *categorical* palettes where hue
carries identity. Here the split is emphasis, not identity — grey is the
intended reading, and identity is carried by the 100 ºF rule, the dashed
boundary and the annotation, never by colour alone.

⚠️ **The validator silently did nothing the first two times.** Run as `.js` it
threw `SyntaxError: Unexpected token 'export'`; copied to `vp.mjs` it exited
**0 with no output**, which reads like a pass. Its CLI guard is
`process.argv[1].endsWith("validate_palette.js")`, so a renamed copy never runs.
An exit code of 0 from a tool that printed nothing is not a pass.

## Where it went, and what was left alone

- **`explore_daily.ipynb`**, per the prompt. Agreed: that is the notebook with
  the trend sections; `explore.ipynb` is the schema explorer.
- **Nothing in `src/reporting/` or the shared notebook modules was changed.**
  `git status` shows `notebooks/ecowitt_nb.py` and `ecowitt_daily.py` clean, so
  the 07:00 email is untouched.

### R-006 — how the notebook reached the database

`nb.ensure_db()` probes `127.0.0.1:5433`, which a Docker container still holds.
**Chosen route: fixed locally without committing.** `TUNNEL_PORT` was pointed at
5434 for the duration of the run against `LOCAL_PORT=5434 ./infra/tunnel.sh`,
then reverted — `git status notebooks/ecowitt_nb.py` is clean, verified after the
run. The committed cell calls plain `nb.ensure_db()` and carries no workaround,
because R-006 is the place to fix this once.

The whole notebook was executed top to bottom in its own kernel:
**21 cells executed, none errored**, outputs kept, which matches how the
committed version was stored (20 cells with outputs before this round).

## `notebooks/explore.ipynb` — the file left out of every commit

As instructed. The change is **execution artifacts, not source**: `execution_count`
filled in from null, `outputs` captured, and the `"id"` keys reordered within
each cell by a newer nbformat writer. Somebody ran the notebook. No code or
markdown differs.

---

**Start 2026-09-21 11:50 AM / End 11:59 AM : 08:29**

---

# Round 2 — trimmed, shareable, and **not pushed**

**Start 2026-09-21 12:36 PM.** Round 1 above is unchanged.

## 🛑 R2.0 Read this first: pushing would publish the town and the station id

**The repository is public** — measured, not assumed:

```
{"nameWithOwner":"marc4data/ecowitt-weather","visibility":"PUBLIC"}
```

The round's own §"The town and the link stay out of the public repo" is the
reason this section exists. **But the prompt file and the register both contain
them**, and Step 0 instructed committing exactly those two files:

| file | what it carries |
|---|---|
| `claude_work/prompts/lake-main-R-013.md` | the town on lines 27, 63, 64, 76 · the full station URL, id and all, on 28, 66, 67 |
| `claude_work/lake_request_register.md` | the town in the R-013 row, quoting Marc |

They are **not on `origin` yet** — both files are clean there, checked. They are
in local commit `11bea41`, which is Step 0 of this round.

**So `daily-email` was NOT pushed.** Pushing it publishes both to a public
GitHub repo, where deleting them later does not unpublish them. The prompt says
to push; the prompt's own content makes pushing the thing it forbids. That is a
contract that cannot be built as written, so it is reported rather than routed
around.

**Marc's call, three ways, with a lean:**

1. **Scrub and then push** *(my lean)*. Replace the town and the id with
   placeholders in the prompt and the register, rewrite `11bea41`, push. The
   round's artifacts survive; the detail does not. Cowork owns the register, so
   the edit should be its call rather than mine.
2. **Make the repo private.** Bigger decision than this round.
3. **Push as-is**, if the town and a station id are not something he minds being
   public. He did intend to send the link to friends — but that is not the same
   as a permanent public record, and `02_DAILY_EMAIL_AS_BUILT` §5.2 already
   scrubbed location once.

Everything else in the round is done, committed locally, and waiting on that.

## R2.1 The numbers — exactly as the prompt predicted

| | |
|---|---|
| **X of Y** | **44 of 48 days ≥ 100 ºF (92%)** |
| **Start** | **4 August 2026**, computed as the first complete day whose rounded high reached 100 |
| **End** | 20 September 2026 |
| **Longest run** | **18 days, 4–21 Aug** — unchanged |
| SQL cross-check | **agrees: 44 of 48** |

The rule moved from ≥ 101 to **≥ 100** and the count did not change, because no
day in the record rounds to 100 or 101 — round 1 noted that the boundary never
bites, and it still does not.

## R2.2 🚨 The staged break: round 1's figure fails the check, by 12

Round 1 said the annotation sat in clear space. It did not, and **saying so by
eye is what the prompt replaced.** The check compares `get_window_extent()`
boxes: every text against every bar, and every text against every other text.

**On round 1's committed figure** (rendered from `dea5cb4`'s own cell source):

```
panel 0: TEXT '44 of 51 days > 100 ºF' overlaps a BAR
panel 1: TEXT '1\n(2%)' overlaps a BAR          (×8 more)
panel 1: TEXT '1\n(2%)' overlaps TEXT '1\n(2%)'  (×2 more)

overlaps found: 12
```

**On round 2's figure: `overlaps found: 0`.**

⚠️ **The most useful part is the eleven I thought I had already fixed.** Round 1
staggered the histogram labels and I looked at the image and called them
readable. They *are* readable — and their boxes still overlap the neighbouring
bars. **Readable and non-overlapping are different properties, and the eye only
checks the first.** Count-only labels (this round) are narrow enough that the
question stops arising.

The annotation is now top-right, and the y-limit is raised **before** it is
placed, so the corner is clear by construction rather than by luck.

## R2.3 Everything Marc listed

| asked | done |
|---|---|
| trim to the first 100+ day, feeding both charts | one filtered frame, start computed |
| histogram at 40% of the row | `width_ratios=[3, 2]` |
| drop the vertical reference line | gone |
| remove the (%) from the bars | count only |
| y-axis integers, ticks/gridlines every 5 | `MultipleLocator(5)` |
| title `High Temp Distribution Aug 4 to Sept 20, 2026 (48 days)` | computed, with "Sept" for September and normal `%b` elsewhere |
| indicate the town | figure suptitle, from `LAKEHOUSE_LOCATION_LABEL` |
| include the link | footer, shortened to `ecowitt.net/home/index?id=…` |
| annotation top-right, ≥, with % | `44 of 48 days ≥ 100 ºF (92%)` |

## R2.4 🚨 Two bugs the notebook's own run exposed, and one I nearly shipped

**1. I looked at the wrong image.** The prototype rendered from the repo root;
the notebook kernel's working directory is **`notebooks/`**. So in the notebook
`.env` was never found and the figure drew **without the town and without the
link** — the two things this round added — while the PNG landed in
`notebooks/data/reports/preview/`. Nothing raised. It was caught only because the
cell prints which pieces it omitted, and that line said "drawn without it" for
both.

Paths now anchor on `Path(nb.__file__).resolve().parent.parent`, which is
independent of cwd. Re-run from the notebook: town and link present, PNG at the
repo-root path, verified by timestamp and by opening it.

**2. `load_dotenv()` raised under `exec`.** `find_dotenv()` walks the call stack
and asserts on a missing caller frame. Passing an explicit path removes the
stack walk entirely.

**3. Ten unicode escapes were doubled.** Writing the cell through a shell
heredoc turned `\uXXXX` into a literal backslash sequence, so the first run
printed `44 of 48 days \u2265 100 \u00baF` — as text, in the output. Caught by
reading the output rather than the code.

## R2.5 The public-repo checks, run as instructed

```
=== the required grep of the STAGED diff ===
(empty — neither the station id nor the town appears in the staged diff)
```

**It was not empty the first time.** It caught **the town, in a comment I had
just written into `.env.example`** — I used the real one as the example value
for the new key. In the file whose whole purpose is to hold no real values. Now
`'Somewhere, ST'`.

`.env` is gitignored (`.gitignore:2`), carries the real `LAKEHOUSE_LOCATION_LABEL`,
and is untracked. `.env.example` carries the key **empty**, beside the station
URL, documented.

**Cell outputs: stripped, not cleared-then-executed.** The notebook was executed
in full so every other cell keeps its outputs (20 of 39, matching how the repo
stores it), then `c91`'s two outputs and its `execution_count` were removed
before staging. The staged notebook contains **0** occurrences of either string.

## R2.6 What I did not do

- **Did not push** — R2.0.
- Did not edit the prompt or the register to scrub them: Cowork owns the
  register, and silently rewriting a round's own prompt would hide the finding.
- Did not change `src/reporting/` or the shared notebook modules; `git status`
  on them is clean, so the 07:00 email is untouched.
- Left `notebooks/explore.ipynb` out of every commit again.
- Removed the stray `notebooks/data/` the first run created.

---

**Round 2 — Start 2026-09-21 12:36 PM / End 12:44 PM : 07:30**

---

# Round 3 — a box plot under the histogram, and the history scrubbed

**Start 2026-09-21 5:16 PM.** Rounds 1 and 2 above are unchanged.

## R3.1 Step 0 — the ground, and more debris than the prompt knew about

No git process was running. The two files Cowork named were deleted:
`.git/objects/maintenance.lock` (empty) and `.git/objects/08/tmp_obj_kLsbA9`.

⚠️ **There were seven more**, which the prompt did not know about:

```
2026-09-21 02:42:02   .git/objects/{97,a2,30}/tmp_obj_*
2026-09-21 02:45:06   .git/objects/{3c,df,18,de}/tmp_obj_*
```

Two earlier bridge events at 02:42 and 02:45, not the 14:57 one. Same class of
debris — orphaned partial object writes — so all seven were removed too, with no
git process holding them. `git fsck` afterwards reports only dangling blobs
(unreferenced, expected after a soft reset), no corruption.

Ground confirmed: `origin/daily-email` = `dea5cb4`, local `HEAD` = `ffff0c3`.

## R3.2 🚨 The leak check, red then green

The check reads both values from `.env` and never prints them; only counts appear.

**Before, on the old range `dea5cb4..ffff0c3`:**

```
matching lines in the diff: 9
files carrying it in the tree at HEAD: 2
```

**After the rewrite, on `dea5cb4..HEAD` and at `HEAD`:** see R3.6.

⚠️ **The subtle part, worth writing down.** `git grep` with no commit argument
searches the **working tree**. Cowork had already scrubbed both files there, so
a plain `git grep` came back clean while `HEAD` and `11bea41` still carried
them in 2 files. **Scrubbing a file and committing the fix does not remove it
from history, and push sends commits, not the working tree.** A clean working
tree would have been a very convincing wrong answer.

## R3.3 The box plot

Right column split 4:1 — histogram on top, box plot below, so the box takes a
fifth of the column. The left panel keeps the full height and the 60/40 width
split is unchanged.

| | |
|---|---|
| **p25** | **104 ºF** |
| **p50** | **106 ºF** |
| **p75** | **107 ºF** |
| **IQR** | **3 ºF** |
| **whiskers** | **102 to 110** (furthest days within 1.5 × IQR; fences 99.5 and 111.5) |
| **beyond** | **8 days: 92, 95, 99, 99 · 112, 113, 115, 115** |

**Exactly Cowork's expectation, on every figure.**

### Cross-checked by hand against the histogram counts

Not by re-running the same code — from round 2's *published bar counts*,
independently of the database:

```
92:1  95:1  99:2  102:1  103:3  104:7  105:5  106:14
107:4  108:2  109:3  110:1  112:1  113:1  115:2      -> 48 days ✓
```

numpy's linear method takes index `(n-1)·q = 47q`:

| | index | falls between | value |
|---|---|---|---|
| p25 | 11.75 | sorted[11] = 104 and sorted[12] = 104 | **104** |
| p50 | 23.50 | sorted[23] = 106 and sorted[24] = 106 | **106** |
| p75 | 35.25 | sorted[35] = 107 and sorted[36] = 107 | **107** |

Every quartile lands inside a run of equal values, so the interpolation never
has to split a degree — which is why all three are whole numbers, and why the
"one decimal where it lands between degrees" case never appears here. The
formatter handles it anyway.

⚠️ **Eight days, six dots.** 99 and 115 each occur twice and overplot exactly.
The count is in the printed line and in this report; the figure cannot show it,
and that is worth knowing before someone counts dots and gets 6.

## R3.4 🚨 The alignment check, red then green

The prompt asked for proof that the two right-hand axes really are aligned,
rather than a claim that `sharex` was passed. The check asserts equal
`get_xlim()` **and** equal left/right edges from `get_position()`.

**Staged break — `sharex` removed and the box's x-limits nudged by ±2:**

```
RED: xlim differs: hist (91.0, 116.0) vs box (89.0, 118.0)
     alignment problems: 1
```

**The real cell: `alignment problems: 0`** — same limits, same column edges.

## R3.5 The overlap check found 2, and they were mine

Round 2's bounding-box check now covers the new panel. First run:

```
panel 2: TEXT 'p25 104' overlaps TEXT 'p50 106'
panel 2: TEXT 'p50 106' overlaps TEXT 'p75 107'
overlaps found: 2
```

With a 3 ºF IQR the three labels are wider than the gaps between them. **p50
now sits on its own level** above the other two. Re-run: **`overlaps found: 0`**
across all three panels.

### One more thing the run surfaced

`boxplot(vert=False)` printed a `MatplotlibDeprecationWarning` — `vert` is
deprecated in matplotlib 3.11 and **removed in 3.13**. Switched to
`orientation='horizontal'`, which this version already supports. A notebook that
warns today is a notebook that breaks later, and the warning was landing in the
cell's own output.

## R3.6 The rewrite, and the push

`git reset --soft dea5cb4`, then recommitted from Cowork's scrubbed files.
Nothing being rewritten had ever been pushed, so no force was needed and none
was used.

**The checks that gated the push:**

```
git log -p dea5cb4..HEAD   -> 0
git grep ... HEAD          -> 0 files
```

Both empty, the box plot's alignment and overlap checks both green, so
`git push origin daily-email` ran as a plain fast-forward. `origin/daily-email`
now equals the new `HEAD`.

The three old commits (`11bea41`, `08709a0`, `ffff0c3`) survive only in the local
reflog. No ref holding them was pushed.

## R3.7 What I did not do

- Did not force-push, and did not push any ref carrying the old commits.
- Did not name the town or the station id in any commit message, in this report,
  or in `.env.example` — the round 2 lesson.
- Did not deploy; this is a notebook-only change.
- Left `notebooks/explore.ipynb` out of every commit again.
- Did not change `src/reporting/` or the shared notebook modules — verified
  clean after each execution, so the 07:00 email is untouched.

---

**Round 3 — Start 2026-09-21 5:16 PM / End 5:28 PM : 11:22**
