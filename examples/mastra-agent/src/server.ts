// BoliBench webhook server (POST /turn) for the Mastra agent in agent.ts, on a local Ollama model.
//   MODEL=qwen3:8b PORT=8000 npm start
import { readFileSync } from 'node:fs';
import { createServer, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { z } from 'zod';
import { type History, runTurn, TurnRequest } from './agent.ts';

const MAX_BODY = 64 * 1024;
const env = process.env;
const MODEL = env.MODEL ?? 'qwen3:8b';
const OLLAMA_BASE_URL = env.OLLAMA_BASE_URL ?? 'http://127.0.0.1:11434/v1';
const PORT = z.coerce.number().int().min(0).max(65535).parse(env.PORT ?? 8000);
const TURN_TIMEOUT_S = z.coerce.number().positive().parse(env.TURN_TIMEOUT_S ?? 170);

const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')) as { version: string };
const agent = { name: 'bolibench-mastra-agent', version: `${pkg.version}+${MODEL}` };
// Mastra's model router with a custom OpenAI-compatible url; Ollama ignores the key but the client wants one
const model = { id: `ollama/${MODEL}` as const, url: OLLAMA_BASE_URL, apiKey: 'ollama' };
const conversations = new Map<string, History>();

function send(res: ServerResponse, status: number, body: unknown): void {
  const data = JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(data) });
  res.end(data);
}

const server = createServer(async (req, res) => {
  if (req.method !== 'POST' || req.url !== '/turn') return send(res, 404, { error: 'unknown endpoint' });
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req as AsyncIterable<Buffer>) {
    size += chunk.length;
    if (size > MAX_BODY) return send(res, 413, { error: `body exceeds ${MAX_BODY} bytes` });
    chunks.push(chunk);
  }
  let json: unknown;
  try {
    json = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return send(res, 400, { error: 'body is not valid JSON' });
  }
  const parsed = TurnRequest.safeParse(json);
  if (!parsed.success) return send(res, 400, { error: z.prettifyError(parsed.error) });
  const turn = parsed.data;
  if (turn.turn === 0) {
    conversations.clear(); // BoliBench runs one case at a time
    conversations.set(turn.conversation, []);
  }
  const history = conversations.get(turn.conversation);
  if (!history) return send(res, 409, { error: `unknown conversation ${turn.conversation}` });
  try {
    send(res, 200, { reply: await runTurn(turn, model, history, TURN_TIMEOUT_S * 1000), agent });
  } catch (e) {
    console.error(`turn ${turn.turn} failed:`, e);
    send(res, 500, { error: e instanceof Error ? e.message : String(e) });
  }
});
server.listen(PORT, '127.0.0.1', () => {
  const { port } = server.address() as AddressInfo;
  console.log(`${agent.name} ${agent.version} on http://127.0.0.1:${port}/turn, model via ${OLLAMA_BASE_URL}`);
});
