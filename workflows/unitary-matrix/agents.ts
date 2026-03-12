import { CodexAgent } from "smithers-orchestrator";
import { AGENT_TIMEOUT_MS } from "./config";
import { WRITER_SYSTEM, JUDGE_SYSTEM } from "./system-prompts";

const WRITER_MODEL = "gpt-5.3-codex";
const JUDGE_MODEL = "gpt-5.3-codex";

export const writer = new CodexAgent({
  model: WRITER_MODEL,
  systemPrompt: WRITER_SYSTEM,
  config: { model_reasoning_effort: "high" },
  sandbox: "read-only",
  timeoutMs: AGENT_TIMEOUT_MS,
});

export const judge = new CodexAgent({
  model: JUDGE_MODEL,
  systemPrompt: JUDGE_SYSTEM,
  config: { model_reasoning_effort: "high" },
  sandbox: "read-only",
  timeoutMs: AGENT_TIMEOUT_MS,
});
