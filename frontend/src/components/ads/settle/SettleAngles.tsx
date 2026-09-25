import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Skeleton } from "@/components/layout/Skeleton";
import type { SettleRow, SettleView } from "@/lib/adsSettleApi";
import type { ActiveJobsSnapshot } from "@/lib/jobsApi";
import { ActionBar, GradeRules, GradeTermChip, OriginTag, ReadFailed, TagToggle, Thumb, WaitLine } from "../patterns";
import { FROM_META, campaignOf, isImported } from "./settleCsv";

/** F29-I12 step 2 「確認每則主打什麼」 (prototype v10 `stepAngle()`, hash `d/settle/angle`): every ad that will be
 * written gets one angle — the AI's three candidates from its copy (the first preselected, marked ✦) or the user's
 * own words (自訂, 1–12 characters, F27 pause-flow precedent). While the AI still works, one queue-position line
 * (`WaitLine`, from `/api/jobs/active`); a failed read is its own state (`ReadFailed`) and leaves 自訂 only. */

export const ANGLE_MAX = 12;

export type AnglePick = { kind: "candidate"; index: number } | { kind: "custom"; text: string };
export type AnglePicks = Record<string, AnglePick>;

/** The rows that are written to the notebook (划算／太貴／沒賣出, not skipped). */
export const learnRows = (view: SettleView) => view.rows.filter((row) => row.fate !== "skip");

/** The angle a row will be (or was) written with; null while it has none that can be sent. */
export function angleOf(row: SettleRow, pick: AnglePick | undefined): string | null {
  if (row.written_angle) return row.written_angle;
  if (pick?.kind === "custom") {
    const text = pick.text.trim();
    return text && text.length <= ANGLE_MAX ? text : null;
  }
  if (row.angles.status !== "ready") return null;
  return row.angles.candidates[pick?.index ?? 0] ?? null;
}

export type JobsRead = { status: "loading" } | { status: "error" } | { status: "ready"; snapshot: ActiveJobsSnapshot };

/** The queue position of this settle's angle work: the earliest `background.ads_angles` job for one of the pending
 * ads. Not found (just finished, or not listed yet) stays unknown — never 第 0 件. */
function angleJob(jobs: JobsRead, pendingIds: Set<string>) {
  if (jobs.status !== "ready") return null;
  const mine = jobs.snapshot.data
    .filter((job) => (job.kind === "ads_angles" || job.task_name.endsWith("ads_angles")) && pendingIds.has(job.scope.entity_id ?? ""))
    .sort((a, b) => a.position - b.position);
  return mine[0] ? { job: mine[0], total: jobs.snapshot.total } : null;
}

function AngleRow({ row, view, pick, failed, onPick }: {
  row: SettleRow; view: SettleView; pick: AnglePick | undefined; failed: boolean; onPick: (pick: AnglePick) => void;
}) {
  const name = row.name ?? "（未命名廣告）";
  const pending = row.angles.status === "pending" && !failed;
  const ready = row.angles.status === "ready" && row.angles.candidates.length > 0;
  const custom = pick?.kind === "custom";
  const chosen = custom ? -1 : pick?.index ?? 0;
  const readFailed = failed || row.angles.status === "failed";
  return (
    <li className="grid grid-cols-[48px_minmax(0,1fr)] gap-3.5 border-t border-border py-4 first:border-t-0">
      <Thumb url={row.thumbnail_url} size={48} />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {!pending && !readFailed && <GradeTermChip grade={row.grade} label={row.grade_label} />}
          <span className="font-medium [overflow-wrap:anywhere]">{name}</span>
          {!pending && !readFailed && isImported(campaignOf(view, row).origin) && <OriginTag>{FROM_META}</OriginTag>}
        </div>
        {pending ? (
          <div className="mt-2.5 flex flex-wrap gap-2" aria-label="AI 還在整理">
            {["w-[72px]", "w-[96px]", "w-[84px]"].map((w) => <Skeleton key={w} className={`h-8 rounded-full ${w}`} />)}
          </div>
        ) : (
          <>
            {readFailed
              ? <div className="mt-1 text-[13px] text-muted-foreground">讀取失敗，自己填這則主打什麼</div>
              : <div className="mt-1 text-[13px] text-muted-foreground [overflow-wrap:anywhere]">
                  {row.copy_text ? `文案：「${row.copy_text}」` : "這則沒有文案可讀，自己填主打什麼"}
                </div>}
            <div className="mt-2.5 flex flex-wrap items-center gap-2" role="group" aria-label={`${name}主打什麼`}>
              {ready && !readFailed && row.angles.candidates.map((c, i) => (
                <TagToggle key={c} on={chosen === i} onClick={() => onPick({ kind: "candidate", index: i })}>
                  {i === 0 ? "✦ " : ""}{c}
                </TagToggle>
              ))}
              <TagToggle on={custom} onClick={() => onPick({ kind: "custom", text: custom ? pick.text : "" })}>＋ 自訂</TagToggle>
            </div>
            {custom && (
              <Input
                className="mt-2 h-8 max-w-[220px] text-sm" aria-label={`「${name}」的自訂主打`} value={pick.text}
                maxLength={ANGLE_MAX} placeholder={`${ANGLE_MAX} 個字以內`}
                onChange={(e) => onPick({ kind: "custom", text: e.target.value.slice(0, ANGLE_MAX) })}
              />
            )}
          </>
        )}
      </div>
    </li>
  );
}

export function SettleAngles({ view, header, picks, onPick, jobs, onRetry, homeHref, resultHref, noteHref }: {
  view: SettleView; header: ReactNode; picks: AnglePicks; onPick: (entityId: string, pick: AnglePick) => void;
  jobs: JobsRead; onRetry: () => void; homeHref: string; resultHref: string; noteHref: string;
}) {
  const rows = learnRows(view);
  const pendingIds = new Set(rows.filter((row) => row.angles.status === "pending").map((row) => row.entity_id));
  const waiting = pendingIds.size > 0;
  const jobsFailed = waiting && jobs.status === "error";
  const anglesFailed = rows.some((row) => row.angles.status === "failed");
  const missing = rows.filter((row) => angleOf(row, picks[row.entity_id]) === null).length;
  const changed = rows.filter((row) => {
    const pick = picks[row.entity_id];
    return pick && (pick.kind === "custom" || pick.index !== 0);
  }).length;
  const found = angleJob(jobs, pendingIds);
  let hint: string | undefined;
  if (missing === 0) hint = changed ? `你改了 ${changed} 則` : undefined;
  else if (jobsFailed || anglesFailed) hint = "讀取失敗，按上方重試，或自己填";
  else if (waiting) hint = "整理好就能選";
  else hint = `還有 ${missing} 則沒選`;

  return (
    <>
      <div className="flex max-w-[1260px] flex-col gap-4">
        {header}
        {jobsFailed || anglesFailed
          ? <ReadFailed what="AI 整理的主打讀不到；這期的成績都還在，可以自己填" onRetry={onRetry} />
          : waiting
            ? <WaitLine
                title="AI 正在從文案整理主打" status={found?.job.status ?? null} position={found?.job.position ?? null}
                total={found?.total ?? null} waitedSeconds={found?.job.waited_seconds ?? null} note="可以先離開，整理好會出現在首頁待辦"
              />
            : <div className="-mt-2"><GradeRules /></div>}
        <ol aria-label="每則主打什麼" className="surface px-[22px] py-1">
          {rows.map((row) => (
            <AngleRow key={row.entity_id} row={row} view={view} pick={picks[row.entity_id]} failed={jobsFailed}
              onPick={(pick) => onPick(row.entity_id, pick)} />
          ))}
        </ol>
      </div>
      <div className="flex-1" />
      <ActionBar back={{ label: "這期成績", to: resultHref }} exit={{ label: "晚點再結算", to: homeHref }} hint={hint}>
        {missing === 0
          ? <Button asChild><Link to={noteHref}>都對，下一步 →</Link></Button>
          : <Button disabled>都對，下一步 →</Button>}
      </ActionBar>
    </>
  );
}
