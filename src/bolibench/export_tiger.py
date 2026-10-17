"""Optional, explicit export of bolibench case metrics and failures to Tiger Data (TimescaleDB + pgvector).

See docs/integrations/tiger-data.md.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from bolibench.export import CaseArtifact, ExportError, Run, case_record, dump, load_run, redact, require_driver, require_env

DDL = (
    """CREATE TABLE IF NOT EXISTS bolibench_case_results (
    time timestamptz NOT NULL,
    run_id text NOT NULL,
    config_id text NOT NULL,
    case_id text NOT NULL,
    model text,
    agent_version text,
    verdict text NOT NULL,
    passed boolean NOT NULL,
    n_tool_calls integer,
    n_rejected integer,
    duration_ms double precision,
    PRIMARY KEY (time, run_id, case_id)
)""",
    "SELECT create_hypertable('bolibench_case_results', by_range('time'), if_not_exists => TRUE)",
)
INSERT = """INSERT INTO bolibench_case_results
    (time, run_id, config_id, case_id, model, agent_version, verdict, passed, n_tool_calls, n_rejected, duration_ms)
VALUES (%(time)s, %(run_id)s, %(config_id)s, %(case_id)s, %(model)s, %(agent_version)s, %(verdict)s, %(passed)s,
    %(n_tool_calls)s, %(n_rejected)s, %(duration_ms)s)
ON CONFLICT DO NOTHING"""
REPORT = """SELECT time_bucket('1 day', time) AS day, coalesce(model, '(unreported)') AS model, config_id,
    count(*) AS cases, avg(passed::int) AS pass_rate,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS median_duration_ms
FROM bolibench_case_results
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3"""

DIM = 768  # embeddinggemma's full size; another model must also return 768 values
FAILURE_DDL = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    """CREATE TABLE IF NOT EXISTS bolibench_failures (
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
)""",
    "CREATE INDEX IF NOT EXISTS bolibench_failures_tsv ON bolibench_failures USING gin (tsv)",
    "CREATE INDEX IF NOT EXISTS bolibench_failures_embedding ON bolibench_failures USING hnsw (embedding vector_cosine_ops)",
)
FAILURE_INSERT = """INSERT INTO bolibench_failures (run_id, case_id, time, verdict, categories, text, embedding_model, embedding)
VALUES (%(run_id)s, %(case_id)s, %(time)s, %(verdict)s, %(categories)s, %(text)s, %(embedding_model)s, %(embedding)s::vector)
ON CONFLICT DO NOTHING"""
SIMILAR_VECTOR = """SELECT run_id, case_id, categories FROM bolibench_failures
WHERE embedding_model = %(embedding_model)s AND (run_id, case_id) <> (%(run_id)s, %(case_id)s)
ORDER BY embedding <=> %(embedding)s::vector
LIMIT %(pool)s"""
# plainto_tsquery ANDs every word; OR them so a failure sharing some of the words still ranks
SIMILAR_TEXT = """WITH query AS (SELECT replace(plainto_tsquery('simple', %(text)s)::text, ' & ', ' | ')::tsquery AS q)
SELECT run_id, case_id, categories FROM bolibench_failures, query
WHERE tsv @@ q AND (run_id, case_id) <> (%(run_id)s, %(case_id)s)
ORDER BY ts_rank_cd(tsv, q) DESC
LIMIT %(pool)s"""
POOL = 20  # candidates taken from each ranking before fusion
OLLAMA_EMBED = "http://127.0.0.1:11434/api/embed"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # localhost only: never via a proxy
PROMPTS = {"embeddinggemma": "task: sentence similarity | query: "}  # the model card's symmetric-similarity prompt


def rows(run: Run) -> list[dict[str, Any]]:
    out = []
    for case in run.cases:
        rec = case_record(run, case)
        agent = rec["agent"] or {}
        out.append({
            "time": rec["started_at"],
            **{k: rec[k] for k in ("run_id", "config_id", "case_id")},
            "model": agent.get("name"),  # the agent's self-reported identity; NULL when not reported
            "agent_version": agent.get("version"),
            **{k: rec[k] for k in ("verdict", "passed", "n_tool_calls", "n_rejected", "duration_ms")},
        })
    return out


def export(conn: Any, batch: list[dict[str, Any]]) -> int:
    """Create the hypertable if needed and insert; existing (time, run_id, case_id) rows are kept. Returns rows inserted."""
    for sql in DDL:
        conn.execute(sql)
    inserted = sum(conn.execute(INSERT, row).rowcount for row in batch)
    conn.commit()
    return inserted


def report(conn: Any) -> None:
    for day, model, config_id, cases, pass_rate, median in conn.execute(REPORT).fetchall():
        duration = "n/a" if median is None else f"{median:.0f} ms"
        print(f"{day:%Y-%m-%d}  {model}  {config_id}  {cases} cases  {float(pass_rate):.0%} pass  median {duration}")


def failure_text(case: CaseArtifact) -> str:
    """Exactly what gets embedded and full-text indexed for a case."""
    a = case.artifact
    lines = [f"user: {t.user_input}\nagent: {t.agent_reply}" for t in a.run.turns]
    lines.append("checks not passed: " + (", ".join(f"{c.metric} ({c.verdict})" for c in a.evaluation.checks if c.verdict != "pass") or "none"))
    lines.append("categories: " + (", ".join(sorted({c.category for c in a.evaluation.classifications})) or "none"))
    if a.run.execution_error:
        lines.append(f"execution error: {a.run.execution_error}")
    return "\n".join(lines)


def failure_row(run: Run, case: CaseArtifact) -> dict[str, Any]:
    rec = case_record(run, case)
    return {"time": rec["started_at"], **{k: rec[k] for k in ("run_id", "case_id", "verdict", "categories")}, "text": failure_text(case)}


def failure_rows(run: Run) -> list[dict[str, Any]]:
    return [failure_row(run, c) for c in run.cases if c.artifact.evaluation.verdict != "pass"]


def load_query(path: Path) -> dict[str, Any]:
    run = load_run(path.parent)
    case = next((c for c in run.cases if c.artifact.case_id == path.stem), None)
    if case is None or not path.is_file():
        raise ExportError(f"{path}: not a case artifact (<run_dir>/<case_id>.json)")
    return failure_row(run, case)


def ollama_embed(texts: list[str], model: str) -> list[list[float]]:
    """Embed with a local Ollama model. Errors out rather than returning anything that isn't a real embedding."""
    prefix = PROMPTS.get(model.split(":")[0], "")
    body = json.dumps({"model": model, "input": [prefix + t for t in texts], "keep_alive": 0}).encode()
    request = urllib.request.Request(OLLAMA_EMBED, body, {"Content-Type": "application/json"})
    try:
        with OPENER.open(request, timeout=120) as response:
            vectors: list[list[float]] = json.load(response)["embeddings"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise ExportError(f"ollama could not embed with {model!r} (HTTP {e.code}: {detail}); try `ollama pull {model}`") from e
    except OSError as e:  # URLError, refused, timeout
        raise ExportError(f"ollama is not reachable at {OLLAMA_EMBED} ({e}); start it with `ollama serve`") from e
    if len(vectors) != len(texts) or any(len(v) != DIM for v in vectors):
        raise ExportError(f"{model!r} returned {len(vectors)} vectors of sizes {sorted({len(v) for v in vectors})}; need {len(texts)} of {DIM}")
    return vectors


def with_embeddings(batch: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
    vectors = ollama_embed([r["text"] for r in batch], model) if batch else []
    return [r | {"embedding_model": model, "embedding": "[" + ",".join(map(str, v)) + "]"} for r, v in zip(batch, vectors)]


def index_failures(conn: Any, batch: list[dict[str, Any]]) -> int:
    """Rows must already carry their embedding. Existing (run_id, case_id) rows are kept. Returns rows inserted."""
    for sql in FAILURE_DDL:
        conn.execute(sql)
    inserted = sum(conn.execute(FAILURE_INSERT, row).rowcount for row in batch)
    conn.commit()
    return inserted


def rrf(*rankings: list[tuple[str, str]], k: int = 60) -> dict[tuple[str, str], float]:
    """Reciprocal rank fusion: sum of 1 / (k + rank) over the rankings an item appears in (rank from 1)."""
    scores: dict[tuple[str, str], float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1 / (k + rank)
    return scores


def similar(conn: Any, query: dict[str, Any], k: int) -> list[tuple[str, str, list[str], float]]:
    """Top-k past failures by fused vector (cosine) and full-text rank. The query case itself is excluded."""
    own = {"run_id": query["run_id"], "case_id": query["case_id"], "pool": POOL}
    by_vector = conn.execute(SIMILAR_VECTOR, own | {"embedding": query["embedding"], "embedding_model": query["embedding_model"]}).fetchall()
    by_text = conn.execute(SIMILAR_TEXT, own | {"text": query["text"]}).fetchall()
    categories = {(r[0], r[1]): r[2] for r in by_vector + by_text}
    scores = rrf([(r[0], r[1]) for r in by_vector], [(r[0], r[1]) for r in by_text])
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:k]
    return [(run_id, case_id, categories[run_id, case_id], score) for (run_id, case_id), score in ranked]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bolibench.export_tiger", description=__doc__)
    parser.add_argument("run_dirs", nargs="*", type=Path, help="bolibench run directories (<UTC timestamp>-<random>)")
    parser.add_argument("--dry-run", action="store_true", help="print the SQL and rows instead of connecting")
    parser.add_argument("--report", action="store_true", help="print pass rate and median duration per model per UTC day")
    parser.add_argument("--failures", action="store_true", help="also embed non-passing cases into bolibench_failures (needs local Ollama)")
    parser.add_argument("--similar", type=Path, metavar="ARTIFACT", help="list past failures similar to <run_dir>/<case_id>.json")
    parser.add_argument("--k", type=int, default=5, help="--similar: results to print (default 5)")
    parser.add_argument("--embed-model", default="embeddinggemma", help="Ollama embedding model (default embeddinggemma)")
    args = parser.parse_args(argv)
    if bool(args.run_dirs) + args.report + (args.similar is not None) != 1:
        parser.error("give run directories, --report, or --similar ARTIFACT")
    if args.failures and not args.run_dirs:
        parser.error("--failures needs run directories")
    try:
        runs = [load_run(d) for d in args.run_dirs]
        batch = [row for r in runs for row in rows(r)]
        failures = [row for r in runs for row in failure_rows(r)] if args.failures else []
        queries = [load_query(args.similar)] if args.similar else []
        if args.dry_run:
            sqls: list[str] = []
            if batch:
                sqls += [*DDL, INSERT]
            if failures:
                sqls += [*FAILURE_DDL, FAILURE_INSERT]
            if queries:
                sqls += [SIMILAR_VECTOR, SIMILAR_TEXT]
            if args.report:
                sqls.append(REPORT)
            for sql in sqls:
                print(sql + ";")
            for row in batch + failures + queries:
                print(dump(row))
            return 0
        url = require_env("TIGER_DATABASE_URL")
        psycopg = require_driver("psycopg", "tiger", "psycopg[binary]")
        embedded = with_embeddings(failures + queries, args.embed_model)
    except ExportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(url, application_name="bolibench") as conn:
            if args.report:
                report(conn)
                return 0
            if queries:
                for run_id, case_id, categories, score in similar(conn, embedded[0], args.k):
                    print(f"{score:.4f}  {run_id}/{case_id}  {', '.join(categories) or '-'}")
                return 0
            inserted = export(conn, batch)
            indexed = index_failures(conn, embedded) if failures else 0
    except psycopg.Error as e:
        print(f"error: {redact(str(e), url)}", file=sys.stderr)
        return 1
    print(f"{len(batch)} case rows: {inserted} inserted, {len(batch) - inserted} already present")
    if failures:
        print(f"{len(failures)} failures: {indexed} indexed, {len(failures) - indexed} already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
