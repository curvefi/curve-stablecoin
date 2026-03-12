/** @jsxImportSource smithers-orchestrator */
import { Sequence, Ralph } from "smithers-orchestrator";
import { Workflow, Task, smithers, outputs } from "./smithers";
import { BRANCH_CHUNK_SIZE, MAX_REVIEW_ROUNDS, discoverTargets } from "./config";
import { writer, judge } from "./agents";
import WriterTaskPrompt from "./prompts/writer-task.mdx";
import JudgeTaskPrompt from "./prompts/judge-task.mdx";

type CaseIssue = {
  testCaseName: string;
  branchId: string;
  issue: string;
};

function sanitizeId(contractPath: string, functionName: string): string {
  return `${contractPath}:${functionName}`.replace(/[^a-z0-9]/gi, "-").toLowerCase();
}

function chunkBySize<T>(items: T[], size: number): T[][] {
  if (size <= 0) return [items];
  const chunks: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    chunks.push(items.slice(i, i + size));
  }
  return chunks;
}

function dedupeCaseIssues(issues: CaseIssue[]): CaseIssue[] {
  const seen = new Set<string>();
  const out: CaseIssue[] = [];
  for (const i of issues) {
    const key = `${i.testCaseName}::${i.branchId}::${i.issue}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(i);
  }
  return out;
}

function dedupeStrings(items: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of items) {
    if (seen.has(item)) continue;
    seen.add(item);
    out.push(item);
  }
  return out;
}

export default smithers((ctx) => {
  const discovery = ctx.outputMaybe("discovery", { nodeId: "discover-targets" });
  const targets = discovery?.targets ?? [];

  return (
    <Workflow name="unitary-matrix-loop">
      <Sequence>
        <Task id="discover-targets" output={outputs.discovery}>
          {() => {
            const all = discoverTargets();
            const contractPath =
              typeof ctx.input.contractPath === "string" ? ctx.input.contractPath : "";
            const functionName =
              typeof ctx.input.functionName === "string" ? ctx.input.functionName : "";
            const targets = all.filter((t) => {
              if (contractPath && t.contractPath !== contractPath) return false;
              if (functionName && t.functionName !== functionName) return false;
              return true;
            });
            return { targets };
          }}
        </Task>

        {targets.map((target) => {
          const { contractPath, functionName } = target;
          const sid = sanitizeId(contractPath, functionName);
          const chunks = chunkBySize(target.branchTargets, BRANCH_CHUNK_SIZE);

          return (
            <Sequence key={sid}>
              {chunks.map((chunkBranchTargets, chunkIdx) => {
                const chunkNo = chunkIdx + 1;
                const chunkId = `${sid}:chunk-${chunkNo}`;
                const writeId = `${chunkId}:write`;
                const reviewId = `${chunkId}:review`;
                const programmaticCheckId = `${chunkId}:programmatic-check`;
                const judgeRawId = `${chunkId}:judge-raw`;
                const issueMemoryId = `${chunkId}:issue-memory`;

                const latestWriter = ctx.latest("writer", writeId);
                const latestReview = ctx.latest("review", reviewId);
                const latestIssueMemory = ctx.latest("issueMemory", issueMemoryId);

                const branchIdSet = new Set(chunkBranchTargets.map((b) => b.id));
                const chunkScaffoldCases = target.scaffoldCases.filter((c) =>
                  branchIdSet.has(c.branchId),
                );

                const previousChunkExamples = chunks
                  .slice(0, chunkIdx)
                  .map((_, prevIdx) =>
                    ctx.latest("writer", `${sid}:chunk-${prevIdx + 1}:write`),
                  )
                  .filter((x): x is NonNullable<typeof x> => Boolean(x));

                return (
                  <Ralph
                    key={chunkId}
                    id={`${chunkId}:loop`}
                    until={latestReview?.approved === true}
                    maxIterations={MAX_REVIEW_ROUNDS}
                    onMaxReached="return-last"
                  >
                    <Sequence>
                      <Task id={writeId} output={outputs.writer} agent={writer} retries={2}>
                        <WriterTaskPrompt
                          target={target}
                          chunkIndex={chunkNo}
                          totalChunks={chunks.length}
                          chunkBranchTargets={chunkBranchTargets}
                          chunkScaffoldCases={chunkScaffoldCases}
                          previousChunkExamples={previousChunkExamples}
                          previousOutput={latestWriter ?? null}
                          reviewFeedback={
                            latestIssueMemory ??
                            (latestReview?.approved === false
                              ? { caseIssues: latestReview.caseIssues }
                              : null)
                          }
                        />
                      </Task>

                      <Task id={programmaticCheckId} output={outputs.programmaticCheck}>
                        {() => {
                          const currentWriter = ctx.latest("writer", writeId);
                          const cases = currentWriter?.entry?.cases ?? [];
                          const allowed = new Set(chunkBranchTargets.map((b) => b.id));
                          const expected = [...allowed.values()];

                          const caseIssues: CaseIssue[] = [];
                          const branchUseCount = new Map<string, number>();

                          for (const c of cases) {
                            const name = typeof c.name === "string" ? c.name : "<unnamed-case>";
                            const branchId =
                              typeof c.branchId === "string" && c.branchId.length > 0
                                ? c.branchId
                                : "<missing-branch-id>";

                            if (!allowed.has(branchId)) {
                              caseIssues.push({
                                testCaseName: name,
                                branchId,
                                issue:
                                  "branchId is not part of this chunk's branch targets; use only precomputed chunk branch IDs",
                              });
                              continue;
                            }

                            branchUseCount.set(branchId, (branchUseCount.get(branchId) ?? 0) + 1);
                          }

                          for (const branchId of expected) {
                            if (!branchUseCount.has(branchId)) {
                              caseIssues.push({
                                testCaseName: `<missing:${branchId}>`,
                                branchId,
                                issue: "missing coverage for required chunk branch target",
                              });
                            }
                          }

                          for (const [branchId, count] of branchUseCount.entries()) {
                            if (count <= 1) continue;
                            for (const c of cases) {
                              if (c.branchId !== branchId) continue;
                              caseIssues.push({
                                testCaseName: c.name,
                                branchId,
                                issue:
                                  "duplicate branch coverage in this chunk; keep one case and mark duplicates as redundant",
                              });
                            }
                          }

                          const finalIssues = dedupeCaseIssues(caseIssues);
                          return {
                            ok: finalIssues.length === 0,
                            caseIssues: finalIssues,
                          };
                        }}
                      </Task>

                      <Task id={judgeRawId} output={outputs.judgeRaw} agent={judge} retries={2}>
                        <JudgeTaskPrompt
                          target={target}
                          chunkIndex={chunkNo}
                          totalChunks={chunks.length}
                          chunkBranchTargets={chunkBranchTargets}
                          writerOutput={latestWriter ?? null}
                        />
                      </Task>

                      <Task id={reviewId} output={outputs.review}>
                        {() => {
                          const prog = ctx.latest("programmaticCheck", programmaticCheckId);
                          const judgeOut = ctx.latest("judgeRaw", judgeRawId);

                          const progCaseIssues = prog?.caseIssues ?? [];
                          const judgeCaseIssues = judgeOut?.caseIssues ?? [];
                          const caseIssues = dedupeCaseIssues([
                            ...progCaseIssues,
                            ...judgeCaseIssues,
                          ]);

                          const summaryIssues = dedupeStrings([
                            ...(prog?.ok === false
                              ? [
                                  "programmatic chunk checks failed: branch coverage must be complete, in-chunk only, and non-duplicated",
                                ]
                              : []),
                            ...(judgeOut?.summaryIssues ?? []),
                          ]);

                          const approved = Boolean(
                            prog?.ok === true && judgeOut?.approved === true,
                          );

                          return {
                            approved,
                            caseIssues,
                            summaryIssues,
                          };
                        }}
                      </Task>

                      <Task id={issueMemoryId} output={outputs.issueMemory}>
                        {() => {
                          const previous =
                            ctx.latest("issueMemory", issueMemoryId)?.caseIssues ?? [];
                          const current =
                            ctx.latest("review", reviewId)?.approved === false
                              ? (ctx.latest("review", reviewId)?.caseIssues ?? [])
                              : [];
                          return {
                            caseIssues: dedupeCaseIssues([...previous, ...current]),
                          };
                        }}
                      </Task>
                    </Sequence>
                  </Ralph>
                );
              })}
            </Sequence>
          );
        })}
      </Sequence>
    </Workflow>
  );
});
