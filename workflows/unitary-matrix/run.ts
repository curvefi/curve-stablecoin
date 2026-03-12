#!/usr/bin/env bun
/**
 * Run the matrix loop with rich progress output.
 * Usage:
 *   bun run workflows/unitary-matrix/run.ts [--input '{"contractPath":"curve_stablecoin/AMM.vy"}']
 *   bun run workflows/unitary-matrix/run.ts --resume-run-id <run-id>
 *   bun run workflows/unitary-matrix/run.ts --show-agent-output
 *   bun run workflows/unitary-matrix/run.ts --agent-output compact|full|off
 */
import { resolve, dirname, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { Database } from "bun:sqlite";
import { runWorkflow } from "smithers-orchestrator";
import { BRANCH_CHUNK_SIZE, discoverTargets } from "./config";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../..");
const dbPath = resolve(ROOT, ".tmp/unitary-matrix-loop.db");
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;
const TELEGRAM_ENABLED = Boolean(TELEGRAM_BOT_TOKEN && TELEGRAM_CHAT_ID);

let input: Record<string, unknown> = {};
let resumeRunId: string | null = null;
type AgentOutputMode = "off" | "compact" | "full";
let agentOutputMode: AgentOutputMode = "off";
for (let i = 2; i < process.argv.length; i++) {
  if (process.argv[i] === "--input" && process.argv[i + 1]) {
    input = JSON.parse(process.argv[i + 1]);
    i += 1;
  } else if (process.argv[i] === "--resume-run-id" && process.argv[i + 1]) {
    resumeRunId = process.argv[i + 1];
    i += 1;
  } else if (process.argv[i] === "--show-agent-output") {
    agentOutputMode = "compact";
  } else if (process.argv[i] === "--agent-output" && process.argv[i + 1]) {
    const raw = String(process.argv[i + 1]).toLowerCase();
    if (raw === "off" || raw === "compact" || raw === "full") {
      agentOutputMode = raw;
    }
    i += 1;
  }
}
const showAgentOutput = agentOutputMode !== "off";

// Import the workflow
const workflow = (await import("./workflow.tsx")).default;

function sanitizeId(contractPath: string, functionName: string): string {
  return `${contractPath}:${functionName}`.replace(/[^a-z0-9]/gi, "-").toLowerCase();
}

const allTargets = discoverTargets();
const scopedTargets = allTargets.filter((t) => {
  if (typeof input.contractPath === "string" && t.contractPath !== input.contractPath) {
    return false;
  }
  if (typeof input.functionName === "string" && t.functionName !== input.functionName) {
    return false;
  }
  return true;
});
const labelBySid = new Map<string, { contract: string; fn: string }>();
const chunkCountBySid = new Map<string, number>();
const branchCountBySid = new Map<string, number>();
const chunkBranchCountsBySid = new Map<string, number[]>();
const chunkOrdinalByKey = new Map<string, number>();
let totalBatchesPlanned = 0;
for (const t of scopedTargets) {
  const sid = sanitizeId(t.contractPath, t.functionName);
  const contract = basename(t.contractPath, ".vy");
  labelBySid.set(sid, { contract, fn: t.functionName });

  const totalBranches = t.branchTargets?.length ?? 0;
  const chunkCount = Math.max(1, Math.ceil(totalBranches / BRANCH_CHUNK_SIZE));
  const chunkBranchCounts = Array.from({ length: chunkCount }, (_, idx) => {
    const start = idx * BRANCH_CHUNK_SIZE;
    return Math.max(0, Math.min(BRANCH_CHUNK_SIZE, totalBranches - start));
  });

  chunkCountBySid.set(sid, chunkCount);
  branchCountBySid.set(sid, totalBranches);
  chunkBranchCountsBySid.set(sid, chunkBranchCounts);

  for (let c = 1; c <= chunkCount; c++) {
    totalBatchesPlanned += 1;
    chunkOrdinalByKey.set(`${sid}:chunk-${c}`, totalBatchesPlanned);
  }
}

function parseChunkNode(nodeId: string): { sid: string; chunkNo: number; role: string } | null {
  const m = nodeId.match(/^(.*):chunk-(\d+):([^:]+)$/);
  if (!m) return null;
  return {
    sid: m[1],
    chunkNo: Number(m[2]),
    role: m[3],
  };
}

function shortNodeLabel(nodeId: string): string {
  if (nodeId === "discover-targets") return "discover-targets";
  const parts = nodeId.split(":");
  const role = parts[parts.length - 1] ?? "";
  const core = parts.slice(0, -1).join(":");
  const chunkMatch = core.match(/:chunk-(\d+)$/);
  const baseSid = chunkMatch ? core.slice(0, chunkMatch.index) : core;
  const chunkNo = chunkMatch ? Number(chunkMatch[1]) : null;
  const meta = labelBySid.get(baseSid);
  const roleLabel = role === "write" ? "writer" : role === "review" ? "judge" : role;
  if (!meta) return `${nodeId}`;
  return `${meta.contract}.${meta.fn}${chunkNo ? ` chunk ${chunkNo}` : ""} ${roleLabel}`;
}

function fmtDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms));
  const s = Math.floor(total / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m ${sec}s`;
  if (m > 0) return `${m}m ${sec}s`;
  if (s > 0) return `${s}s`;
  return `${total}ms`;
}

function nodeAttemptKey(nodeId: string, iteration: number, attempt: number): string {
  return `${nodeId}::${iteration}::${attempt}`;
}

function readOutput(nodeId: string, iteration: number, table: string): any {
  try {
    const db = new Database(dbPath, { readonly: true });
    const row = db.query(
      `SELECT * FROM ${table} WHERE node_id = ? AND iteration = ? ORDER BY rowid DESC LIMIT 1`
    ).get(nodeId, iteration) as any;
    db.close();
    return row;
  } catch {
    return null;
  }
}

const printedContracts = new Set<string>();

function relPath(p: string): string {
  if (typeof p !== "string") return "";
  return p.startsWith(ROOT + "/") ? p.slice(ROOT.length + 1) : p;
}

function printWriterOutput(nodeId: string, iteration: number) {
  const row = readOutput(nodeId, iteration, "writer");
  if (!row) return;

  const entry = JSON.parse(row.entry);
  const contractPath = relPath(row.contract_path ?? row.contractPath ?? entry.contractPath ?? "");
  const filePath = relPath(entry.filePath ?? "");
  const functionName = row.function_name ?? row.functionName ?? entry.method ?? "";

  if (contractPath && !printedContracts.has(contractPath)) {
    printedContracts.add(contractPath);
    process.stderr.write(`\n## \`${contractPath}\`\n\n`);
  }

  process.stderr.write(`### \`${filePath}\` — \`${functionName}\` [writer iter ${iteration}]\n\n`);

  const cases = entry.cases ?? [];
  for (const c of cases) {
    const icon = c.status === "compliant" ? "[x]"
      : c.status === "redundant" ? "[-]"
      : c.status === "non_compliant" ? "[!]"
      : "[ ]";
    const branch = c.branchName
      ? ` *(${c.branchName}${c.branchId ? ` | ${c.branchId}` : ""})*`
      : c.branch
        ? ` *(${c.branch})*`
        : c.branchId
          ? ` *(${c.branchId})*`
          : "";
    process.stderr.write(`- ${icon} \`${c.name}\`${branch}\n`);
    for (let i = 0; i < (c.steps ?? []).length; i++) {
      process.stderr.write(`  - ${i + 1}. ${c.steps[i]}\n`);
    }
    if (c.issues && c.issues.length > 0) {
      for (const issue of c.issues) {
        process.stderr.write(`  > ${issue}\n`);
      }
    }
  }
  process.stderr.write("\n");
}

function printReviewOutput(nodeId: string, iteration: number) {
  const row = readOutput(nodeId, iteration, "review");
  if (!row) return;

  const caseIssues = JSON.parse(row.case_issues ?? row.caseIssues ?? "[]") as Array<{
    testCaseName: string;
    branchId: string;
    issue: string;
  }>;
  const summaryIssues = JSON.parse(
    row.summary_issues ?? row.summaryIssues ?? "[]",
  ) as string[];
  const functionName =
    row.function_name ??
    readOutput(nodeId.replace(/:review$/, ":write"), iteration, "writer")?.function_name ??
    nodeId;
  if (row.approved) {
    process.stderr.write(`✅ judge approved \`${functionName}\`\n\n`);
  } else {
    const totalIssues = caseIssues.length + summaryIssues.length;
    process.stderr.write(`❌ judge rejected \`${functionName}\` (${totalIssues} issues)\n`);
    for (const issue of caseIssues) {
      process.stderr.write(
        `- [${issue.branchId}] ${issue.testCaseName}: ${issue.issue}\n`,
      );
    }
    for (const issue of summaryIssues) {
      process.stderr.write(`- ${issue}\n`);
    }
    process.stderr.write("\n");
  }
}

function getProgress(runId: string): {
  started: number;
  approved: number;
  rejected: number;
  batchesStarted: number;
  batchesReviewed: number;
  batchesApproved: number;
} {
  try {
    const db = new Database(dbPath, { readonly: true });
    const writerNodes = db
      .query("SELECT DISTINCT node_id FROM writer WHERE run_id = ?")
      .all(runId) as Array<{ node_id: string }>;

    const startedFns = new Set<string>();
    for (const row of writerNodes) {
      const nodeId = row.node_id;
      const base = nodeId.replace(/:chunk-\d+:write$/, "").replace(/:write$/, "");
      startedFns.add(base);
    }

    const reviewRows = db
      .query(
        `
        SELECT node_id, iteration, approved
        FROM review
        WHERE run_id = ?
        ORDER BY node_id, iteration DESC
        `,
      )
      .all(runId) as Array<{ node_id: string; iteration: number; approved: number }>;

    const latestByChunk = new Map<string, { approved: boolean }>();
    for (const row of reviewRows) {
      if (!latestByChunk.has(row.node_id)) {
        latestByChunk.set(row.node_id, { approved: Boolean(row.approved) });
      }
    }

    let approved = 0;
    let rejected = 0;
    for (const [sid, expectedChunks] of chunkCountBySid.entries()) {
      let reviewedChunks = 0;
      let rejectedChunks = 0;
      for (let c = 1; c <= expectedChunks; c++) {
        const chunkNode = `${sid}:chunk-${c}:review`;
        const state = latestByChunk.get(chunkNode);
        if (!state) continue;
        reviewedChunks += 1;
        if (!state.approved) rejectedChunks += 1;
      }
      if (rejectedChunks > 0) {
        rejected += 1;
      } else if (reviewedChunks === expectedChunks && expectedChunks > 0) {
        approved += 1;
      }
    }

    const started = startedFns.size;
    const batchesStarted = writerNodes.length;
    const batchesReviewed = latestByChunk.size;
    let batchesApproved = 0;
    for (const state of latestByChunk.values()) {
      if (state.approved) batchesApproved += 1;
    }

    db.close();
    return {
      started,
      approved,
      rejected,
      batchesStarted,
      batchesReviewed,
      batchesApproved,
    };
  } catch {
    return {
      started: 0,
      approved: 0,
      rejected: 0,
      batchesStarted: 0,
      batchesReviewed: 0,
      batchesApproved: 0,
    };
  }
}

function pct(num: number, den: number): string {
  if (den <= 0) return "0.0";
  return ((num / den) * 100).toFixed(1);
}

async function sendTelegram(text: string): Promise<void> {
  if (!TELEGRAM_ENABLED) return;
  try {
    await fetch(
      `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          chat_id: TELEGRAM_CHAT_ID,
          text,
          disable_web_page_preview: true,
        }),
      },
    );
  } catch {
    // Best-effort notifications; do not fail workflow on telegram issues.
  }
}

function notifyTelegram(text: string): void {
  void sendTelegram(text);
}

function buildReviewTelegramMessage(nodeId: string, iteration: number): string | null {
  const row = readOutput(nodeId, iteration, "review");
  if (!row) return null;

  const caseIssues = JSON.parse(row.case_issues ?? row.caseIssues ?? "[]") as Array<{
    testCaseName: string;
    branchId: string;
    issue: string;
  }>;
  const summaryIssues = JSON.parse(
    row.summary_issues ?? row.summaryIssues ?? "[]",
  ) as string[];
  const totalIssues = caseIssues.length + summaryIssues.length;
  const label = shortNodeLabel(nodeId).replace(/\sjudge$/, "");

  if (row.approved) {
    return `✅ ${label}: judge approved`;
  }

  const issueLines: string[] = [];
  for (const issue of caseIssues.slice(0, 2)) {
    issueLines.push(`• [${issue.branchId}] ${issue.testCaseName}: ${issue.issue}`);
  }
  for (const issue of summaryIssues.slice(0, Math.max(0, 2 - issueLines.length))) {
    issueLines.push(`• ${issue}`);
  }

  const details = issueLines.length > 0 ? `\n${issueLines.join("\n")}` : "";
  return `❌ ${label}: judge rejected (${totalIssues} issue${totalIssues === 1 ? "" : "s"})${details}`;
}

function stripAnsi(text: string): string {
  return text.replace(/\x1b\[[0-9;]*m/g, "");
}

function decodeHtmlEntities(text: string): string {
  return text
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

type AgentRepeatState = {
  line: string;
  count: number;
};

const agentRepeatByNodeStream = new Map<string, AgentRepeatState>();
const nodeStartMsByKey = new Map<string, number>();
const lastChunkStepDurationByChunk = new Map<string, { role: string; ms: number }>();

function printAgentLine(nodeId: string, text: string): void {
  process.stderr.write(`    · ${text}\n`);
}

function flushAgentRepeat(nodeId: string, stream?: "stdout" | "stderr"): void {
  const keys = [...agentRepeatByNodeStream.keys()].filter((k) =>
    stream ? k === `${nodeId}:${stream}` : k.startsWith(`${nodeId}:`),
  );
  for (const key of keys) {
    const state = agentRepeatByNodeStream.get(key);
    if (!state) continue;
    if (state.count > 1) {
      const suffix = state.count - 1;
      const sid = key.endsWith(":stderr") ? "stderr" : "stdout";
      printAgentLine(nodeId, `(last line repeated ${suffix}x)`);
    }
    agentRepeatByNodeStream.delete(key);
  }
}

function normalizeAgentLine(line: string): string | null {
  const t = decodeHtmlEntities(line).trim();
  if (!t) return null;
  if (/^OpenAI Codex v/.test(t)) return null;

  if (agentOutputMode === "compact") {
    if (t === "codex") return null;
    if (/^```/.test(t)) return null;
    if (/^[{}\[\],]$/.test(t)) return null;
    if (/^IMPORTANT: After completing the task below/.test(t)) return null;
    if (/^\*\*REQUIRED OUTPUT\*\*/.test(t)) return null;
    if (/^Output the JSON at the END/.test(t)) return null;
    if (/^\.\/workflows\/unitary-matrix\/prompts\/.+\.mdx:\d+:/.test(t)) return null;
    if (/^\{"contractPath":"","functionName":"","entry":\{"filePath":"","method":"","cases":\[\]\}\}$/.test(t)) return null;

    if (/^thinking$/i.test(t)) return "thinking...";
    const bold = t.match(/^\*\*(.+)\*\*$/);
    if (bold) return `note: ${bold[1]}`;

    if (/^mcp startup: ready:/.test(t)) return t.replace(/^mcp startup: /, "");
    if (/^mcp:/.test(t)) return t;
    if (/^deprecated:/.test(t)) return `warning: ${t}`;
  }

  return t.length > 220 ? `${t.slice(0, 217)}...` : t;
}

function printAgentOutput(event: any): void {
  if (!showAgentOutput) return;
  const stream = event.stream === "stderr" ? "stderr" : "stdout";
  const raw = typeof event.text === "string" ? event.text : "";
  if (!raw) return;
  const cleaned = stripAnsi(raw).replace(/\r/g, "\n");
  const lines = cleaned
    .split("\n")
    .map(normalizeAgentLine)
    .filter((line): line is string => Boolean(line));

  const key = `${event.nodeId}:${stream}`;
  for (const line of lines) {
    const prev = agentRepeatByNodeStream.get(key);
    if (prev && prev.line === line) {
      prev.count += 1;
      agentRepeatByNodeStream.set(key, prev);
      continue;
    }
    if (prev && prev.count > 1) {
      printAgentLine(event.nodeId, `(last line repeated ${prev.count - 1}x)`);
    }
    printAgentLine(event.nodeId, line);
    agentRepeatByNodeStream.set(key, { line, count: 1 });
  }
}

if (TELEGRAM_ENABLED) {
  process.stderr.write("📨 telegram notifications: enabled\n");
  notifyTelegram("🚀 unitary-matrix: run started");
}

if (showAgentOutput) {
  process.stderr.write(`🧠 agent output: ${agentOutputMode}\n`);
}

if (scopedTargets.length > 0) {
  const planLine =
    `📦 plan: ${scopedTargets.length} function(s), ${totalBatchesPlanned} batch(es) total ` +
    `(chunk size ${BRANCH_CHUNK_SIZE})`;
  process.stderr.write(planLine + "\n");
  notifyTelegram(planLine);
  for (const t of scopedTargets) {
    const sid = sanitizeId(t.contractPath, t.functionName);
    const meta = labelBySid.get(sid);
    if (!meta) continue;
    const chunks = chunkCountBySid.get(sid) ?? 1;
    const branches = branchCountBySid.get(sid) ?? 0;
    process.stderr.write(
      `  - ${meta.contract}.${meta.fn}: ${chunks} batch(es), ${branches} branch target(s)\n`,
    );
  }
}

const result = await runWorkflow(workflow, {
  input,
  runId: resumeRunId ?? undefined,
  resume: Boolean(resumeRunId),
  workflowPath: resolve(__dirname, "workflow.tsx"),
  rootDir: ROOT,
  onProgress(event: any) {
    const now = Date.now();
    switch (event.type) {
      case "NodeStarted":
        {
          const nodeId = String(event.nodeId);
          const iter = event.iteration ?? 0;
          const attempt = event.attempt ?? 1;
          nodeStartMsByKey.set(nodeAttemptKey(nodeId, iter, attempt), now);

          const line = `→ ${shortNodeLabel(nodeId)} (attempt ${attempt}, iter ${iter})`;
          process.stderr.write(line + "\n");

          const parsed = parseChunkNode(nodeId);
          if (parsed) {
            const chunkKey = `${parsed.sid}:chunk-${parsed.chunkNo}`;
            const prev = lastChunkStepDurationByChunk.get(chunkKey);
            if (prev) {
              const prevRole =
                prev.role === "write"
                  ? "writer"
                  : prev.role === "review"
                    ? "judge"
                    : prev.role;
              process.stderr.write(
                `  ⏱ previous step (${prevRole}) took ${fmtDuration(prev.ms)}\n`,
              );
            }
          }
        }
        if (
          typeof event.nodeId === "string" &&
          event.nodeId.endsWith(":write") &&
          (/:chunk-1:write$/.test(event.nodeId) || !/:chunk-\d+:write$/.test(event.nodeId)) &&
          (event.iteration ?? 0) === 0 &&
          (event.attempt ?? 1) === 1
        ) {
          const total = scopedTargets.length;
          const progress = getProgress(event.runId);
          const progressLine =
            `  📊 progress: started ${progress.started}/${total} (${pct(progress.started, total)}%), ` +
            `approved ${progress.approved}/${total} (${pct(progress.approved, total)}%), ` +
            `rejected ${progress.rejected}; ` +
            `batches started ${progress.batchesStarted}/${totalBatchesPlanned}, ` +
            `reviewed ${progress.batchesReviewed}/${totalBatchesPlanned}, ` +
            `approved ${progress.batchesApproved}/${totalBatchesPlanned}`;
          process.stderr.write(progressLine + "\n");
          notifyTelegram(progressLine.replace(/^\s+/, ""));
        }
        if (
          typeof event.nodeId === "string" &&
          event.nodeId.endsWith(":write") &&
          (event.iteration ?? 0) === 0 &&
          (event.attempt ?? 1) === 1
        ) {
          const parsed = parseChunkNode(event.nodeId);
          if (parsed) {
            const key = `${parsed.sid}:chunk-${parsed.chunkNo}`;
            const ordinal = chunkOrdinalByKey.get(key) ?? parsed.chunkNo;
            const meta = labelBySid.get(parsed.sid);
            const totalChunks = chunkCountBySid.get(parsed.sid) ?? 1;
            const chunkBranches =
              chunkBranchCountsBySid.get(parsed.sid)?.[parsed.chunkNo - 1] ?? 0;
            const totalBranches = branchCountBySid.get(parsed.sid) ?? 0;
            const batchLine =
              `  📦 batch ${ordinal}/${Math.max(totalBatchesPlanned, 1)}: ` +
              `${meta?.contract ?? parsed.sid}.${meta?.fn ?? ""} ` +
              `chunk ${parsed.chunkNo}/${totalChunks} ` +
              `(${chunkBranches}/${totalBranches} branch targets in this batch)`;
            process.stderr.write(batchLine + "\n");
            notifyTelegram(batchLine.replace(/^\s+/, ""));
          }
        }
        break;
      case "NodeFinished": {
        flushAgentRepeat(event.nodeId);
        const nodeId = String(event.nodeId);
        const iter = event.iteration ?? 0;
        const attempt = event.attempt ?? 1;
        const key = nodeAttemptKey(nodeId, iter, attempt);
        const startedAt = nodeStartMsByKey.get(key);
        const took = startedAt ? `, took ${fmtDuration(now - startedAt)}` : "";
        const line = `✓ ${shortNodeLabel(nodeId)} (attempt ${attempt}${took})`;
        process.stderr.write(line + "\n");

        const parsed = parseChunkNode(nodeId);
        if (parsed && startedAt) {
          const chunkKey = `${parsed.sid}:chunk-${parsed.chunkNo}`;
          lastChunkStepDurationByChunk.set(chunkKey, { role: parsed.role, ms: now - startedAt });
        }

        if (event.nodeId.endsWith(":write")) {
          printWriterOutput(event.nodeId, event.iteration ?? 0);
        } else if (event.nodeId.endsWith(":review")) {
          printReviewOutput(event.nodeId, event.iteration ?? 0);
          const reviewMsg = buildReviewTelegramMessage(event.nodeId, event.iteration ?? 0);
          if (reviewMsg) notifyTelegram(reviewMsg);
        }
        break;
      }
      case "NodeFailed":
        {
          flushAgentRepeat(event.nodeId);
          const nodeId = String(event.nodeId);
          const iter = event.iteration ?? 0;
          const attempt = event.attempt ?? 1;
          const key = nodeAttemptKey(nodeId, iter, attempt);
          const startedAt = nodeStartMsByKey.get(key);
          const took = startedAt ? ` after ${fmtDuration(now - startedAt)}` : "";
          const line = `✗ ${shortNodeLabel(nodeId)} (attempt ${attempt})${took}: ${event.error?.message ?? event.error ?? "failed"}`;
          process.stderr.write(line + "\n");
          notifyTelegram(`🛑 ${line}`);

          const parsed = parseChunkNode(nodeId);
          if (parsed && startedAt) {
            const chunkKey = `${parsed.sid}:chunk-${parsed.chunkNo}`;
            lastChunkStepDurationByChunk.set(chunkKey, { role: parsed.role, ms: now - startedAt });
          }
        }
        break;
      case "NodeRetrying":
        {
          flushAgentRepeat(event.nodeId);
          const line = `↻ ${shortNodeLabel(event.nodeId)} retrying (attempt ${event.attempt ?? 1})`;
          process.stderr.write(line + "\n");
          notifyTelegram(`🔁 ${line}`);
        }
        break;
      case "NodeOutput":
        printAgentOutput(event);
        break;
      case "ToolCallStarted":
        if (showAgentOutput) {
          process.stderr.write(
            `    · tool ${shortNodeLabel(event.nodeId)}: ${event.toolName}#${event.seq} started\n`,
          );
        }
        break;
      case "ToolCallFinished":
        if (showAgentOutput) {
          process.stderr.write(
            `    · tool ${shortNodeLabel(event.nodeId)}: ${event.toolName}#${event.seq} ${event.status}\n`,
          );
        }
        break;
      case "RunFinished":
        {
          for (const key of [...agentRepeatByNodeStream.keys()]) {
            const nodeId = key.split(":").slice(0, -1).join(":");
            if (nodeId) flushAgentRepeat(nodeId);
          }
          const line = `✓ Run finished`;
          process.stderr.write(line + "\n");
          const p = getProgress(event.runId);
          notifyTelegram(
            `🏁 run finished\n📊 functions approved ${p.approved}/${scopedTargets.length}, rejected ${p.rejected}`,
          );
        }
        break;
      case "RunFailed":
        {
          for (const key of [...agentRepeatByNodeStream.keys()]) {
            const nodeId = key.split(":").slice(0, -1).join(":");
            if (nodeId) flushAgentRepeat(nodeId);
          }
          const line = `✗ Run failed: ${event.error?.message ?? event.error ?? "unknown"}`;
          process.stderr.write(line + "\n");
          notifyTelegram("🛑 run failed\n" + line);
        }
        break;
    }
  },
});

console.log(JSON.stringify(result, null, 2));
