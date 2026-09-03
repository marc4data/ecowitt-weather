# Notebooks

Three notebooks, three questions. Keeping them separate is deliberate: a
notebook that answers one question can be read top to bottom and trusted.

| notebook | question | scope |
|---|---|---|
| `explore.ipynb` | what exists, and how is it built | the schema |
| `explore_daily.ipynb` | is yesterday sound, and what did the weather do | one day |
| `audit.ipynb` | does the whole record hold up | all-time |

Shared plumbing lives in two plain modules the notebooks import rather than
copy — `ecowitt_nb.py` (tunnel, connection, palette, fetching, metric metadata,
charts) and `ecowitt_daily.py` (the day-scoped checks and summaries). That is
not tidiness for its own sake: the tunnel-ownership bug below had to be fixed
twice because the same cell had been pasted into two notebooks.

```bash
pip install -e ".[notebook]"

# One-time: register the venv as a kernel Jupyter can see.
# Needed because Anaconda ships its own Jupyter and its own Python, and that
# Python has none of this project's packages. Without this the notebook fails
# with a bare `ModuleNotFoundError: No module named 'psycopg'`, which points at
# a missing package when the real problem is the wrong interpreter.
.venv/bin/python -m ipykernel install --user --name ecowitt \
    --display-name "Python (ecowitt)"

jupyter lab notebooks/explore.ipynb
```

## The tunnel opens itself

**No separate terminal.** `nb.ensure_db()` checks port 5433, runs
`infra/tunnel.sh` if nothing is listening, and waits for the port to genuinely
accept a connection.

The tunnel itself cannot be automated away, only its opening: Postgres binds to
localhost on the VM and nothing accepts inbound connections, so a forwarded
local port is the only route in.

Two rules make it safe with more than one notebook open:

* **A tunnel is closed only by the kernel that opened it, and only if nothing
  else is connected.** Without that check, shutting down one kernel yanks the
  tunnel out from under the other notebook mid-query — which is exactly what
  happened before the check existed.
* **`ensure_db()` probes the connection with `SELECT 1` before handing it back.**
  When a tunnel dies under an open connection, SQLAlchemy still reports
  `closed` as `False` — nobody *closed* anything, the socket just died. Only a
  query finds out, so it runs one and rebuilds the pool if it fails.

Running `./infra/tunnel.sh` yourself still works; the notebooks will use it and
leave it running.

## `explore.ipynb` — the schema

Samples every table and view **discovered from the catalog at runtime** —
nothing is hardcoded, so an object added later is automatically in scope — then
shows how the schema enforces its own rules: constraints, triggers, indexes and
columns, plus the metric catalog and what is actually stored.

Section 4 is the one worth reading. Five project rules are made *impossible to
violate* there rather than merely detectable later — the append-only trigger on
`raw_payload`, the composite `(metric, unit)` foreign key, the CHECK that stops
a credential landing in a stored URL. That enforcement layer is what
self-managed Postgres bought over BigQuery for about $44/yr.

## `explore_daily.ipynb` — the daily report

Yesterday as a complete local calendar day: local midnight to local midnight at
the native 5-minute resolution, so 23 or 25 hours on a DST changeover rather
than a wrong 24. Three parts, in the order they should be read:

1. **Boundary conditions** — is this day fit to report on. Ten checks, each with
   a verdict, the number behind it, and why it matters. They cluster at the
   boundaries because that is where a day goes wrong: the edges of the window
   (did it start and finish landing), of the grid (gaps — and whether they are
   scattered or one long hole), and of each sensor's physical range.
2. **Summary** — the day in a dozen numbers, each with *when* it happened. A
   104 ºF high at 15:00 is a normal afternoon; the same high at 03:00 is a
   broken sensor.
3. **Supporting detail** — one figure per logical group, panels stacked on a
   single shared time axis, plus the full table behind them.

Two checks exist because a healthy-looking number can hide a broken sensor:
**longest single gap** (one 40-minute hole and eight scattered singles both read
as "97% covered") and **no flatlined sensor** (a sensor stuck on one value all
day scores perfect coverage; only variance catches it).

This asks *is this day sound*. Whether the whole record holds up is
`audit.ipynb`'s job, and nothing here duplicates it.

### Kernels

**It runs on any Python 3.12 kernel.** The first cell checks whether the
current interpreter has the dependencies and, if not, adds this project's
`.venv/site-packages` to `sys.path` — safe only when the Python versions match
exactly, because compiled extensions like `psycopg` are ABI-specific. It says
loudly when it does this.

That fallback exists because pinning a kernel in the notebook does not stick:
**VS Code writes the selected kernel back into the `.ipynb` file**, so whatever
you last ran with overwrites the pin. On a machine with Anaconda plus several
project venvs, that turns into a loop.

Selecting the right kernel is still cleaner, and avoids mixing two
environments' packages in one process:

* **VS Code:** click the kernel name in the notebook's **top-right corner** →
  *Select Another Kernel…* → *Jupyter Kernel…* → **Python (ecowitt)**
* **JupyterLab:** *Kernel > Change Kernel > Python (ecowitt)*

`.vscode/settings.json` points this workspace's default interpreter at
`.venv`, so new notebooks and terminals start in the right place.

The password comes from `ECOWITT_RO_PASSWORD` if set, otherwise Secret Manager.
It is never stored in the notebook.

### Why the hourly table isn't a plain `AVG`

Each metric is aggregated by its own `metric_catalog.resample_rule`, because one
rule cannot serve every metric:

| kind | rule | what a plain average would do |
|---|---|---|
| `circular` | vector mean | averaging 350° and 10° gives 180° — due south for a north wind |
| `extremum` | `max` | understate peak gusts |
| `accumulator` | `last` | average a running total, which means nothing |
| `opaque`/`status` | `last` | do arithmetic on a code that isn't a number |

Measured on real data from this station: in one hour where the wind swung
between 60° and 345°, the linear average read **192.6°** against a correct
vector mean of **162.7°** — a 29.9° error. Over a north-crossing hour the same
mistake reaches 180°.

Executed notebooks are gitignored — they are large, full of data, and
regenerable. Only the source is tracked.


## `audit.ipynb` — the whole record

Proves the record says what it should. 23 checks, each able to fail, several
deliberately redundant with a database constraint — a constraint that is never
exercised is a claim rather than a guarantee.

```bash
jupyter lab notebooks/audit.ipynb
```

Covers run continuity, resolution verification, grid coverage, constraint
integrity (duplicates, unit drift, unclassified metrics, exact degree-sign
bytes), quarantine, physical plausibility of values, raw-payload retention,
credential leakage, and backup freshness.

**The last check is the one that matters.** It takes a stored raw payload, runs
it back through the *same* `ingest.normalize` code the pipeline uses, and
compares row by row against what is in the table. Everything else tests internal
consistency; this tests whether the curated data is reproducible from the
evidence — which is the claim §10 makes when it says parsing bugs are
recoverable but discarded data is not.

Current result: 4,914 rows re-derived, 4,914 matched, 0 mismatches.
