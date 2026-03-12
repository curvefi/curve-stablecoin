import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../..");

export const MAX_REVIEW_ROUNDS = 4;
export const AGENT_TIMEOUT_MS = 30 * 60 * 1000;
export const BRANCH_CHUNK_SIZE = 5;

export type BranchTarget = {
  id: string;
  kind: "default" | "branch" | "revert" | "event";
  label: string;
  line: number;
};

export type ScaffoldCase = {
  branchId: string;
  suggestedName: string;
  branchLabel: string;
};

export type Target = {
  contractPath: string;
  functionName: string;
  isInternal: boolean;
  expectedTestDirectory: string;
  expectedFilePath: string;
  existingTestFiles: string[];
  branchTargets: BranchTarget[];
  scaffoldCases: ScaffoldCase[];
};

type FunctionDef = {
  name: string;
  isInternal: boolean;
  startLine: number;
  endLine: number;
};

type TestFile = {
  path: string;
  fileName: string;
  dir: string;
};

type DirectoryProfile = {
  dir: string;
  suffix: string;
};

const DIRECTORY_OVERRIDES: Record<string, DirectoryProfile> = {
  "curve_stablecoin/AMM.vy": { dir: "tests/unitary/controller", suffix: "c" },
  "curve_stablecoin/controller.vy": {
    dir: "tests/unitary/controller",
    suffix: "c",
  },
  "curve_stablecoin/ControllerFactory.vy": {
    dir: "tests/unitary/controller",
    suffix: "c",
  },
  "curve_stablecoin/ControllerView.vy": {
    dir: "tests/unitary/controller_view",
    suffix: "c",
  },
  "curve_stablecoin/lending/LendController.vy": {
    dir: "tests/unitary/lending/lend_controller",
    suffix: "lc",
  },
  "curve_stablecoin/lending/LendFactory.vy": {
    dir: "tests/unitary/lending/lend_factory",
    suffix: "lf",
  },
  "curve_stablecoin/lending/Vault.vy": {
    dir: "tests/unitary/lending/vault",
    suffix: "v",
  },
  "curve_stablecoin/lending/blueprint_registry.vy": {
    dir: "tests/unitary/lib/blueprint_registry",
    suffix: "br",
  },
  "curve_stablecoin/mpolicies/AggMonetaryPolicy4.vy": {
    dir: "tests/unitary/mpolicies/agg_monetary_policy4",
    suffix: "amp4",
  },
};

function camelToSnake(name: string): string {
  const s1 = name.replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2");
  return s1.replace(/([a-z\d])([A-Z])/g, "$1_$2").toLowerCase();
}

function normalizeMethodName(methodName: string): string {
  if (methodName === "__init__") return "init";
  if (methodName === "__default__") return "default";
  return camelToSnake(methodName.replace(/^_+/, "")).replace(/_+$/, "");
}

function computeContractSuffix(contractSnake: string): string {
  const parts: string[] = [];
  for (const chunk of contractSnake.split("_")) {
    if (!chunk) continue;
    const letters = chunk.replace(/[^a-zA-Z]/g, "");
    const digits = chunk.replace(/[^0-9]/g, "");
    if (letters) parts.push(letters[0] + digits);
    else if (digits) parts.push(digits);
  }
  const suffix = parts.join("");
  return suffix || contractSnake.slice(0, 3);
}

function discoverContractFiles(): string[] {
  const contractsDir = resolve(ROOT, "curve_stablecoin");
  const files: string[] = [];

  function walk(dir: string) {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      try {
        if (statSync(full).isDirectory()) {
          if (entry === "interfaces" || entry === "testing") continue;
          walk(full);
        } else if (entry.endsWith(".vy") && entry !== "constants.vy") {
          files.push(relative(ROOT, full));
        }
      } catch {
        // ignore unreadable entries
      }
    }
  }

  walk(contractsDir);
  return files.sort();
}

function extractTargetFunctions(contractAbsPath: string): FunctionDef[] {
  const src = readFileSync(contractAbsPath, "utf-8");
  const lines = src.split("\n");

  const defs: Array<{ name: string; startLine: number; isTarget: boolean; isInternal: boolean }> = [];

  let pendingExternal = false;
  let pendingInternal = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const trimmed = line.trim();

    if (trimmed.startsWith("@external")) {
      pendingExternal = true;
      continue;
    }
    if (trimmed.startsWith("@internal")) {
      pendingInternal = true;
      continue;
    }
    if (trimmed.startsWith("@")) {
      continue;
    }

    const m = trimmed.match(/^def\s+(\w+)\s*\(/);
    if (m) {
      const name = m[1]!;
      const isExternal = pendingExternal;
      const isInternal = pendingInternal;
      const isTarget =
        name !== "__init__" &&
        name !== "__default__" &&
        (isExternal || isInternal);
      defs.push({
        name,
        startLine: i + 1,
        isTarget,
        isInternal,
      });
      pendingExternal = false;
      pendingInternal = false;
      continue;
    }

    if (trimmed !== "") {
      pendingExternal = false;
      pendingInternal = false;
    }
  }

  const out: FunctionDef[] = [];
  for (let i = 0; i < defs.length; i++) {
    const cur = defs[i]!;
    const next = defs[i + 1];
    if (!cur.isTarget) continue;
    out.push({
      name: cur.name,
      isInternal: cur.isInternal,
      startLine: cur.startLine,
      endLine: (next?.startLine ?? lines.length + 1) - 1,
    });
  }
  return out;
}

function collectBranchTargets(srcLines: string[], fn: FunctionDef): BranchTarget[] {
  let branchCount = 0;
  let revertCount = 0;
  let eventCount = 0;

  const targets: BranchTarget[] = [
    {
      id: `default-${fn.startLine}`,
      kind: "default",
      label: "Default execution path",
      line: fn.startLine,
    },
  ];

  for (let lineNo = fn.startLine + 1; lineNo <= fn.endLine; lineNo++) {
    const raw = srcLines[lineNo - 1] ?? "";
    const trimmed = raw.trim();
    if (!trimmed) continue;

    if (
      trimmed.startsWith("if ") ||
      trimmed.startsWith("elif ") ||
      trimmed.startsWith("else:")
    ) {
      branchCount += 1;
      targets.push({
        id: `branch-${lineNo}-${branchCount}`,
        kind: "branch",
        label: trimmed,
        line: lineNo,
      });
    }
    if (trimmed.startsWith("assert ") || trimmed.startsWith("raise ")) {
      revertCount += 1;
      targets.push({
        id: `revert-${lineNo}-${revertCount}`,
        kind: "revert",
        label: trimmed,
        line: lineNo,
      });
    }
    if (/\blog\s+/.test(trimmed)) {
      eventCount += 1;
      targets.push({
        id: `event-${lineNo}-${eventCount}`,
        kind: "event",
        label: trimmed,
        line: lineNo,
      });
    }
  }

  return targets;
}

function buildScaffoldCases(branchTargets: BranchTarget[]): ScaffoldCase[] {
  const cases: ScaffoldCase[] = [];

  for (const t of branchTargets) {
    if (t.kind === "default") {
      cases.push({
        branchId: t.id,
        suggestedName: "test_default_behavior",
        branchLabel: t.label,
      });
    } else if (t.kind === "branch") {
      cases.push({
        branchId: t.id,
        suggestedName: `test_default_behavior_branch_${t.line}`,
        branchLabel: t.label,
      });
    } else if (t.kind === "revert") {
      cases.push({
        branchId: t.id,
        suggestedName: `test_revert_branch_${t.line}`,
        branchLabel: t.label,
      });
    } else if (t.kind === "event") {
      cases.push({
        branchId: t.id,
        suggestedName: `test_default_behavior_event_${t.line}`,
        branchLabel: t.label,
      });
    }
  }

  return cases;
}

function listUnitaryTestFiles(): TestFile[] {
  const root = resolve(ROOT, "tests/unitary");
  const files: TestFile[] = [];

  function walk(dir: string) {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      try {
        if (statSync(full).isDirectory()) {
          if (entry === "__pycache__" || entry === ".pytest_cache") continue;
          walk(full);
        } else if (entry.endsWith(".py") && entry.startsWith("test_")) {
          const rel = relative(ROOT, full);
          files.push({
            path: rel,
            fileName: entry,
            dir: relative(ROOT, dirname(full)),
          });
        }
      } catch {
        // ignore unreadable entries
      }
    }
  }

  walk(root);
  return files.sort((a, b) => a.path.localeCompare(b.path));
}

function methodMatchesTestFile(
  methodName: string,
  isInternal: boolean,
  testFileName: string,
): boolean {
  const normalized = normalizeMethodName(methodName);
  const stem = testFileName.replace(/\.py$/, "");
  const aliases = normalized === "init" ? [normalized, "ctor"] : [normalized];

  for (const alias of aliases) {
    const pat = isInternal
      ? new RegExp(`^test_internal_(?:[a-z0-9_]+_)?${alias}(?:_[a-z0-9]+)*$`)
      : new RegExp(`^test_(?!internal_)(?:[a-z0-9_]+_)?${alias}(?:_[a-z0-9]+)*$`);
    if (pat.test(stem)) return true;
  }
  return false;
}

function parseSuffixFromMatchedFile(
  methodName: string,
  isInternal: boolean,
  testFileName: string,
): string | null {
  const normalized = normalizeMethodName(methodName);
  const stem = testFileName.replace(/\.py$/, "");
  const aliases = normalized === "init" ? [normalized, "ctor"] : [normalized];

  for (const alias of aliases) {
    const re = isInternal
      ? new RegExp(`^test_internal_(?:[a-z0-9_]+_)?${alias}(?:_([a-z0-9]+))?$`)
      : new RegExp(`^test_(?!internal_)(?:[a-z0-9_]+_)?${alias}(?:_([a-z0-9]+))?$`);
    const m = stem.match(re);
    if (m) return m[1] ?? null;
  }
  return null;
}

function fallbackTestDirectory(contractPath: string): string {
  const parts = contractPath.split("/");
  const withoutRoot = parts[0] === "curve_stablecoin" ? parts.slice(1) : parts;
  const base = withoutRoot[withoutRoot.length - 1]!.replace(/\.vy$/, "");
  const snake = camelToSnake(base);
  if (withoutRoot.length > 1) {
    return `tests/unitary/${withoutRoot.slice(0, -1).join("/")}/${snake}`;
  }
  return `tests/unitary/${snake}`;
}

function mostCommon(items: string[]): string | null {
  if (items.length === 0) return null;
  const counts = new Map<string, number>();
  for (const item of items) {
    counts.set(item, (counts.get(item) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]![0];
}

export function discoverTargets(): Target[] {
  const contracts = discoverContractFiles();
  const tests = listUnitaryTestFiles();
  const targets: Target[] = [];

  for (const contractPath of contracts) {
    const contractAbs = resolve(ROOT, contractPath);
    const src = readFileSync(contractAbs, "utf-8");
    const srcLines = src.split("\n");
    const fns = extractTargetFunctions(contractAbs);

    const override = DIRECTORY_OVERRIDES[contractPath];
    const contractSnake = camelToSnake(
      contractPath.split("/").pop()!.replace(/\.vy$/, ""),
    );
    const fallbackDir = fallbackTestDirectory(contractPath);
    const fallbackSuffix = computeContractSuffix(contractSnake);
    const baseDir = override?.dir ?? fallbackDir;
    const baseSuffix = override?.suffix ?? fallbackSuffix;
    const scopedTests = tests.filter((t) => t.dir === baseDir);

    const perFnMatches = new Map<string, TestFile[]>();
    for (const fn of fns) {
      const matches = scopedTests.filter((t) =>
        methodMatchesTestFile(fn.name, fn.isInternal, t.fileName),
      );
      perFnMatches.set(fn.name, matches);
    }

    const allMatches = fns.flatMap((fn) => perFnMatches.get(fn.name) ?? []);
    const profileDir = mostCommon(allMatches.map((m) => m.dir)) ?? baseDir;

    const suffixCandidates: string[] = [];
    for (const fn of fns) {
      for (const m of perFnMatches.get(fn.name) ?? []) {
        const suffix = parseSuffixFromMatchedFile(fn.name, fn.isInternal, m.fileName);
        if (suffix) suffixCandidates.push(suffix);
      }
    }
    const profileSuffix = mostCommon(suffixCandidates) ?? baseSuffix;

    for (const fn of fns) {
      const normalized = normalizeMethodName(fn.name);
      const matches = (perFnMatches.get(fn.name) ?? []).sort((a, b) =>
        a.path.localeCompare(b.path),
      );

      const exactPreferred =
        matches.find((m) => {
          if (fn.isInternal) {
            return (
              m.fileName === `test_internal_${normalized}.py` ||
              m.fileName.startsWith(`test_internal_${normalized}_`)
            );
          }
          return (
            m.fileName === `test_${normalized}.py` ||
            m.fileName.startsWith(`test_${normalized}_`)
          );
        }) ?? matches[0];

      const expectedFilePath = exactPreferred
        ? exactPreferred.path
        : fn.isInternal
          ? `${profileDir}/test_internal_${normalized}_${profileSuffix}.py`
          : `${profileDir}/test_${normalized}_${profileSuffix}.py`;

      const branchTargets = collectBranchTargets(srcLines, fn);
      const scaffoldCases = buildScaffoldCases(branchTargets);

      targets.push({
        contractPath,
        functionName: fn.name,
        isInternal: fn.isInternal,
        expectedTestDirectory: dirname(expectedFilePath).replace(/\\/g, "/"),
        expectedFilePath: expectedFilePath.replace(/\\/g, "/"),
        existingTestFiles: matches.map((m) => m.path),
        branchTargets,
        scaffoldCases,
      });
    }
  }

  return targets.sort((a, b) =>
    a.contractPath === b.contractPath
      ? a.functionName.localeCompare(b.functionName)
      : a.contractPath.localeCompare(b.contractPath),
  );
}
