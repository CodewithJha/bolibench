# MongoDB Atlas export (optional)

Copies finished run directories into MongoDB so per-case history can be queried across runs. The local
JSON artifacts stay the source of truth: export only runs when you invoke it, reads the run directory,
and never modifies it.

Atlas vs. [Tiger Data](tiger-data.md): Atlas stores each full artifact as a document (transcript, tool
calls, checks, classifications), so you can query any field of past runs. Tiger stores one numeric row
per case for time-series trends. Neither adds scoring; both only hold what the artifacts already say.

## Install and run

```sh
uv pip install 'bolibench[mongo]'       # or: uv run --with pymongo python -m bolibench.export_mongo ...
export MONGODB_URI='mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority'
export MONGODB_DB=bolibench             # optional, default "bolibench"

python -m bolibench.export_mongo --dry-run runs/<UTC timestamp>-<random>   # print documents, no network
python -m bolibench.export_mongo runs/<UTC timestamp>-<random> [...] [--suite suites/orders]
python -m bolibench.export_mongo --report [--config-id <id>]               # per-case pass rate across runs
```

- `MONGODB_URI` is read from the environment only, never from a flag, and is never printed; driver
  errors are shown with the URI and any credentials replaced by `<redacted>`.
- The client uses the Stable API (`ServerApi("1")`), as recommended for Atlas. PyMongo 4.x (4.19 is
  current) includes the DNS support `mongodb+srv://` needs.
- A run directory must be complete: every `<case_id>.json` must validate as an artifact and
  `summary.json` must agree with them. Otherwise nothing is exported (exit 2).
- Exit codes: 0 ok, 1 database error, 2 input/config error (bad run dir, missing env var, missing driver).

## Data model

`runs`, one document per run directory:

| field | value |
| --- | --- |
| `_id` | run directory name, `<UTC timestamp>-<random>` (never a path) |
| `config_id` | from `summary.json` |
| `started_at` | earliest case `started_at` (BSON date) |
| `summary` | `summary.json` as written, including the adapter identities |

`case_results`, one document per case artifact:

| field | value |
| --- | --- |
| `_id` | `<run_id>/<case_id>`, the idempotency key |
| `run_id`, `config_id`, `case_id`, `verdict`, `passed` | denormalized from the artifact and summary |
| `categories` | distinct classification categories, sorted |
| `adapter` | `{name, version}` |
| `agent` | `adapter.self_reported_agent` (`{name, version}`, unverified) or null |
| `started_at`, `finished_at`, `duration_ms` | BSON dates; duration null when `finished_at` is missing |
| `n_tool_calls`, `n_rejected` | null when the adapter does not expose tool calls |
| `artifact_sha256` | sha256 of the artifact file bytes, to check a document against the local file |
| `tags` | case tags from `--suite` at export time, else null; artifacts do not record tags |
| `artifact` | the full artifact JSON, verbatim |

The embedded artifact is copied as written, including `adapter.config` (the agent URL, or the
`--scripts` path exactly as given on the command line). The exporter itself adds no paths.

Writes are `replace_one(..., upsert=True)` by `_id`, so re-exporting a run is a no-op that reports
"already present" rather than a duplicate. Renaming a run directory changes its `run_id`, so don't.

Indexes, created on every export (`create_index` is idempotent):

- `case_results`: `{case_id: 1, started_at: -1}` (history of one case), `{run_id: 1}`, `{verdict: 1}`
- `runs`: `{config_id: 1}`

## Report

`--report` runs one aggregation over `case_results`: optional `$match` on `config_id`, `$sort` by
`started_at`, `$group` by `case_id` (runs, passes, last verdict). `--dry-run --report` prints the
pipeline. Example line:

```
3/4 pass (75%)  last fail         cancel-single-order
```

## Atlas setup, verification, cleanup

1. Create a cluster (the free tier is enough), a database user with `readWrite` on the target database,
   and add your IP to the network access list. Copy the "Drivers / Python" connection string.
2. `export MONGODB_URI=...`, then dry-run, export one run, export it again (expect `0 new`), and run
   `--report`. In Atlas Data Explorer, check `bolibench.case_results` and its indexes.
3. Live test (creates and drops a `bolibench_live_test_<random>` database):
   `BOLIBENCH_LIVE=1 uv run --with pymongo pytest tests/test_export.py -k live_mongo`
4. Cleanup: drop the `bolibench` database (or the collections) in Data Explorer or with
   `db.dropDatabase()` in `mongosh`; delete the database user and IP entry if they were only for this.
