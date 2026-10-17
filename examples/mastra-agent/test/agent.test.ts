// Offline: the real Mastra loop against a scripted OpenAI-compatible model and a stub tool gateway.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer, type IncomingMessage, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { test } from 'node:test';
import { type History, runTurn, TurnRequest } from '../src/agent.ts';

type Call = { name: string; args: Record<string, unknown> };
type Step = { calls: Call[] } | { text: string };
type Json = Record<string, any>;

async function body(req: IncomingMessage): Promise<Json> {
  let data = '';
  for await (const chunk of req) data += chunk;
  return JSON.parse(data);
}

async function listen(server: Server): Promise<string> {
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}

/** Scripted Chat Completions endpoint: one step per request, streamed or not, as the client asks. */
async function fakeModel(steps: Step[]) {
  const requests: Json[] = [];
  const server = createServer(async (req, res) => {
    const request = await body(req);
    requests.push(request);
    const step = steps.shift();
    assert.ok(step, 'model called more often than scripted');
    const toolCalls = 'calls' in step
      ? step.calls.map((c, i) => ({ index: i, id: `call_${requests.length}_${i}`, type: 'function', function: { name: c.name, arguments: JSON.stringify(c.args) } }))
      : undefined;
    const message = { role: 'assistant', content: 'text' in step ? step.text : null, tool_calls: toolCalls };
    const finish = toolCalls ? 'tool_calls' : 'stop';
    const usage = { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 };
    const base = { id: 'x', created: 0, model: request.model };
    if (!request.stream) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ ...base, object: 'chat.completion', choices: [{ index: 0, message, finish_reason: finish }], usage }));
    }
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const chunk = (choice: Json, extra: Json = {}) =>
      res.write(`data: ${JSON.stringify({ ...base, object: 'chat.completion.chunk', choices: [choice], ...extra })}\n\n`);
    chunk({ index: 0, delta: message, finish_reason: null });
    chunk({ index: 0, delta: {}, finish_reason: finish }, { usage });
    res.end('data: [DONE]\n\n');
  });
  return { url: `${await listen(server)}/v1`, requests, close: () => server.close() };
}

async function fakeGateway(status = 200) {
  const calls: Json[] = [];
  const server = createServer(async (req, res) => {
    calls.push(await body(req));
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(status === 200 ? { ok: true, result: { orders: [] }, error: null } : { error: 'tool request outside an active turn' }));
  });
  return { url: `${await listen(server)}/runs/tok/tools`, calls, close: () => server.close() };
}

const TOOLS = { list_orders: [], get_order: ['order_id'], cancel_order: ['order_id'], update_quantity: ['order_id', 'quantity'], ask_user: ['kind', 'question'] };
const request = (toolsUrl: string, turn = 0, utterance = 'मेरा kurta वाला order cancel कर दो') =>
  TurnRequest.parse({ conversation: 'c1', turn, utterance, context: { today: '2026-10-17', policy: null }, tools_url: toolsUrl, tools: TOOLS });

async function withStubs(steps: Step[], gatewayStatus: number, fn: (m: Awaited<ReturnType<typeof fakeModel>>, g: Awaited<ReturnType<typeof fakeGateway>>) => Promise<void>) {
  const [model, gateway] = await Promise.all([fakeModel(steps), fakeGateway(gatewayStatus)]);
  try {
    await fn(model, gateway);
  } finally {
    model.close();
    gateway.close();
  }
}

test('ask_user ends the turn: later calls are not sent, the question is the reply', () =>
  withStubs(
    [{ calls: [{ name: 'list_orders', args: {} }, { name: 'ask_user', args: { kind: 'confirm', question: 'Kurta वाला cancel कर दूँ?' } }, { name: 'cancel_order', args: { order_id: 'ORD-1' } }] }],
    200,
    async (model, gateway) => {
      const reply = await runTurn(request(gateway.url), { id: 'ollama/fake', url: model.url, apiKey: 'x' }, [], 10_000);
      assert.equal(reply, 'Kurta वाला cancel कर दूँ?');
      assert.deepEqual(gateway.calls, [
        { tool: 'list_orders', args: {} },
        { tool: 'ask_user', args: { kind: 'confirm', question: 'Kurta वाला cancel कर दूँ?' } },
      ]);
      assert.equal(model.requests.length, 1);
      const sent = model.requests[0]!;
      assert.equal(sent.model, 'fake');
      assert.equal(sent.reasoning_effort, 'none');
      const quantity = sent.tools.find((t: Json) => t.function.name === 'update_quantity').function.parameters.properties.quantity;
      assert.equal(quantity.type, 'integer');
      assert.match(sent.messages[0].content, /Today's date is 2026-10-17\.$/);
    },
  ));

test('tool results feed the next step; history carries over to the next turn', () =>
  withStubs(
    [{ calls: [{ name: 'list_orders', args: {} }] }, { text: 'कौन सा order?' }, { text: 'हो गया' }],
    200,
    async (model, gateway) => {
      const history: History = [];
      const config = { id: 'ollama/fake' as const, url: model.url, apiKey: 'x' };
      assert.equal(await runTurn(request(gateway.url), config, history, 10_000), 'कौन सा order?');
      assert.equal(await runTurn(request(gateway.url, 1, 'नीला वाला'), config, history, 10_000), 'हो गया');
      assert.deepEqual(gateway.calls, [{ tool: 'list_orders', args: {} }]);
      const roles = model.requests[2]!.messages.map((m: Json) => m.role);
      assert.deepEqual(roles, ['system', 'user', 'assistant', 'tool', 'assistant', 'user']);
    },
  ));

test('a gateway refusal fails the turn instead of reaching the model as a tool result', () =>
  withStubs([{ calls: [{ name: 'list_orders', args: {} }] }, { text: 'unused' }], 409, async (model, gateway) => {
    await assert.rejects(runTurn(request(gateway.url), { id: 'ollama/fake', url: model.url, apiKey: 'x' }, [], 10_000), /answered 409 to list_orders/);
    assert.equal(model.requests.length, 1);
  }));

test('tools_url must be plain http on localhost', () => {
  assert.throws(() => request('https://127.0.0.1:1/runs/t/tools'));
  assert.throws(() => request('http://example.com/runs/t/tools'));
});

test('server: identity on replies, 400 on bad turns, 413 on big bodies', async () => {
  const server = spawn(process.execPath, ['src/server.ts'], { env: { ...process.env, PORT: '0', MODEL: 'qwen3:8b' }, stdio: ['ignore', 'pipe', 'inherit'] });
  try {
    const [line] = (await once(server.stdout!, 'data')) as [Buffer];
    const url = /(http:\S+\/turn)/.exec(line.toString())![1]!;
    assert.match(line.toString(), /^bolibench-mastra-agent 0\.1\.0\+qwen3:8b /);
    const post = (data: string) => fetch(url, { method: 'POST', body: data }).then(async (r) => [r.status, await r.json()] as const);
    assert.equal((await post('{"turn": 0}'))[0], 400);
    assert.equal((await post('x'.repeat(70_000)))[0], 413);
  } finally {
    server.kill();
  }
});
