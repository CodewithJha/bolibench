"""Durable suite runs on Temporal: one workflow per run, one activity per case.

    python -m bolibench.temporal_run worker
    python -m bolibench.temporal_run start suites/orders --scripts DIR [--output runs]

The run directory is <output>/<workflow id>. A case whose artifact is already there is not run again,
so a crashed worker, a retried activity or a restarted workflow with the same id resumes the run.
Only an unreachable agent is retried; every verdict, `fail` and `error` included, is a result.
See docs/integrations/temporal.md. The pure helpers import without temporalio.
"""

import argparse
import asyncio
import contextlib
import os
import re
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from temporalio import activity, workflow
    from temporalio.client import Client, WorkflowFailureError
    from temporalio.common import RetryPolicy
    from temporalio.envconfig import ClientConfig
    from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
    from temporalio.worker import Worker

    HAVE_TEMPORAL = True
except ModuleNotFoundError:
    HAVE_TEMPORAL = False

with workflow.unsafe.imports_passed_through() if HAVE_TEMPORAL else contextlib.nullcontext():
    from bolibench.adapters import AdapterError, AgentAdapter
    from bolibench.cli import load_cases, load_scripts, scripted_adapter
    from bolibench.evaluate import evaluate
    from bolibench.models import AdapterInfo, Artifact, CaseContext, Summary, TestCase
    from bolibench.runner import run_case, write_artifact, write_summary
    from bolibench.sandbox import OrderSandbox
    from bolibench.store import load_case
    from bolibench.webhook import WebhookAgentAdapter, check_agent_url

RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MARGIN_S = 30.0  # gateway start, evaluation and artifact write on top of the turn deadlines


@dataclass
class CaseInput:
    case_id: str
    case_path: str
    turns: int
    script_path: str = ""  # scripted runs only


@dataclass
class SuiteInput:
    output: str
    cases: list[CaseInput]
    agent_url: str = ""  # "" = scripted
    turn_timeout: float = 30.0
    max_attempts: int = 3


@dataclass
class CaseTask:
    output: str
    run_name: str
    case: CaseInput
    agent_url: str
    turn_timeout: float
    max_attempts: int


@dataclass
class CaseOutcome:
    case_id: str
    verdict: str
    path: str
    reused: bool  # True: an earlier attempt or run had already written this artifact


@dataclass
class SuiteResult:
    cases: list[CaseOutcome]
    summary: str


class AgentUnavailable(Exception):
    """Retryable. Raised instead of AdapterError so run_case does not record it as the case's result."""


def case_timeout(turns: int, turn_timeout: float) -> timedelta:
    """Activity start-to-close timeout: every turn may use its whole deadline."""
    return timedelta(seconds=turns * turn_timeout + MARGIN_S)


def new_run_name() -> str:
    """Same shape as runner.new_run_dir's directory names."""
    return f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


def run_dir_for(output: str, run_name: str) -> Path:
    if not RUN_NAME.match(run_name):
        raise ValueError(f"workflow id {run_name!r} is not a safe directory name ({RUN_NAME.pattern})")
    return Path(output) / run_name


def is_unreachable(e: AdapterError) -> bool:
    """Connection refused or dropped: the agent never answered. Turn deadlines, HTTP error statuses and
    bad replies are the agent's results and are not retried."""
    cause = e.__cause__
    return isinstance(getattr(cause, "reason", cause), (ConnectionRefusedError, ConnectionResetError))


@dataclass
class RetryUnreachable:
    """Lets an unreachable-agent AdapterError escape run_case as AgentUnavailable, except on the final
    attempt, where it is recorded as an `error` verdict exactly like `bolibench run` does."""

    inner: AgentAdapter
    final_attempt: bool

    @property
    def info(self) -> AdapterInfo:
        return self.inner.info

    @property
    def exposes_tool_calls(self) -> bool:
        return self.inner.exposes_tool_calls

    def respond(self, turn: int, utterance: str, context: CaseContext, sandbox: OrderSandbox) -> str:
        try:
            return self.inner.respond(turn, utterance, context, sandbox)
        except AdapterError as e:
            if self.final_attempt or not is_unreachable(e):
                raise
            raise AgentUnavailable(str(e)) from e


AdapterFactory = Callable[[CaseTask, TestCase], contextlib.AbstractContextManager[AgentAdapter]]


@contextlib.contextmanager
def default_adapter(task: CaseTask, case: TestCase) -> Iterator[AgentAdapter]:
    """A fresh adapter per activity attempt; a webhook gateway lives in this worker process for one case."""
    if not task.agent_url:
        yield scripted_adapter(*load_scripts(Path(task.case.script_path), [case])[case.id])
        return
    with WebhookAgentAdapter(task.agent_url, task.turn_timeout) as webhook:
        yield webhook
    for s in webhook.stray_calls:
        print(f"warning: {case.id}: refused {s.status} outside the running turn: {s.reason} (tool {s.tool})", file=sys.stderr)


def completed(run_dir: Path, case_id: str) -> Artifact | None:
    """The artifact an earlier attempt wrote for this case. A partial or foreign file raises: never overwritten."""
    path = run_dir / f"{case_id}.json"
    if not path.exists():
        return None
    artifact = Artifact.model_validate_json(path.read_text(encoding="utf-8"))
    if artifact.case_id != case_id:
        raise ValueError(f"{path} holds case {artifact.case_id!r}")
    return artifact


def run_case_task(task: CaseTask, attempt: int, adapter_for: AdapterFactory = default_adapter) -> CaseOutcome:
    """Run one case into the run dir at most once; an artifact already there is the result."""
    run_dir = run_dir_for(task.output, task.run_name)
    case_id = task.case.case_id
    path = run_dir / f"{case_id}.json"
    if (done := completed(run_dir, case_id)) is not None:
        return CaseOutcome(case_id, done.evaluation.verdict, str(path), reused=True)
    case = load_case(task.case.case_path)
    with adapter_for(task, case) as adapter:
        record = run_case(case, RetryUnreachable(adapter, final_attempt=attempt >= task.max_attempts))
    result = evaluate(case, record)
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        write_artifact(run_dir, Artifact(case_id=case.id, run=record, evaluation=result))
    except FileExistsError:  # a concurrent attempt (after a start-to-close timeout) finished first
        if (done := completed(run_dir, case_id)) is None:
            raise
        return CaseOutcome(case_id, done.evaluation.verdict, str(path), reused=True)
    return CaseOutcome(case_id, result.verdict, str(path), reused=False)


def summary_task(output: str, run_name: str) -> str:
    path = run_dir_for(output, run_name) / "summary.json"
    if path.exists():
        Summary.model_validate_json(path.read_text(encoding="utf-8"))  # a partial file is not "done"
        return str(path)
    return str(write_summary(path.parent))


if HAVE_TEMPORAL:

    class CaseActivities:
        def __init__(self, adapter_for: AdapterFactory = default_adapter) -> None:
            self.adapter_for = adapter_for

        @activity.defn(name="bolibench.run_case")
        def run_case(self, task: CaseTask) -> CaseOutcome:
            try:
                return run_case_task(task, activity.info().attempt, self.adapter_for)
            except AgentUnavailable:
                raise
            except Exception as e:  # a bug or bad input: retrying cannot fix it, and a rerun costs model calls
                raise ApplicationError(f"{type(e).__name__}: {e}", type=type(e).__name__, non_retryable=True) from e

        @activity.defn(name="bolibench.write_summary")
        def write_summary(self, output: str, run_name: str) -> str:
            try:
                return summary_task(output, run_name)
            except Exception as e:  # same: only worker crashes (timeouts) are worth a retry
                raise ApplicationError(f"{type(e).__name__}: {e}", type=type(e).__name__, non_retryable=True) from e

    @workflow.defn(name="BoliBenchSuite")
    class SuiteWorkflow:
        @workflow.run
        async def run(self, suite: SuiteInput) -> SuiteResult:
            run_name = workflow.info().workflow_id
            retry = RetryPolicy(initial_interval=timedelta(seconds=2), maximum_interval=timedelta(minutes=1), maximum_attempts=suite.max_attempts)
            outcomes = []
            for case in suite.cases:  # sequential, like `bolibench run`: a local agent sees one conversation at a time
                task = CaseTask(suite.output, run_name, case, suite.agent_url, suite.turn_timeout, suite.max_attempts)
                outcomes.append(
                    await workflow.execute_activity_method(
                        CaseActivities.run_case,
                        task,
                        start_to_close_timeout=case_timeout(case.turns, suite.turn_timeout),
                        retry_policy=retry,
                    )
                )
            summary = await workflow.execute_activity_method(
                CaseActivities.write_summary,
                args=[suite.output, run_name],
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=retry,
            )
            return SuiteResult(outcomes, summary)

    def make_worker(client: Client, task_queue: str, activities: CaseActivities, pool: ThreadPoolExecutor) -> Worker:
        # one case at a time per worker: turn deadlines assume the agent is not serving other runs
        return Worker(
            client,
            task_queue=task_queue,
            workflows=[SuiteWorkflow],
            activities=[activities.run_case, activities.write_summary],
            activity_executor=pool,
            max_concurrent_activities=1,
        )

    async def start(client: Client, suite: SuiteInput, workflow_id: str, task_queue: str) -> SuiteResult:
        try:
            handle = await client.start_workflow(SuiteWorkflow.run, suite, id=workflow_id, task_queue=task_queue)
        except WorkflowAlreadyStartedError:  # still running: wait for it instead
            handle = client.get_workflow_handle_for(SuiteWorkflow.run, workflow_id)
        return await handle.result()

    async def connect() -> Client:
        # TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, TEMPORAL_API_KEY (enables TLS), or a temporal.toml profile
        config = {"target_host": "localhost:7233", **ClientConfig.load_client_connect_config()}
        try:
            return await Client.connect(**config)
        except RuntimeError as e:  # temporalio raises a bare RuntimeError for an unreachable server
            print(f"error: cannot connect to Temporal at {config['target_host']}: {e}", file=sys.stderr)
            raise SystemExit(2) from None


def suite_input(args: argparse.Namespace) -> SuiteInput:
    """The `bolibench run` input checks; raises ValueError (SuiteError or bad URL) before anything runs."""
    cases = load_cases(args.cases)
    path_of = {c.id: str((args.cases / f"{c.id}.json" if args.cases.is_dir() else args.cases).absolute()) for c in cases}
    if args.agent_url is None:
        scripts = load_scripts(args.scripts.absolute(), cases)
        inputs = [CaseInput(c.id, path_of[c.id], len(c.turns), str(scripts[c.id][0])) for c in cases]
    else:
        check_agent_url(args.agent_url)
        inputs = [CaseInput(c.id, path_of[c.id], len(c.turns)) for c in cases]
    return SuiteInput(str(args.output.absolute()), inputs, args.agent_url or "", args.timeout, args.max_attempts)


def report(result: SuiteResult) -> int:
    for o in result.cases:
        print(f"{o.verdict:<12} {o.case_id}  {o.path}" + ("  (already done)" if o.reused else ""))
    verdicts = Counter(o.verdict for o in result.cases)
    print(f"{len(result.cases)} cases: " + ", ".join(f"{n} {v}" for v, n in sorted(verdicts.items())) + f"; summary {result.summary}")
    return 0 if verdicts["pass"] == len(result.cases) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bolibench.temporal_run", epilog="see docs/integrations/temporal.md")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("worker", help="run a worker for suite workflows (Ctrl-C stops it; runs resume on restart)")
    start_cmd = commands.add_parser("start", help="start a suite run and wait for it; exit codes as `bolibench run`")
    start_cmd.add_argument("cases", type=Path, help="suite directory or single case file")
    adapter = start_cmd.add_mutually_exclusive_group(required=True)
    adapter.add_argument("--scripts", type=Path, help="fake adapter: script directory, or one script file for one case")
    adapter.add_argument("--agent-url", help="webhook adapter: local agent endpoint (reached from the worker host)")
    start_cmd.add_argument("--timeout", type=float, default=30.0, help="whole-turn deadline in seconds (default 30)")
    start_cmd.add_argument("--output", type=Path, default=Path("runs"), help="artifact root on the worker host (default: runs/)")
    start_cmd.add_argument("--workflow-id", help="run dir name; reuse one to resume a run (default: <UTC timestamp>-<random>)")
    start_cmd.add_argument("--max-attempts", type=int, default=3, help="attempts per case while the agent is unreachable (default 3)")
    args = parser.parse_args(argv)
    if not HAVE_TEMPORAL:
        print("error: needs temporalio: install bolibench[temporal]", file=sys.stderr)
        return 2
    task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", "bolibench")
    if args.command == "worker":
        return asyncio.run(_work(task_queue))
    workflow_id = args.workflow_id or new_run_name()
    try:
        run_dir_for(".", workflow_id)
        suite = suite_input(args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"workflow {workflow_id} on task queue {task_queue}; run dir {run_dir_for(suite.output, workflow_id)}")
    try:
        result = asyncio.run(_start(suite, workflow_id, task_queue))
    except WorkflowFailureError as e:
        print(f"error: workflow failed: {e.cause}", file=sys.stderr)
        return 1
    return report(result)


async def _work(task_queue: str) -> int:
    client = await connect()
    with ThreadPoolExecutor(1) as pool:
        print(f"worker on task queue {task_queue}, namespace {client.namespace}")
        await make_worker(client, task_queue, CaseActivities(), pool).run()
    return 0


async def _start(suite: SuiteInput, workflow_id: str, task_queue: str) -> SuiteResult:
    return await start(await connect(), suite, workflow_id, task_queue)


if __name__ == "__main__":
    sys.exit(main())
