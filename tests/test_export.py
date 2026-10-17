import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

from bolibench import export_mongo, export_tiger
from bolibench.adapters import Fail, FakeAgentAdapter, Reply, Step
from bolibench.cli import SCRIPT
from bolibench.evaluate import evaluate
from bolibench.export import CaseArtifact, ExportError, case_record, load_run, redact
from bolibench.models import AdapterInfo, AgentIdentity, Artifact
from bolibench.runner import new_run_dir, run_case, write_artifact, write_summary
from bolibench.store import load_case

ROOT = Path(__file__).parent.parent
SUITE = ROOT / "suites" / "orders"
SECRET = "s3cret-pw"
LIVE = os.environ.get("BOLIBENCH_LIVE") == "1"


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """One real run: a scripted pass, a self-identified agent that fails, and an adapter error."""
    scripted = AdapterInfo(name="fake-scripted", version="1", config={"script": "examples/scripts/ambiguous-previous-order.json"})
    agent = AdapterInfo(name="webhook", version="1", config={"agent_url": "http://127.0.0.1:8000/turn"}, self_reported_agent=AgentIdentity(name="qwen3-8b", version="v2"))
    plans: dict[str, tuple[AdapterInfo, list[list[Step]]]] = {
        "ambiguous-previous-order": (scripted, SCRIPT.validate_json((ROOT / "examples/scripts/ambiguous-previous-order.json").read_bytes())),
        "cancel-single-order": (agent, [[Reply(text="ठीक है")]]),
        "forbidden-bulk-cancel": (agent, [[Fail(reason="agent crashed")]]),
    }
    directory = new_run_dir(tmp_path / "runs")
    for case_id, (info, script) in plans.items():
        case = load_case(SUITE / f"{case_id}.json")
        script = (script * len(case.turns))[: len(case.turns)]
        record = run_case(case, FakeAgentAdapter(script, info=info))
        write_artifact(directory, Artifact(case_id=case.id, run=record, evaluation=evaluate(case, record)))
    write_summary(directory)
    return directory


def records(run_dir: Path) -> dict[str, dict[str, Any]]:
    run = load_run(run_dir)
    return {c.artifact.case_id: case_record(run, c) for c in run.cases}


def test_records_are_shaped_from_the_artifacts(run_dir: Path) -> None:
    run = load_run(run_dir)
    assert run.run_id == run_dir.name and run.summary.config_id and len(run.cases) == 3
    recs = records(run_dir)
    ok, failed, errored = recs["ambiguous-previous-order"], recs["cancel-single-order"], recs["forbidden-bulk-cancel"]
    assert (ok["verdict"], ok["passed"], ok["n_tool_calls"], ok["n_rejected"], ok["agent"]) == ("pass", True, 3, 0, None)
    assert ok["key"] == f"{run_dir.name}/ambiguous-previous-order" and ok["run_id"] == run_dir.name
    assert isinstance(ok["duration_ms"], float) and ok["duration_ms"] >= 0
    assert (failed["verdict"], failed["passed"], failed["agent"]) == ("fail", False, {"name": "qwen3-8b", "version": "v2"})
    assert failed["categories"] and failed["categories"] == sorted(set(failed["categories"]))
    assert errored["verdict"] == "error" and errored["adapter"] == {"name": "webhook", "version": "1"}
    assert ok["artifact_sha256"] == hashlib.sha256((run_dir / "ambiguous-previous-order.json").read_bytes()).hexdigest()


def test_unobserved_metrics_are_null_not_zero(run_dir: Path) -> None:
    run = load_run(run_dir)
    a = run.cases[0].artifact
    hidden = a.model_copy(update={"run": a.run.model_copy(update={"finished_at": None, "exposes_tool_calls": False, "tool_calls": []})})
    rec = case_record(run, CaseArtifact(hidden, hidden.model_dump_json().encode()))
    assert (rec["duration_ms"], rec["n_tool_calls"], rec["n_rejected"]) == (None, None, None)


def test_ids_and_documents_are_stable_and_path_free(run_dir: Path, tmp_path: Path) -> None:
    assert records(run_dir) == records(run_dir)
    run = load_run(run_dir)
    docs = [export_mongo.run_doc(run), *export_mongo.case_docs(run, {})]
    assert docs == [export_mongo.run_doc(load_run(run_dir)), *export_mongo.case_docs(load_run(run_dir), {})]
    text = json.dumps(docs, default=str) + json.dumps(export_tiger.rows(run), default=str)
    assert str(tmp_path) not in text and str(ROOT) not in text
    case = docs[1]
    assert case["artifact"] == json.loads((run_dir / f"{case['case_id']}.json").read_bytes())  # full artifact, verbatim


@pytest.mark.parametrize("damage", ["bad_json", "bad_schema", "no_summary", "summary_mismatch", "renamed"])
def test_malformed_run_dirs_are_rejected(run_dir: Path, tmp_path: Path, damage: str) -> None:
    broken = shutil.copytree(run_dir, tmp_path / "copy" / run_dir.name)
    artifact = broken / "cancel-single-order.json"
    if damage == "bad_json":
        artifact.write_text("{", encoding="utf-8")
    elif damage == "bad_schema":
        artifact.write_text(json.dumps(json.loads(artifact.read_text(encoding="utf-8")) | {"schema_version": 2}), encoding="utf-8")
    elif damage == "no_summary":
        (broken / "summary.json").unlink()
    elif damage == "summary_mismatch":
        summary = json.loads((broken / "summary.json").read_text(encoding="utf-8"))
        summary["cases"]["cancel-single-order"] = "pass"
        (broken / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    else:
        artifact.rename(broken / "other-case.json")
    with pytest.raises(ExportError):
        load_run(broken)
    assert export_mongo.main(["--dry-run", str(broken)]) == 2 and export_tiger.main(["--dry-run", str(broken)]) == 2


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.indexes: list[list[tuple[str, int]]] = []

    def create_index(self, keys: list[tuple[str, int]]) -> None:
        self.indexes.append(keys)

    def replace_one(self, query: dict[str, Any], doc: dict[str, Any], upsert: bool) -> Any:
        assert upsert and query == {"_id": doc["_id"]}
        new = doc["_id"] not in self.docs
        self.docs[doc["_id"]] = doc
        return type("Result", (), {"upserted_id": doc["_id"] if new else None})()

    def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.pipeline = pipeline
        return [{"_id": "cancel-single-order", "runs": 4, "passes": 3, "last_verdict": "fail", "last_started_at": None}]


def test_mongo_export_upserts_idempotently_and_creates_indexes(run_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db: dict[str, FakeCollection] = {"runs": FakeCollection(), "case_results": FakeCollection()}
    run = load_run(run_dir)
    batch = ([export_mongo.run_doc(run)], export_mongo.case_docs(run, {"cancel-single-order": ["hinglish"]}))
    assert export_mongo.export(db, *batch) == 4
    assert export_mongo.export(db, *batch) == 0
    assert set(db["runs"].docs) == {run_dir.name} and len(db["case_results"].docs) == 3
    assert db["case_results"].indexes[:3] == [[("case_id", 1), ("started_at", -1)], [("run_id", 1)], [("verdict", 1)]]
    assert db["runs"].indexes[0] == [("config_id", 1)]
    assert db["case_results"].docs[f"{run_dir.name}/cancel-single-order"]["tags"] == ["hinglish"]
    export_mongo.report(db, "abc")
    assert db["case_results"].pipeline[0] == {"$match": {"config_id": "abc"}}
    assert "3/4 pass (75%)  last fail" in capsys.readouterr().out


class FakeConn:
    def __init__(self, results: dict[str, list[tuple[Any, ...]]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.keys: set[tuple[Any, ...]] = set()
        self.commits = 0
        self.results = results or {}

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((sql, params))
        rowcount = 0
        if params is not None and "time" in params:
            key = (sql, params["time"], params["run_id"], params["case_id"])
            rowcount = int(key not in self.keys)
            self.keys.add(key)
        rows = self.results.get(sql, [])
        return type("Cursor", (), {"rowcount": rowcount, "fetchall": lambda _: rows})()

    def commit(self) -> None:
        self.commits += 1

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, *_: object) -> None:
        pass


def test_tiger_export_is_parameterized_and_idempotent(run_dir: Path) -> None:
    conn = FakeConn()
    batch = export_tiger.rows(load_run(run_dir))
    assert export_tiger.export(conn, batch) == 3 and export_tiger.export(conn, batch) == 0 and conn.commits == 2
    sqls = [sql for sql, _ in conn.calls]
    assert "create_hypertable('bolibench_case_results', by_range('time'), if_not_exists => TRUE)" in sqls[1]
    inserts = [(sql, p) for sql, p in conn.calls if p is not None]
    assert len(inserts) == 6 and all(sql == export_tiger.INSERT for sql, _ in inserts)
    assert all(run_dir.name not in sql and "cancel-single-order" not in sql for sql in sqls)
    assert all(f"%({k})s" in export_tiger.INSERT for k in batch[0])
    row = next(p for _, p in inserts if p and p["case_id"] == "cancel-single-order")
    assert (row["model"], row["agent_version"], row["passed"], row["verdict"]) == ("qwen3-8b", "v2", False, "fail")


def test_dry_runs_need_no_env_or_driver(run_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("TIGER_DATABASE_URL", raising=False)
    monkeypatch.setitem(sys.modules, "pymongo", None)
    monkeypatch.setitem(sys.modules, "psycopg", None)
    assert export_mongo.main(["--dry-run", "--suite", str(SUITE), str(run_dir)]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["collection"] for line in lines] == ["runs"] + ["case_results"] * 3
    assert lines[1]["document"]["tags"] == load_case(SUITE / "ambiguous-previous-order.json").tags
    assert export_tiger.main(["--dry-run", str(run_dir)]) == 0
    out = capsys.readouterr().out
    assert "create_hypertable" in out and "ON CONFLICT DO NOTHING" in out and out.count(f'"run_id": "{run_dir.name}"') == 3
    assert export_tiger.main(["--dry-run", "--report"]) == 0 and "time_bucket('1 day', time)" in capsys.readouterr().out


@pytest.mark.parametrize(("module", "env"), [(export_mongo, "MONGODB_URI"), (export_tiger, "TIGER_DATABASE_URL")])
def test_missing_env_fails_before_driver_import(run_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], module: Any, env: str) -> None:
    monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(module, "require_driver", lambda *_: pytest.fail("driver imported before the env check"))
    assert module.main([str(run_dir)]) == 2
    assert f"{env} is not set" in capsys.readouterr().err


@pytest.mark.parametrize(("module", "env", "driver", "extra"), [
    (export_mongo, "MONGODB_URI", "pymongo", "bolibench[mongo]"),
    (export_tiger, "TIGER_DATABASE_URL", "psycopg", "bolibench[tiger]"),
])
def test_missing_driver_is_a_clear_error(run_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], module: Any, env: str, driver: str, extra: str) -> None:
    monkeypatch.setenv(env, f"scheme://user:{SECRET}@db.example/x")
    monkeypatch.setitem(sys.modules, driver, None)
    assert module.main([str(run_dir)]) == 2
    out = capsys.readouterr()
    assert f"{driver} is not installed" in out.err and extra in out.err and SECRET not in out.err + out.out


def test_redact_hides_connection_strings() -> None:
    uri = f"mongodb+srv://bench:{SECRET}@cluster0.example.mongodb.net/?retryWrites=true"
    assert SECRET not in redact(f"bad uri {uri}", uri)
    assert SECRET not in redact(f"postgres://tsdbadmin:{SECRET}@host:5432/tsdb failed", "other")
    assert SECRET not in redact(f"host=x password={SECRET} dbname=tsdb", "other")


def test_driver_errors_are_redacted(run_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Needs the drivers (`uv run --with pymongo --with 'psycopg[binary]'`); no network: bad URI / refused localhost port."""
    pytest.importorskip("pymongo")
    pytest.importorskip("psycopg")
    monkeypatch.setenv("MONGODB_URI", f"mongodb://bench:{SECRET}@")
    assert export_mongo.main([str(run_dir)]) == 1
    monkeypatch.setenv("TIGER_DATABASE_URL", f"postgresql://bench:{SECRET}@127.0.0.1:1/tsdb?connect_timeout=2")
    assert export_tiger.main([str(run_dir)]) == 1
    out = capsys.readouterr()
    assert out.err.count("error: ") == 2 and SECRET not in out.err + out.out


def fake_embed(texts: list[str], model: str) -> list[list[float]]:
    return [[float(len(t) % 7), 1.0] + [0.0] * (export_tiger.DIM - 2) for t in texts]


def test_failure_text_is_exactly_turns_checks_categories_and_error(run_dir: Path) -> None:
    failures = {f["case_id"]: f for f in export_tiger.failure_rows(load_run(run_dir))}
    assert set(failures) == {"cancel-single-order", "forbidden-bulk-cancel"}  # passes are not failures
    failed = failures["cancel-single-order"]
    case = load_case(SUITE / "cancel-single-order.json")
    lines = failed["text"].split("\n")
    assert lines[0] == f"user: {case.turns[0]}" and lines[1] == "agent: ठीक है"
    assert lines[-2].startswith("checks not passed: ") and "(fail)" in lines[-2]
    assert lines[-1] == "categories: " + ", ".join(failed["categories"])
    assert failures["forbidden-bulk-cancel"]["text"].endswith("execution error: AdapterError: agent crashed")
    assert set(failed) == {"time", "run_id", "case_id", "verdict", "categories", "text"}


def test_rrf_sums_reciprocal_ranks() -> None:
    a, b, c = ("r", "a"), ("r", "b"), ("r", "c")
    scores = export_tiger.rrf([a, b], [b, c])
    assert scores == {a: 1 / 61, b: 1 / 62 + 1 / 61, c: 1 / 62}
    assert sorted(scores, key=lambda key: -scores[key]) == [b, a, c]


def test_failures_are_indexed_idempotently_with_parameterized_sql(run_dir: Path) -> None:
    batch = [r | {"embedding_model": "fake", "embedding": "[1,0]"} for r in export_tiger.failure_rows(load_run(run_dir))]
    conn = FakeConn()
    assert export_tiger.index_failures(conn, batch) == 2 and export_tiger.index_failures(conn, batch) == 0
    sqls = [sql for sql, _ in conn.calls]
    assert sqls[0] == "CREATE EXTENSION IF NOT EXISTS vector" and "embedding vector(768)" in sqls[1]
    assert "GENERATED ALWAYS AS (to_tsvector('simple', text))" in sqls[1] and "USING hnsw" in sqls[3]
    inserts = [p for sql, p in conn.calls if sql == export_tiger.FAILURE_INSERT]
    assert len(inserts) == 4 and inserts[0] is not None and inserts[0]["embedding"] == "[1,0]"
    assert all(run_dir.name not in sql and "ठीक" not in sql for sql in sqls)


def test_similar_fuses_vector_and_text_rankings(run_dir: Path) -> None:
    query = export_tiger.load_query(run_dir / "cancel-single-order.json") | {"embedding_model": "m", "embedding": "[1,0]"}
    conn = FakeConn({
        export_tiger.SIMILAR_VECTOR: [("r1", "a", ["entity_resolution"]), ("r2", "b", [])],
        export_tiger.SIMILAR_TEXT: [("r2", "b", []), ("r3", "c", ["ambiguity_handling"])],
    })
    assert export_tiger.similar(conn, query, k=2) == [("r2", "b", [], 1 / 62 + 1 / 61), ("r1", "a", ["entity_resolution"], 1 / 61)]
    (vector_sql, vector_params), (text_sql, text_params) = conn.calls
    assert (vector_sql, text_sql) == (export_tiger.SIMILAR_VECTOR, export_tiger.SIMILAR_TEXT)
    own = {"run_id": run_dir.name, "case_id": "cancel-single-order", "pool": export_tiger.POOL}
    assert vector_params == own | {"embedding": "[1,0]", "embedding_model": "m"}
    assert text_params == own | {"text": query["text"]}


class FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode()

    def read(self, *_: Any) -> bytes:
        return self.body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        pass


def test_ollama_embed_request_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import urllib.error

    sent: list[Any] = []

    def ok(request: Any, timeout: float) -> FakeResponse:
        sent.append(request)
        return FakeResponse({"embeddings": [[0.5] * export_tiger.DIM]})

    monkeypatch.setattr(export_tiger.OPENER, "open", ok)
    assert export_tiger.ollama_embed(["user: x"], "embeddinggemma") == [[0.5] * export_tiger.DIM]
    assert sent[0].full_url == "http://127.0.0.1:11434/api/embed"
    assert json.loads(sent[0].data) == {"model": "embeddinggemma", "input": ["task: sentence similarity | query: user: x"], "keep_alive": 0}

    def missing_model(request: Any, timeout: float) -> Any:
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error":"model \\"nope\\" not found, try pulling it first"}'))  # type: ignore[arg-type]

    monkeypatch.setattr(export_tiger.OPENER, "open", missing_model)
    with pytest.raises(ExportError, match=r"HTTP 404.*not found.*ollama pull nope"):
        export_tiger.ollama_embed(["x"], "nope")

    def no_ollama(request: Any, timeout: float) -> Any:
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr(export_tiger.OPENER, "open", no_ollama)
    with pytest.raises(ExportError, match="not reachable.*ollama serve"):
        export_tiger.ollama_embed(["x"], "embeddinggemma")

    monkeypatch.setattr(export_tiger.OPENER, "open", lambda request, timeout: FakeResponse({"embeddings": [[0.1] * 384]}))
    with pytest.raises(ExportError, match="need 1 of 768"):
        export_tiger.ollama_embed(["x"], "all-minilm")


def fake_psycopg(conn: FakeConn) -> Any:
    return type("psycopg", (), {"connect": staticmethod(lambda *_, **__: conn), "Error": type("Error", (Exception,), {})})


def test_cli_failures_and_similar_offline(run_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("TIGER_DATABASE_URL", f"postgres://u:{SECRET}@db.example/tsdb")
    monkeypatch.setattr(export_tiger, "ollama_embed", fake_embed)
    conn = FakeConn({export_tiger.SIMILAR_VECTOR: [("r1", "a", ["entity_resolution"])]})
    monkeypatch.setattr(export_tiger, "require_driver", lambda *_: fake_psycopg(conn))
    assert export_tiger.main(["--failures", str(run_dir)]) == 0
    assert capsys.readouterr().out.splitlines()[1] == "2 failures: 2 indexed, 0 already present"
    assert export_tiger.main(["--similar", str(run_dir / "cancel-single-order.json"), "--k", "3"]) == 0
    assert capsys.readouterr().out == f"{1 / 61:.4f}  r1/a  entity_resolution\n"


def test_cli_ollama_failure_stops_before_connecting(run_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import urllib.error

    monkeypatch.setenv("TIGER_DATABASE_URL", "postgres://db.example/tsdb")
    monkeypatch.setattr(export_tiger.OPENER, "open", lambda *_, **__: (_ for _ in ()).throw(urllib.error.URLError("refused")))
    monkeypatch.setattr(export_tiger, "require_driver", lambda *_: type("psycopg", (), {"connect": lambda *_: pytest.fail("connected")}))
    assert export_tiger.main(["--failures", str(run_dir)]) == 2
    assert "ollama is not reachable" in capsys.readouterr().err


def test_failure_dry_runs_print_text_without_embedding(run_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert export_tiger.main(["--dry-run", "--failures", str(run_dir)]) == 0
    out = capsys.readouterr().out
    assert "CREATE EXTENSION IF NOT EXISTS vector" in out and "::vector" in out and '"embedding"' not in out
    assert out.count('"text": ') == 2
    assert export_tiger.main(["--dry-run", "--similar", str(run_dir / "cancel-single-order.json")]) == 0
    assert "ORDER BY embedding <=> %(embedding)s::vector" in capsys.readouterr().out
    assert export_tiger.main(["--dry-run", "--similar", str(run_dir / "summary.json")]) == 2


@pytest.mark.skipif(not LIVE, reason="live: set BOLIBENCH_LIVE=1 with Ollama running and embeddinggemma pulled")
def test_live_ollama_embeddings(run_dir: Path) -> None:
    failures = export_tiger.failure_rows(load_run(run_dir))
    vectors = export_tiger.ollama_embed([f["text"] for f in failures], "embeddinggemma")
    assert len(vectors) == 2 and all(len(v) == export_tiger.DIM for v in vectors) and vectors[0] != vectors[1]


@pytest.mark.skipif(not (LIVE and os.environ.get("MONGODB_URI")), reason="live: set BOLIBENCH_LIVE=1 and MONGODB_URI")
def test_live_mongo(run_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    pymongo = pytest.importorskip("pymongo")
    db_name = f"bolibench_live_test_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("MONGODB_DB", db_name)
    try:
        assert export_mongo.main([str(run_dir)]) == 0 and export_mongo.main([str(run_dir)]) == 0
        assert "4 new" in capsys.readouterr().out.splitlines()[0]
        assert export_mongo.main(["--report"]) == 0 and "1/1 pass (100%)" in capsys.readouterr().out
    finally:
        with pymongo.MongoClient(os.environ["MONGODB_URI"]) as client:
            client.drop_database(db_name)


@pytest.mark.skipif(not (LIVE and os.environ.get("TIGER_DATABASE_URL")), reason="live: set BOLIBENCH_LIVE=1 and TIGER_DATABASE_URL")
def test_live_tiger(run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    schema = sql.Identifier(f"bolibench_live_test_{uuid.uuid4().hex[:8]}")
    with psycopg.connect(os.environ["TIGER_DATABASE_URL"], autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        try:
            conn.execute(sql.SQL("SET search_path TO {}, public").format(schema))
            conn.autocommit = False
            batch = export_tiger.rows(load_run(run_dir))
            assert export_tiger.export(conn, batch) == 3 and export_tiger.export(conn, batch) == 0
            [(rate,)] = conn.execute("SELECT avg(passed::int) FROM bolibench_case_results").fetchall()
            assert float(rate) == pytest.approx(1 / 3)
            export_tiger.report(conn)
            monkeypatch.setattr(export_tiger, "ollama_embed", fake_embed)  # pgvector SQL check; real embeddings need Ollama
            failures = export_tiger.with_embeddings(export_tiger.failure_rows(load_run(run_dir)), "fake")
            assert export_tiger.index_failures(conn, failures) == 2 and export_tiger.index_failures(conn, failures) == 0
            [hit] = export_tiger.similar(conn, failures[0], k=5)
            assert (hit[0], hit[1]) == (run_dir.name, failures[1]["case_id"]) and hit[3] > 1 / 61
        finally:
            conn.rollback()
            conn.autocommit = True
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))
