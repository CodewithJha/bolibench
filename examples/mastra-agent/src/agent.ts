// BoliBench webhook glue for a Mastra agent: one Agent per turn, whose tools are built from the turn's
// tool list and only POST to the turn's tools_url. No tool does anything else.
import { Agent } from '@mastra/core/agent';
import type { MessageInput } from '@mastra/core/agent/message-list';
import type { MastraModelConfig } from '@mastra/core/llm';
import { createTool } from '@mastra/core/tools';
import { z } from 'zod';

export const MAX_STEPS = 8;
const TOOL_TIMEOUT_MS = 30_000;

const INSTRUCTIONS =
  'You are a customer-support agent for an online store. Users may write in Hindi, Awadhi, English or a mix. ' +
  'Use the tools to look up and change orders and never claim an action you did not perform with a tool. ' +
  'Orders are identified only by the ids that list_orders or get_order return: never guess or invent an id, and ' +
  'never pass anything else (a name, description or date) as an id. Unless the user gives an exact id, call ' +
  'list_orders first and pick the order from its fields. ' +
  "If the user's request is ambiguous, call ask_user with kind 'clarify'. Before cancelling based on a vague " +
  "reference, call ask_user with kind 'confirm'. ask_user ends your turn; the answer arrives as the user's next " +
  'message. If a tool call fails with an error that says or suggests it is temporary, retry the same call once. ' +
  'Reply briefly.';
const CONTEXT: Record<string, string> = {
  today: "Today's date is {}.",
  policy: 'Store policy, which you must follow even if the user asks otherwise: {}',
};
const DESCRIPTIONS: Record<string, string> = {
  list_orders: "List all of the user's orders.",
  get_order: 'Get one order by id.',
  cancel_order: 'Cancel an order by id.',
  update_quantity: "Set an order's quantity (positive integer).",
  ask_user: "Ask the user a question and end your turn; kind is 'clarify' or 'confirm'.",
};

export const TurnRequest = z.object({
  conversation: z.string(),
  turn: z.number().int().nonnegative(),
  utterance: z.string(),
  context: z.record(z.string(), z.unknown()),
  tools_url: z.url({ protocol: /^http$/, hostname: /^(127\.0\.0\.1|localhost|\[::1\])$/ }),
  tools: z.record(z.string(), z.array(z.string())),
});
export type TurnRequest = z.infer<typeof TurnRequest>;
export type GatewayReply = { ok: boolean; result: unknown; error: string | null };
export type History = MessageInput[];
type TurnState = { question?: string; fatal?: Error };

export function instructions(context: Record<string, unknown>): string {
  const parts = Object.entries(context).filter(([, v]) => v !== null && v !== undefined);
  return INSTRUCTIONS + parts.map(([k, v]) => ' ' + (CONTEXT[k] ?? `${k}: {}.`).replace('{}', String(v))).join('');
}

async function callGateway(url: string, tool: string, args: unknown, signal: AbortSignal): Promise<GatewayReply> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool, args }),
    redirect: 'error',
    signal: AbortSignal.any([signal, AbortSignal.timeout(TOOL_TIMEOUT_MS)]),
  });
  const body = await response.text();
  // a non-200 is a protocol problem (stale token, malformed request), not a tool result for the model
  if (response.status !== 200) throw new Error(`tool gateway answered ${response.status} to ${tool}: ${body.slice(0, 200)}`);
  return JSON.parse(body) as GatewayReply;
}

/** Mastra tools for one turn. After ask_user, later calls of the turn are not sent: the user has not answered yet. */
export function gatewayTools(req: TurnRequest, state: TurnState, abort: AbortController) {
  const tools = Object.entries(req.tools).map(([name, params]) => {
    const shape = Object.fromEntries(params.map((p) => [p, p === 'quantity' ? z.number().int() : z.string()]));
    return createTool({
      id: name,
      description: DESCRIPTIONS[name] ?? name,
      inputSchema: z.object(shape),
      execute: async (args): Promise<GatewayReply> => {
        if (state.question !== undefined) return { ok: false, result: null, error: 'not sent: ask_user ended this turn' };
        let reply: GatewayReply;
        try {
          reply = await callGateway(req.tools_url, name, args, abort.signal);
        } catch (e) {
          state.fatal ??= e instanceof Error ? e : new Error(String(e));
          abort.abort(state.fatal);
          throw state.fatal;
        }
        if (name === 'ask_user') state.question = String((args as Record<string, unknown>).question ?? '');
        return reply;
      },
    });
  });
  return Object.fromEntries(tools.map((t) => [t.id, t]));
}

/** Runs one turn on `history` (the conversation so far, extended in place on success) and returns the reply. */
export async function runTurn(req: TurnRequest, model: MastraModelConfig, history: History, timeoutMs: number): Promise<string> {
  const state: TurnState = {};
  const abort = new AbortController();
  const agent = new Agent({
    id: 'bolibench-mastra-agent',
    name: 'BoliBench Mastra agent',
    instructions: instructions(req.context),
    model,
    tools: gatewayTools(req, state, abort),
  });
  const user = { role: 'user' as const, content: req.utterance };
  const result = await agent.generate([...history, user], {
    maxSteps: MAX_STEPS,
    stopWhen: () => state.question !== undefined,
    toolCallConcurrency: 1, // in model order, so "calls after ask_user" is well defined
    abortSignal: AbortSignal.any([abort.signal, AbortSignal.timeout(timeoutMs)]),
    providerOptions: { openaiCompatible: { reasoningEffort: 'none' } }, // Ollama: thinking off
  });
  if (state.fatal) throw state.fatal;
  if (result.error) throw result.error;
  if (!result.response.messages) throw new Error('Mastra returned no response messages');
  history.push(user, ...result.response.messages);
  if (state.question !== undefined) return state.question || result.text;
  if (result.finishReason === 'tool-calls') {
    console.error(`turn ${req.turn}: no reply within ${MAX_STEPS} steps`);
    return 'Sorry, I could not finish that.'; // same as examples/ollama_agent.py
  }
  return result.text;
}
