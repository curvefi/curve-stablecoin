#!/usr/bin/env bun
/**
 * Dump the test matrix from Smithers SQLite DB to markdown.
 * Usage:
 *   bun run workflows/unitary-matrix/dump-matrix.ts
 *   bun run workflows/unitary-matrix/dump-matrix.ts [db-path]
 *   bun run workflows/unitary-matrix/dump-matrix.ts --run-id <run-id>
 *   bun run workflows/unitary-matrix/dump-matrix.ts [db-path] --run-id <run-id>
 */
import { Database } from "bun:sqlite";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../..");
const defaultDb = resolve(ROOT, ".tmp/unitary-matrix-loop.db");

let dbPath = defaultDb;
let requestedRunId: string | null = null;
for (let i = 2; i < process.argv.length; i++) {
  const arg = process.argv[i];
  if (arg === "--run-id") {
    requestedRunId = process.argv[i + 1] ?? null;
    i += 1;
    continue;
  }
  if (!arg.startsWith("--")) {
    dbPath = arg;
  }
}

const db = new Database(dbPath, { readonly: true });

// Find the latest run
const runId = requestedRunId ?? (db.query(`
  SELECT run_id FROM _smithers_runs ORDER BY created_at_ms DESC LIMIT 1
`).get() as { run_id: string } | null)?.run_id;

if (!runId) {
  console.error("No runs found in DB.");
  process.exit(1);
}

if (requestedRunId) {
  const exists = db.query(`SELECT 1 FROM _smithers_runs WHERE run_id = ? LIMIT 1`).get(requestedRunId);
  if (!exists) {
    console.error(`Run not found: ${requestedRunId}`);
    process.exit(1);
  }
}

console.log(`Using run: ${runId}`);

// Get all writer outputs for this run (latest iteration per node)
const rows = db.query(`
  SELECT node_id, iteration, contract_path, function_name, entry
  FROM writer
  WHERE run_id = ?
  ORDER BY node_id, iteration DESC
`).all(runId) as Array<{
  node_id: string;
  iteration: number;
  contract_path: string;
  function_name: string;
  entry: string;
}>;

// Get review statuses for this run
const reviews = db.query(`
  SELECT *
  FROM review
  WHERE run_id = ?
  ORDER BY node_id, iteration DESC
`).all(runId) as Array<{
  node_id: string;
  iteration: number;
  approved: number;
  case_issues?: string;
  caseIssues?: string;
  summary_issues?: string;
  summaryIssues?: string;
  issues?: string;
}>;

const reviewMap = new Map<string, {
  approved: boolean;
  caseIssues: Array<{ testCaseName: string; branchId: string; issue: string }>;
  summaryIssues: string[];
}>();
for (const r of reviews) {
  // key by the write node_id (strip :review, add :write)
  const writeNode = r.node_id.replace(/:review$/, ":write");
  if (!reviewMap.has(writeNode)) {
    const caseIssuesRaw = r.case_issues ?? r.caseIssues ?? "[]";
    const summaryIssuesRaw = r.summary_issues ?? r.summaryIssues ?? r.issues ?? "[]";
    reviewMap.set(writeNode, {
      approved: !!r.approved,
      caseIssues: JSON.parse(caseIssuesRaw),
      summaryIssues: JSON.parse(summaryIssuesRaw),
    });
  }
}

// Deduplicate: latest iteration per node_id
const latest = new Map<string, typeof rows[0]>();
for (const row of rows) {
  if (!latest.has(row.node_id) || row.iteration > latest.get(row.node_id)!.iteration) {
    latest.set(row.node_id, row);
  }
}

// Normalize absolute paths to relative
function relPath(p: string): string {
  if (p.startsWith(ROOT + "/")) return p.slice(ROOT.length + 1);
  return p;
}

type ChunkEntry = { entry: any; nodeId: string };
type FunctionAgg = { functionName: string; filePath: string; chunks: ChunkEntry[] };

// Group by contract -> function (merge chunked entries)
const byContract = new Map<string, Map<string, FunctionAgg>>();
for (const row of latest.values()) {
  const entry = JSON.parse(row.entry);
  entry.filePath = relPath(entry.filePath ?? "");
  const contractKey = relPath(row.contract_path);

  let fnMap = byContract.get(contractKey);
  if (!fnMap) {
    fnMap = new Map<string, FunctionAgg>();
    byContract.set(contractKey, fnMap);
  }

  let agg = fnMap.get(row.function_name);
  if (!agg) {
    agg = {
      functionName: row.function_name,
      filePath: entry.filePath,
      chunks: [],
    };
    fnMap.set(row.function_name, agg);
  }
  agg.filePath = agg.filePath || entry.filePath;
  agg.chunks.push({ entry, nodeId: row.node_id });
}

// Render
const lines: string[] = [];
lines.push("# Unitary Test Matrix");
lines.push("");

const sortedContracts = [...byContract.keys()].sort();
let totalAbsent = 0, totalCompliant = 0, totalNonCompliant = 0, totalRedundant = 0;

for (const contract of sortedContracts) {
  const fnMap = byContract.get(contract)!;
  lines.push(`## \`${contract}\``);
  lines.push("");

  const functions = [...fnMap.values()].sort((a, b) =>
    a.functionName.localeCompare(b.functionName),
  );

  for (const fn of functions) {
    const casesByKey = new Map<string, any>();
    let hasPending = false;
    let hasRejected = false;
    let hasAnyReview = false;

    for (const chunk of fn.chunks) {
      const review = reviewMap.get(chunk.nodeId);
      if (!review) {
        hasPending = true;
      } else {
        hasAnyReview = true;
        if (!review.approved) hasRejected = true;
      }

      for (const c of chunk.entry.cases ?? []) {
        const key = `${c.branchId ?? ""}::${c.name ?? ""}`;
        if (!casesByKey.has(key)) {
          casesByKey.set(key, c);
        }
      }
    }

    const badge = hasPending
      ? " [pending]"
      : hasRejected
        ? " [rejected]"
        : hasAnyReview
          ? " [approved]"
          : " [pending]";

    lines.push(`### \`${fn.filePath}\` — \`${fn.functionName}\`${badge}`);
    lines.push("");

    const cases = [...casesByKey.values()].sort((a, b) => {
      const ab = String(a.branchId ?? "");
      const bb = String(b.branchId ?? "");
      if (ab !== bb) return ab.localeCompare(bb);
      return String(a.name ?? "").localeCompare(String(b.name ?? ""));
    });

    for (const c of cases) {
      const status = c.status ?? "absent";
      const icon = status === "compliant" ? "[x]"
        : status === "redundant" ? "[-]"
        : status === "non_compliant" ? "[!]"
        : "[ ]";

      if (status === "absent") totalAbsent++;
      else if (status === "compliant") totalCompliant++;
      else if (status === "non_compliant") totalNonCompliant++;
      else if (status === "redundant") totalRedundant++;

      const branch = c.branchName
        ? ` *(${c.branchName}${c.branchId ? ` | ${c.branchId}` : ""})*`
        : c.branch
          ? ` *(${c.branch})*`
          : c.branchId
            ? ` *(${c.branchId})*`
            : "";
      lines.push(`- ${icon} \`${c.name}\`${branch}`);
      const steps = c.steps ?? [];
      for (let i = 0; i < steps.length; i++) {
        lines.push(`  - ${i + 1}. ${steps[i]}`);
      }

      if (c.issues && c.issues.length > 0) {
        for (const issue of c.issues) {
          lines.push(`  > ${issue}`);
        }
      }
    }
    lines.push("");
  }
}

lines.push("---");
lines.push("");
lines.push(`**Summary**: ${totalAbsent} absent, ${totalCompliant} compliant, ${totalNonCompliant} non-compliant, ${totalRedundant} redundant`);
lines.push(`**Total entries**: ${functionsCount(byContract)}`);

const md = lines.join("\n") + "\n";
const outPath = resolve(ROOT, "tests/TEST_MATRIX.md");
await Bun.write(outPath, md);
console.log(`Wrote ${outPath} (${functionsCount(byContract)} entries)`);

function functionsCount(map: Map<string, Map<string, FunctionAgg>>): number {
  let n = 0;
  for (const fnMap of map.values()) n += fnMap.size;
  return n;
}
