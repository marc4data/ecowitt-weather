# lake-main-R-013 — round 3: add a box plot under the histogram, scrub the three unpushed commits, then push

**Session:** `main` · **Register:** R-013

## 🚨 Read this first — how your reply ends, whatever happens

1. `Report written: [lake-main-R-013-report.md](claude_work/reports/lake-main-R-013-report.md)`
2. The return cell, **exactly this, no slash, no prefix**:
   ```
   project-round-close lake-main-R-013
   ```
3. `**Start YYYY-MM-DD H:MM AM/PM / End H:MM AM/PM : MM:SS**` — `TZ=America/Los_Angeles`

This applies if you stop early too.

## Why this round exists

Round 2 was right to stop. Cowork's round 2 prompt and register row carried the
town and the full station URL, and told you to commit them; `11bea41` did. None
of the three commits (`11bea41`, `08709a0`, `ffff0c3`) is on origin —
`origin/daily-email` is still `dea5cb4`. Cowork has now scrubbed both files in the
working tree (the town and URL now read as "kept in `.env`"). Round 2's chart
was reviewed and accepted. The one chart change this round is the box plot Marc
asked for (below); nothing else on the figure moves.

This prompt deliberately does not spell out the town or the station id. Get them
from `.env` (`LAKEHOUSE_LOCATION_LABEL`, and the `id=` value in
`LAKEHOUSE_STATION_URL`) for the checks below.

## Step 0 — confirm the ground

- **First, clear what Cowork left in `.git`.** On 2026-09-21 at 2:57 PM Cowork ran
  `git fetch` over the device bridge (against its own rule) and couldn't clean
  up: `.git/objects/maintenance.lock` (empty) and
  `.git/objects/08/tmp_obj_kLsbA9` are left behind. Check that no git process is
  running, delete both, and say that you did. The fetch didn't move any ref:
  `origin/daily-email` is still `dea5cb4`.
- `git fetch`; `origin/daily-email` is `dea5cb4`, local `HEAD` is `ffff0c3`.
  If either differs, stop and report.
- `notebooks/explore.ipynb` stays out of every commit, as before.

## Staged break — show the check goes red first

On the **old** range, before touching anything:
`git log -p dea5cb4..ffff0c3 | grep -F -i -c -e "<station id>" -e "<town>"`
(using the `.env` values). Quote the non-zero count.

## The box plot (Marc, 2026-09-21)

> Can you add a horizontal box-whisker with IQRs, p25, p50, p75 all denoted,
> underneath the histogram. Align the x-axis between the histogram and the
> box-whisker. Box whisker should only take up 20% of the vertical space.

Marc chose (Cowork asked): **whiskers at 1.5 × IQR, days beyond shown as dots.**

- Split the right-hand column vertically: histogram on top, box plot below, height
  ratio **4 : 1** (the box plot takes 20% of the column). The left panel keeps the
  full height, and the 60/40 width split stays.
- **Same x-axis**: `sharex` with the histogram, so a degree sits at the same
  horizontal position in both. The x tick labels and the "Daily high (ºF,
  rounded)" axis label move to the bottom of the box plot. Hide them on the
  histogram, but keep its vertical gridlines if it has any.
- **Data**: the same 48 rounded daily highs the histogram counts, so the two
  panels describe the same numbers. Quartiles: `numpy.percentile`, default
  (linear) method. Quote p25, p50, p75, IQR, whisker ends, and which days fall
  outside, and cross-check them against the histogram counts by hand in the report.
  **Cowork's expectation**, worked from round 2's histogram counts: p25 104, p50
  106, p75 107, IQR 3 ºF; whiskers 102 to 110; 8 days as dots: 92, 95, 99, 99
  (cool side) and 112, 113, 115, 115 (hot side). If you get something different,
  say which one is wrong and why.
- **Labels on the box plot**: p25, p50 and p75, each with its value, and an IQR
  bracket or label showing its width in ºF. Show whole numbers, or one decimal where
  the linear method lands between degrees. No y-axis ticks: it's one row.
- **Style**: box outline in the same orange as the ≥ 100 bars, with a light fill
  and a heavier median line. Dots beyond the whiskers in the muted grey used for
  the < 100 days.
- The overlap check from round 2 covers the new panel too: no text on any bar,
  box or dot, and no text on other text.

**Staged break for the alignment:** also assert that the two right-hand axes have
equal `get_xlim()` and the same left and right edges in figure coordinates
(`get_position()`). Show it failing once with the `sharex` removed and the
box's x-limits nudged, then passing.

Save `data/reports/preview/hot-days.png` again at the same size and dpi, and
look at it. Clear the section's cell outputs before committing, as in round 2.

## The rewrite

1. `git reset --soft dea5cb4` — safe, nothing here was pushed.
2. `git add` Cowork's scrubbed `claude_work/lake_request_register.md` and
   `claude_work/prompts/lake-main-R-013.md`, `notebooks/explore_daily.ipynb`
   (box plot, outputs cleared), plus your report (round 3 section added).
3. Recommit. Two commits is fine (Cowork's files; chart + report), or one — your
   call. Commit messages must not name the town or station id either.
4. Same grep on the **new** range: `git log -p dea5cb4..HEAD` — quote the empty
   result (count 0). Also grep the whole tree at `HEAD`:
   `git grep -F -i -e "<station id>" -e "<town>" HEAD` — empty.
5. Only if both are empty: `git push origin daily-email` (a plain fast-forward;
   no force needed, none allowed). Cowork has reviewed this round's content — the
   push is approved on that condition, **and only if the box plot's checks
   pass**. If they don't, commit locally, don't push, and say why. No deploy;
   notebook-only change.
6. The old commits stay in your local reflog only; don't push any ref that holds
   them.

## Definition of done

- Box plot in place: quartiles quoted and cross-checked, alignment check shown
  red then green, overlap check 0.
- Red count on the old range, 0 on the new range and at `HEAD`.
- `origin/daily-email` = new `HEAD`; quote `git log --oneline -4 origin/daily-email`.
- Round 3 section in the report.

## Then end your reply exactly as the top of this prompt says.

---

# Round 2 (done — kept for the record)

## Step 0

Commit Cowork's edits (register, this prompt) only. Still leave
`notebooks/explore.ipynb` out.

## What Marc asked for (he's sending the image to friends)

> Trim the dataset to start on Aug 4th or whatever the 1st 100+ day is (apply
> that filter to the dataset, which then feeds into both charts). Increase the
> size of the histogram so that it takes 40% of the width of the row. Don't need
> the vertical reference line. Remove the (%). Y-axis should only have integers,
> (major ticks and gridlines at 5, 10, etc). Chart Title = High Temp
> Distribution Aug X to Sept 20, 2026 (X days). Somewhere it needs to indicate
> [town — kept in `.env`]. I'm sending this to friends, so include this link
> ([station URL — kept in `.env`]), or shortened version of it.
> Move the annotation on the left chart to be placed top-right in the chart.
> Should be greater than or equal. Add the % to the annotation.

## The changes

**The rule and the data (both panels):**
- "Hot" is now **rounded daily high ≥ 100 ºF** (was ≥ 101). Update the section's
  markdown to say so.
- The dataset starts on the **first complete day whose rounded high is ≥ 100**,
  computed, not hard-coded. It ends on yesterday. Both panels, the count, the
  percentage and the longest run all read from this one filtered frame.
- The SQL cross-check `assert` applies the same filter and still has to agree.
- Expected from round 1's data: start **4 Aug**, **44 of 48 days**, 92 %, with the
  longest run unchanged at 18 days (4–21 Aug). If you get different numbers, say
  why before continuing.

**Left panel:**
- Annotation moves to the **top-right** inside the axes, in space that is clear
  by construction. Raise the y-limit if you need to — bars reach about 112 ºF near
  the right edge. Text: `44 of 48 days ≥ 100 ºF (92%)`.
- Keep the heavy 100 ºF rule, the accent/muted split (now at ≥ 100), and no bar
  labels.

**Right panel (histogram):**
- **40 % of the row width** (`width_ratios=[3, 2]`).
- Title: `High Temp Distribution Aug 4 to Sept 20, 2026 (48 days)`, with the dates
  and count computed. Use Marc's "Sept" spelling for September; other months
  use their normal 3-letter short form.
- **Remove** the vertical boundary line.
- Labels above bars: the **count only**, no percentage.
- Y axis: integer ticks, **major ticks and gridlines every 5** (0, 5, 10, 15…).
  No fractional ticks.

**The whole figure — for sharing:**
- Show **the town** (from `.env`) in a figure-level title or subtitle, e.g. *"Lake house
  weather station — <town>"*.
- A footer line with the station link, shortened to display as
  `ecowitt.net/home/index?id=<station id>` (drop `https://www.`), e.g.
  *"Live station: ecowitt.net/home/index?id=<station id>"*.

## 🚨 The town and the link stay out of the public repo

02_DAILY_EMAIL_AS_BUILT §5.2: the repo is public. Location details were
scrubbed from it, and the station URL is substituted at deploy time, never
committed. So:

- Read the URL from `LAKEHOUSE_STATION_URL` (already in `.env`) and the town from
  a new `.env` key, `LAKEHOUSE_LOCATION_LABEL=<town, ST>`. Add that key to `.env`
  locally, and to `.env.example` **empty**, the same way the station URL is
  listed there.
- If either is unset, draw the figure without it — no placeholder text, no error.
- **This section's cell outputs are not committed.** The rendered image would
  carry both. Clear that cell's outputs before committing the notebook (or save
  with outputs and strip that cell). Say which you did. The shareable PNG lives
  in `data/reports/preview/hot-days.png`, which is gitignored.
- Before committing, `grep` the staged diff for the station id and the town (both in `.env`) and quote
  the empty result.

## Layout check — this round's staged break

Round 1 said the annotation was in clear space; it wasn't. So check with the
rendered figure's **bounding boxes** (`get_window_extent`), not by eye: no text
overlaps any bar, and no text overlaps any other text, on either panel.

- Run the check on **round 1's figure first** and quote its non-zero count. That
  proves the check can go red.
- Then run it on the new figure and show 0.

## Definition of done

- Numbers as above, with both counting methods agreeing.
- Bounding-box check: non-zero on round 1, 0 on round 2.
- `data/reports/preview/hot-days.png` re-saved. **Also save it at full
  resolution for sharing** (≥ 200 dpi) and look at it.
- Commit and push `daily-email`. Round 2 section in the report.

## Then end your reply exactly as the top of this prompt says.
