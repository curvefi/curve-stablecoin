import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { renderMdx } from "smithers-orchestrator";
import WriterSystemMdx from "./prompts/writer-system.mdx";
import JudgeSystemMdx from "./prompts/judge-system.mdx";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROMPTS_DIR = resolve(__dirname, "prompts");

function readPromptFile(name: string): string {
  try {
    return readFileSync(resolve(PROMPTS_DIR, name), "utf-8");
  } catch {
    return `[Could not read prompt file: ${name}]`;
  }
}

const Spec = () => readPromptFile("spec.md");

export const WRITER_SYSTEM = renderMdx(WriterSystemMdx, {
  components: { Spec },
});

export const JUDGE_SYSTEM = renderMdx(JudgeSystemMdx, {
  components: { Spec },
});
