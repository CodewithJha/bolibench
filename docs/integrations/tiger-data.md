# Tiger Data (TimescaleDB) export (optional)

Two things, both explicit and optional:

1. Metrics: one row per case artifact in a TimescaleDB hypertable, for pass rate and duration per agent
   per day.
2. Similar-failure search for triage (`--failures`, `--similar`): non-passing cases are embedded with a
   local open-weight model (EmbeddingGemma via Ollama) and stored with pgvector next to a full-text
   index; given a new failure, a hybrid (vector + keyword) search lists past failures that look like it.

What is Tiger-specific: the hypertable (TimescaleDB) and the pgvector + tsvector hybrid search, all
in one Postgres service. The rest is plain Postgres. The local JSON artifacts stay the source of truth:
export only runs when you invoke it, reads the run directory, and never modifies it. For full artifacts
and per-case history see [MongoDB Atlas](mongodb-atlas.md).

## Install and run

```sh
uv pip install 'bolibench[tiger]'       # or: uv run --with 'psycopg[binary]' python -m bolibench.export_tiger ...
export TIGER_DATABASE_URL='postgres://tsdbadmin:<password>@<host>:<port>/tsdb?sslmode=require'

python -m bolibench.export_tiger --dry-run runs/<UTC timestamp>-<random>   # print DDL, INSERT and rows, no network
python -m bolibench.export_tiger runs/<UTC timestamp>-<random> [...]
python -m bolibench.export_tiger --report                                   # pass rate + median duration per model per UTC day
python -m bolibench.export_tiger --failures runs/<run> [...]                # also embed + index non-passing cases
python -m bolibench.export_tiger --similar runs/<run>/<case_id>.json [--k 5] # past failures like this one
```

- `TIGER_DATABASE_URL` is read from the environment only and never printed; driver errors are shown
  with the URL and any credentials replaced by `<redacted>`. The service URL is in the credentials file
  Tiger Cloud gives you at service creation, or `tiger db uri` (add the password).
- Driver: psycopg 3 (`psycopg[binary]` bundles libpq; use plain `psycopg` with a system libpq).
- All values are sent as bound parameters (`%(name)s`); no SQL is built from artifact data.
- A run directory must be complete (artifacts valid, `summary.json` agreeing with them), else nothing is
  exported (exit 2). Exit codes: 0 ok, 1 database error, 2 input/config error.

## Schema

```sql
CREATE TABLE IF NOT EXISTS bolibench_case_results (
    time timestamptz NOT NULL,          -- case started_at
    run_id text NOT NULL,               -- run directory name
    config_id text NOT NULL,            -- from summary.json
    case_id text NOT NULL,
    model text,                         -- adapter.self_reported_agent.name; NULL when not reported
    agent_version text,                 -- adapter.self_reported_agent.version; NULL when not reported
    verdict text NOT NULL,
    passed boolean NOT NULL,
    n_tool_calls integer,               -- NULL when the adapter does not expose tool calls
    n_rejected integer,
    duration_ms double precision,       -- finished_at - started_at; NULL when finished_at is missing
    PRIMARY KEY (time, run_id, case_id)
);
SELECT create_hypertable('bolibench_case_results', by_range('time'), if_not_exists => TRUE);
```

Both statements run on every export and are no-ops once the table exists. `create_hypertable` with
`by_range` needs TimescaleDB 2.13+ (every current Tiger Cloud service). Tiger's docs now prefer
`CREATE TABLE ... WITH (tsdb.hypertable)` for new tables; `create_hypertable(..., if_not_exists => TRUE)`
is used here because it is still supported and is idempotent for an existing table.

Inserts use `ON CONFLICT DO NOTHING` on the primary key, so re-exporting a run inserts nothing.
Renaming a run directory changes its `run_id`, so don't.

`model` is the agent's own unverified claim. Runs whose agent reports no identity have `model` NULL and
are distinguished only by `config_id`; two runs of different agent code behind the same URL share a
`config_id` (see README, "Artifacts").

## Report

```sql
SELECT time_bucket('1 day', time) AS day, coalesce(model, '(unreported)') AS model, config_id,
    count(*) AS cases, avg(passed::int) AS pass_rate,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS median_duration_ms
FROM bolibench_case_results GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
```

A plain query, no continuous aggregate: at benchmark volumes it is instant. Example line:

```
2026-10-17  (unreported)  32978a20f0c64924  24 cases  38% pass  median 9437 ms
```

## Similar-failure search

A triage aid: when a case fails, see which past failures look like it, so you can tell a new failure
mode from a recurring one. It is not a verdict and not evidence; the evaluator never uses it, and
nothing is written back to the artifacts.

### What is embedded

For every non-passing case (`fail`, `error`, `inconclusive`) with `--failures`, and for the query case
with `--similar`, this text, built only from the artifact:

```
user: <turns[i].user_input>
agent: <turns[i].agent_reply>          (one pair per recorded turn)
checks not passed: <metric> (<verdict>), ...   or "none"
categories: <classification categories, sorted>   or "none"
execution error: <run.execution_error>          (only when set)
```

No adapter config, URLs, tool arguments or initial state. For `embeddinggemma` the model card's
symmetric similarity prompt `task: sentence similarity | query: ` is prepended to every input (stored
and query alike); it is not part of the stored `text`.

### Embeddings

Ollama's `POST http://127.0.0.1:11434/api/embed` only (fixed host, proxies bypassed), stdlib `urllib`,
`keep_alive: 0` so the model unloads right after the call. Default model `embeddinggemma` (Google's
300M open-weight EmbeddingGemma, 768 dimensions, 100+ languages); `--embed-model` picks another
Ollama model, which must also return 768 values. If Ollama is not running, the model is not pulled,
or the size is wrong, the command fails (exit 2) before connecting to the database; there is no
fallback embedding.

```sh
ollama pull embeddinggemma    # once, ~620 MB
```

### Table

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS bolibench_failures (
    run_id text NOT NULL,
    case_id text NOT NULL,
    time timestamptz NOT NULL,
    verdict text NOT NULL,
    categories text[] NOT NULL,
    text text NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
    embedding_model text NOT NULL,
    embedding vector(768) NOT NULL,
    PRIMARY KEY (run_id, case_id)
);
CREATE INDEX IF NOT EXISTS bolibench_failures_tsv ON bolibench_failures USING gin (tsv);
CREATE INDEX IF NOT EXISTS bolibench_failures_embedding ON bolibench_failures USING hnsw (embedding vector_cosine_ops);
```

A plain table, not a hypertable: it is searched by similarity, not by time range. The `simple` text
configuration (no stemming, no stop words) because utterances are Hindi, Awadhi and code-switched
Hinglish, which no built-in stemmer handles. Inserts are `ON CONFLICT DO NOTHING`; re-embedding on
re-export is wasted work but writes nothing. Vector search only compares rows with the same
`embedding_model`.

### Hybrid search and fusion

`--similar <run_dir>/<case_id>.json` embeds the query case, then runs two parameterized queries, each
returning up to 20 candidates and excluding the query case itself:

- vector: `ORDER BY embedding <=> query_embedding` (cosine distance)
- keyword: the query text's words, OR-ed, `WHERE tsv @@ q ORDER BY ts_rank_cd(tsv, q) DESC`

The two rankings are merged with reciprocal rank fusion, `score = sum of 1 / (60 + rank)` over the
lists a failure appears in (rank from 1). RRF uses only rank positions, so cosine distances and
`ts_rank_cd` values never need to be put on one scale. Output format, best first (illustrative):

```
0.0325  20261017T064824Z-6ec70da2/ambiguous-previous-order  ambiguity_handling
```

The maximum score is 2/61 ≈ 0.0328 (first in both lists).

### Limits

- Tiny dataset: 15 failures across the two qwen3-8b runs. For one query, the top five EmbeddingGemma
  cosine similarities were all between 0.90 and 0.93, so the ordering is a hint, not a measurement.
- Similar text is not the same root cause. Read the artifacts before concluding anything.
- Tokenizing Devanagari depends on the database's locale (it works on a UTF-8 locale).
- Tiger Cloud also offers `pg_textsearch` (BM25) and `pgvectorscale`, which its own hybrid-search
  guide uses; plain `tsvector` and pgvector HNSW are used here because they are available on any
  Postgres with pgvector and are plenty at this size.

## Tiger Cloud setup, verification, cleanup

1. Create a service in Tiger Console (or `tiger service create`) and save the credentials file.
   pgvector is available on Tiger Cloud; the exporter runs `CREATE EXTENSION IF NOT EXISTS vector`.
2. `export TIGER_DATABASE_URL=...`, then dry-run, export one run, export it again (expect
   `0 inserted`), and run `--report`. `SELECT * FROM timescaledb_information.hypertables;` lists the table.
3. Failures: `ollama pull embeddinggemma`, then `--failures` on two runs and `--similar` on one failed
   artifact. `SELECT case_id, verdict, categories FROM bolibench_failures;` shows what was indexed.
4. Live test (creates and drops a `bolibench_live_test_<random>` schema; the pgvector part uses fake
   embeddings so it needs no Ollama):
   `BOLIBENCH_LIVE=1 uv run --with 'psycopg[binary]' pytest tests/test_export.py -k live_tiger`.
   `BOLIBENCH_LIVE=1 uv run pytest tests/test_export.py -k live_ollama` checks a real embedding call.
5. Cleanup: `DROP TABLE bolibench_case_results, bolibench_failures;`, or delete the service if it was
   only for this. `ollama rm embeddinggemma` removes the model.
