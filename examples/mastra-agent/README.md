# bolibench-mastra-agent

A BoliBench webhook agent built with Mastra (`@mastra/core`), running a local open-weight model through
Ollama's OpenAI-compatible API. Tools are created per turn from BoliBench's tool list and only call
BoliBench's tool gateway. Details, results and limitations: `docs/integrations/mastra.md`.

```sh
ollama serve                         # qwen3:8b already pulled
npm install
MODEL=qwen3:8b PORT=8000 npm start
# from the repository root:
uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 --output runs/
```

Env: `MODEL` (`qwen3:8b`), `OLLAMA_BASE_URL` (`http://127.0.0.1:11434/v1`), `PORT` (`8000`),
`TURN_TIMEOUT_S` (`170`). Tests (offline, no model): `npm test`; types: `npm run typecheck`.
Node 22.18+ (runs TypeScript directly, no build step).
