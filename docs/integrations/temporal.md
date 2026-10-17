# Durable suite runs with Temporal (optional)

`bolibench run` is a plain loop: if the process dies at case 9 of 12 during a 5-minute real-model run,
or an hour into a speech-wrapped run, the run directory is left half-written and you start over.
`python -m bolibench.temporal_run` runs the same cases as a [Temporal](https://temporal.io) workflow:

- **Resume after crashes.** One workflow per suite run, one activity per case. Kill the worker, reboot
  the laptop, restart the worker: finished cases are not re-run, the interrupted one starts over.
- **Bounded retries for infrastructure only.** If the agent is unreachable (connection refused or
  dropped), the case is retried up to `--max-attempts` times (default 3, backoff 2s doubling up to 1m).
  Nothing else is retried: a `fail`, `error` or `inconclusive` verdict is a result, and so is a turn
  deadline, an HTTP error status or a malformed reply.
- **Visibility.** Every case is an activity in the Temporal UI with its input, result, attempts and errors.

For the 12 scripted cases in `suites/orders`, which finish in under a second, this is overkill: use
`bolibench run`. It pays off for long real-model or speech runs.

Artifacts are the same files `bolibench run` writes (`<case_id>.json` and `summary.json`, same schema,
same `config_id`), so every other tool reads them unchanged.

## Setup

```sh
uv sync --extra temporal            # or: pip install 'bolibench[temporal]'  (temporalio>=1.34)
```

Then you need a Temporal server, either of:

- **Local dev server:** install the [Temporal CLI](https://docs.temporal.io/cli) yourself, then run
  `temporal server start-dev`. It serves the API on `localhost:7233` and the UI on http://localhost:8233.
  By default its state is in memory; add `--db-filename temporal.db` so workflows also survive a server restart.
- **Temporal Cloud:** set `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE` and `TEMPORAL_API_KEY` (below).

## Run

Two processes, in the same working directory on the same machine (see constraints):

```sh
# terminal 1: the worker executes the cases; leave it running
python -m bolibench.temporal_run worker

# terminal 2: start a run and wait for it; prints the same lines and exit codes as `bolibench run`
python -m bolibench.temporal_run start suites/orders --scripts my-scripts/ --output runs/
python -m bolibench.temporal_run start suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 60
```

`start` takes the same inputs as `bolibench run` and checks them the same way (exit 2, nothing runs).
It also takes `--workflow-id ID` (default `<UTC timestamp>-<random>`, the same shape as
`bolibench run` directory names) and `--max-attempts N`. The run directory is `<output>/<workflow id>`.

- Killing `start` does not stop the run; the worker carries on. Run the same `start ... --workflow-id ID`
  again to wait for it.
- To resume a run whose workflow *failed* (for example a bug, after you fix it), or after losing the
  dev server's state, start it again with the same `--workflow-id`. Cases whose artifacts already exist
  are reported as `(already done)` and are not re-run.

## Configuration (environment only)

| Variable | Default | |
|---|---|---|
| `TEMPORAL_ADDRESS` | `localhost:7233` | server `host:port`; Cloud: `<ns>.<acct>.tmprl.cloud:7233` or the regional endpoint |
| `TEMPORAL_NAMESPACE` | `default` | |
| `TEMPORAL_API_KEY` | none | Temporal Cloud API key; setting it turns TLS on. Never printed or logged by BoliBench. |
| `TEMPORAL_TASK_QUEUE` | `bolibench` | must be the same for `worker` and `start` |

Address, namespace and API key are read by temporalio's own `envconfig`, so a `temporal.toml`
profile (`TEMPORAL_PROFILE`, `TEMPORAL_CONFIG_FILE`, `TEMPORAL_TLS*`) works as well.

## How it works

- `start` loads the cases and scripts, then starts workflow `BoliBenchSuite` with absolute paths to
  the case files, scripts and output root. The workflow code does no I/O and reads no clock or randomness.
  It runs the cases in order, one activity (`bolibench.run_case`) per case, then one activity
  (`bolibench.write_summary`).
- `bolibench.run_case` calls the same `run_case`, `evaluate` and `write_artifact` as `bolibench run`.
  If `<run dir>/<case_id>.json` already holds a valid artifact for that case, the activity returns its
  verdict and runs nothing. Artifacts are created exclusively and never overwritten. A partial file
  (the worker died mid-write) is not counted as done: the activity fails without retrying and
  leaves the file for you to inspect.
- **Timeout:** start-to-close = turns x `--timeout` + 30s. A turn deadline that expires inside the
  adapter is an `error` verdict, as in `bolibench run`. The activity timeout only fires when the
  worker died or hung. Temporal then retries the case, so "resume after crash" means "wait up to this
  timeout".
- **Which errors are retried:** the webhook adapter raises `AdapterError` for every failure. The
  activity wraps the adapter: if the error was caused by `ConnectionRefusedError` or
  `ConnectionResetError` (directly, or as urllib's `URLError.reason`), it is raised as
  `AgentUnavailable`. That error escapes `run_case`, writes nothing, and Temporal retries the whole
  case on a fresh sandbox. On the last attempt it is left as `AdapterError`, so the case is recorded as
  an `error` verdict exactly like `bolibench run`. Any other exception from the activity (a bug or bad
  input) is raised as a non-retryable `ApplicationError` and fails the workflow; it is never retried,
  because a rerun costs model calls and cannot fix a bug.

## Constraints

- **Shared filesystem.** The worker reads cases and scripts and writes artifacts at the absolute
  paths `start` sent. Run both on one machine, or mount the same paths.
- **Webhook gateway per activity.** The tool gateway is a localhost server inside the worker process.
  Each case attempt opens its own `WebhookAgentAdapter` (own port, own tokens) and closes it when the
  case ends. So the agent must be reachable from the **worker** host at `--agent-url`. A tool call
  that arrives after its case ended gets connection refused instead of becoming a `stray_calls`
  warning; any strays seen during a case are printed on the worker's stderr.
- **One case at a time per worker** (`max_concurrent_activities=1`, cases in order), so turn deadlines
  are not shared with other runs. Two concurrent `start`s on one worker queue behind each other.
- A retried case is re-run from turn 0 with a fresh sandbox and a new conversation id; an agent
  that keeps its own state across conversations may notice.
- Case and script files are read again by the worker when each case runs. Do not edit them during a run.

## Verify it yourself

1. `temporal server start-dev`, then `python -m bolibench.temporal_run worker`, then `start` a suite
   with `--workflow-id demo-1`. Expected: the same per-case lines and exit code as `bolibench run`, and
   `runs/demo-1/summary.json` identical to the `summary.json` of `bolibench run` on the same inputs.
2. Crash: start a webhook run against a slow agent and kill the worker (`kill -9`) after a few cases.
   Restart it. `start` keeps waiting. The interrupted case re-runs after its activity timeout, and the
   run dir ends with exactly one artifact per case plus `summary.json`.
3. Agent down: stop the agent and `start` one case with `--max-attempts 2`. Expected: an `error`
   verdict with `AdapterError: agent request failed: <urlopen error [Errno 61] Connection refused>`,
   after one retry about 2s later.
4. Screenshots worth taking in the UI (http://localhost:8233 for the dev server):
   - the workflow list showing `demo-1` as Completed;
   - the workflow's Event History or timeline with one `bolibench.run_case` per case and the final
     `bolibench.write_summary`;
   - for step 2, the timed-out activity with `Attempt 2`;
   - for step 3, the activity's pending/failed attempt with `AgentUnavailable`;
   - the workflow Result (per-case verdicts and summary path).

Tests: `uv run --with temporalio pytest tests/test_temporal_run.py` runs real workflows on temporalio's
time-skipping test server. It downloads that binary into a temp dir on first use, so it needs network
once. Without temporalio, those tests skip and the offline ones still run.

## Limitations

- No heartbeats: recovering from a dead worker waits out the case's full start-to-close timeout.
- Cases run sequentially; there is no parallel fan-out (the CLI doesn't do it either).
- Only connection refused/reset counts as transient. A 502/503 from a proxy in front of the agent,
  or a model server that is still loading and times out, is recorded as an `error` verdict.
- A partially written artifact (crash during the write itself) stops the run for manual cleanup
  instead of being overwritten.
- Reusing a workflow id reuses whatever artifacts are in that directory, by case id only. It does not
  check that they came from the same adapter or scripts.
