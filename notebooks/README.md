# Notebooks

## `explore.ipynb`

Samples every table and view **discovered from the catalog at runtime** — nothing
is hardcoded, so an object added later is automatically in scope — then builds an
hour × metric table for yesterday and today.

```bash
pip install -e ".[notebook]"

# One-time: register the venv as a kernel Jupyter can see.
# Needed because Anaconda ships its own Jupyter and its own Python, and that
# Python has none of this project's packages. Without this the notebook fails
# with a bare `ModuleNotFoundError: No module named 'psycopg'`, which points at
# a missing package when the real problem is the wrong interpreter.
.venv/bin/python -m ipykernel install --user --name ecowitt \
    --display-name "Python (ecowitt)"

./infra/tunnel.sh          # in another terminal, leave running
jupyter lab notebooks/explore.ipynb
```

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
