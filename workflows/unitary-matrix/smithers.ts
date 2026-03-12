import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createSmithers } from "smithers-orchestrator";
import {
  DiscoveryOutput,
  WriterOutput,
  ProgrammaticCheckOutput,
  JudgeOutput,
  ReviewOutput,
  IssueMemoryOutput,
} from "./schemas";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../..");
const DEFAULT_DB = resolve(ROOT, ".tmp/unitary-matrix-loop.db");

export const { Workflow, Task, smithers, outputs } = createSmithers(
  {
    discovery: DiscoveryOutput,
    writer: WriterOutput,
    programmaticCheck: ProgrammaticCheckOutput,
    judgeRaw: JudgeOutput,
    review: ReviewOutput,
    issueMemory: IssueMemoryOutput,
  },
  { dbPath: process.env.SMITHERS_DB_PATH ?? DEFAULT_DB },
);
