import { z } from "zod";

// --- Test matrix schema (the PRD artifact) ---

export const TestCase = z.object({
  name: z.string(),
  status: z.enum(["absent", "compliant", "non_compliant", "redundant"]),
  branchId: z.string(),            // stable id from precomputed branch target
  branchName: z.string(),          // human-readable branch name assigned by writer
  steps: z.array(z.string()),      // empty for redundant
  issues: z.array(z.string()),     // only for non_compliant: what's wrong + how to fix. empty otherwise.
});

export const TestFileEntry = z.object({
  filePath: z.string(),
  method: z.string(),
  cases: z.array(TestCase),
});

export const ContractSection = z.object({
  contractPath: z.string(),
  testDirectory: z.string(),
  functions: z.array(TestFileEntry),
});

export const TestMatrix = z.object({
  version: z.literal("1"),
  sections: z.array(ContractSection),
});

// --- Smithers task schemas ---

export const Target = z.object({
  contractPath: z.string(),
  functionName: z.string(),
  isInternal: z.boolean(),
  expectedTestDirectory: z.string(),
  expectedFilePath: z.string(),
  existingTestFiles: z.array(z.string()),
  branchTargets: z.array(
    z.object({
      id: z.string(),
      kind: z.enum(["default", "branch", "revert", "event"]),
      label: z.string(),
      line: z.number().int().nonnegative(),
    }),
  ),
  scaffoldCases: z.array(
    z.object({
      branchId: z.string(),
      suggestedName: z.string(),
      branchLabel: z.string(),
    }),
  ),
});

export const DiscoveryOutput = z.object({
  targets: z.array(Target),
});

export const WriterOutput = z.object({
  contractPath: z.string(),
  functionName: z.string(),
  entry: TestFileEntry,
});

export const CaseIssue = z.object({
  testCaseName: z.string(),
  branchId: z.string(),
  issue: z.string(),
});

export const ProgrammaticCheckOutput = z.object({
  ok: z.boolean(),
  caseIssues: z.array(CaseIssue),
});

export const JudgeOutput = z.object({
  approved: z.boolean(),
  caseIssues: z.array(CaseIssue),
  summaryIssues: z.array(z.string()),
});

export const ReviewOutput = z.object({
  approved: z.boolean(),
  caseIssues: z.array(CaseIssue),
  summaryIssues: z.array(z.string()),
});

export const IssueMemoryOutput = z.object({
  caseIssues: z.array(CaseIssue),
});
