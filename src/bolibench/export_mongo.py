"""Optional, explicit export of bolibench run directories to MongoDB (e.g. Atlas). See docs/integrations/mongodb-atlas.md."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from bolibench.export import ExportError, Run, case_record, dump, load_run, redact, require_driver, require_env
from bolibench.store import SuiteError, load_suite

INDEXES: dict[str, list[list[tuple[str, int]]]] = {
    "case_results": [[("case_id", 1), ("started_at", -1)], [("run_id", 1)], [("verdict", 1)]],
    "runs": [[("config_id", 1)]],
}
FIELDS = ("run_id", "config_id", "case_id", "verdict", "passed", "categories", "adapter", "agent", "started_at", "finished_at", "duration_ms", "n_tool_calls", "n_rejected", "artifact_sha256")


def run_doc(run: Run) -> dict[str, Any]:
    return {
        "_id": run.run_id,
        "config_id": run.summary.config_id,
        "started_at": min((c.artifact.run.started_at for c in run.cases), default=None),
        "summary": run.summary.model_dump(mode="json"),
    }


def case_docs(run: Run, tags: dict[str, list[str]]) -> list[dict[str, Any]]:
    docs = []
    for case in run.cases:
        rec = case_record(run, case)
        doc = {"_id": rec["key"], **{k: rec[k] for k in FIELDS}, "tags": tags.get(rec["case_id"])}
        docs.append(doc | {"artifact": json.loads(case.raw)})
    return docs


def export(db: Any, runs: list[dict[str, Any]], cases: list[dict[str, Any]]) -> int:
    """Create indexes, then upsert by `_id` (re-export replaces a document with itself). Returns new documents."""
    for name, keys in INDEXES.items():
        for key in keys:
            db[name].create_index(key)
    new = 0
    for name, docs in (("runs", runs), ("case_results", cases)):
        for doc in docs:
            new += db[name].replace_one({"_id": doc["_id"]}, doc, upsert=True).upserted_id is not None
    return new


def pass_rate_pipeline(config_id: str | None) -> list[dict[str, Any]]:
    match = [{"$match": {"config_id": config_id}}] if config_id else []
    return match + [
        {"$sort": {"started_at": 1}},
        {"$group": {
            "_id": "$case_id",
            "runs": {"$sum": 1},
            "passes": {"$sum": {"$cond": ["$passed", 1, 0]}},
            "last_verdict": {"$last": "$verdict"},
            "last_started_at": {"$last": "$started_at"},
        }},
        {"$sort": {"_id": 1}},
    ]


def report(db: Any, config_id: str | None) -> None:
    for r in db["case_results"].aggregate(pass_rate_pipeline(config_id)):
        print(f"{r['passes']}/{r['runs']} pass ({r['passes'] / r['runs']:.0%})  last {r['last_verdict']:<12} {r['_id']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bolibench.export_mongo", description=__doc__)
    parser.add_argument("run_dirs", nargs="*", type=Path, help="bolibench run directories (<UTC timestamp>-<random>)")
    parser.add_argument("--suite", type=Path, help="copy case tags from this suite (artifacts do not record tags)")
    parser.add_argument("--dry-run", action="store_true", help="print the documents (or pipeline) instead of connecting")
    parser.add_argument("--report", action="store_true", help="print per-case pass rate across exported runs")
    parser.add_argument("--config-id", help="--report: only runs with this config_id")
    args = parser.parse_args(argv)
    if bool(args.run_dirs) == args.report:
        parser.error("give run directories or --report")
    try:
        runs = [load_run(d) for d in args.run_dirs]
        tags = {c.id: c.tags for c in load_suite(args.suite)} if args.suite else {}
        run_docs = [run_doc(r) for r in runs]
        docs = [d for r in runs for d in case_docs(r, tags)]
        if args.dry_run:
            if args.report:
                print(dump(pass_rate_pipeline(args.config_id)))
            for name, batch in (("runs", run_docs), ("case_results", docs)):
                for doc in batch:
                    print(dump({"collection": name, "document": doc}))
            return 0
        uri = require_env("MONGODB_URI")
        pymongo = require_driver("pymongo", "mongo", "pymongo")
    except (ExportError, SuiteError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    from pymongo.server_api import ServerApi

    try:
        with pymongo.MongoClient(uri, server_api=ServerApi("1"), appname="bolibench") as client:
            db = client[os.environ.get("MONGODB_DB") or "bolibench"]
            if args.report:
                report(db, args.config_id)
                return 0
            new = export(db, run_docs, docs)
    except pymongo.errors.PyMongoError as e:
        print(f"error: {redact(str(e), uri)}", file=sys.stderr)
        return 1
    print(f"{len(runs)} runs, {len(docs)} case results: {new} new, {len(run_docs) + len(docs) - new} already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
