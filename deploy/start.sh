#!/bin/sh
# Container entrypoint. Live mode: when AGENT_BASE_URL, AGENT_MODEL and AGENT_API_KEY_ENV are set and the
# variable AGENT_API_KEY_ENV names holds a key, the example agent runs on 127.0.0.1 against that
# OpenAI-compatible endpoint and the demo server drives it (the server also needs BOLIBENCH_DEMO_TOKEN).
# Otherwise only the demo server runs and live mode reports itself disabled.
# If the agent dies later, live runs come back as `error` verdicts; the server keeps serving.
set -eu

AGENT_PORT=8765

if [ -n "${AGENT_BASE_URL:-}" ] && [ -n "${AGENT_MODEL:-}" ] && [ -n "${AGENT_API_KEY_ENV:-}" ] \
    && [ -n "$(printenv "$AGENT_API_KEY_ENV" || true)" ]; then
    # the agent never sees the demo token, the server never sees the model key
    env -u BOLIBENCH_DEMO_TOKEN python examples/ollama_agent.py --backend openai --base-url "$AGENT_BASE_URL" \
        --model "$AGENT_MODEL" --api-key-env "$AGENT_API_KEY_ENV" --tool-mode "${AGENT_TOOL_MODE:-native}" --port "$AGENT_PORT" &
    export BOLIBENCH_LIVE_AGENT_URL="http://127.0.0.1:$AGENT_PORT/turn"
    exec env -u "$AGENT_API_KEY_ENV" python -m bolibench.server
fi

echo "live mode: no hosted agent (needs AGENT_BASE_URL, AGENT_MODEL, AGENT_API_KEY_ENV and a key in the variable it names)"
exec env -u BOLIBENCH_LIVE_AGENT_URL python -m bolibench.server
