import { useEffect } from "react";
import { Link } from "react-router-dom";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { formatSyncTime } from "@/lib/format";
import { getCampaignTimeline, type TimelineRow, type TimelineState } from "@/lib/adsWorkspaceApi";
import { useApiRead } from "@/lib/useApiRead";
import { ChangeTimeline, ReadFailed, type ChangeRow } from "../patterns";
import { changeStepPath, type FlowStepName } from "../flow/changeFlow";

/** v10 (F30-I09) the workspace changes tab (prototype `tabChanges()`): one card 「變更紀錄」 with every change set of the
 * campaign from `GET …/timeline` (Contract E), newest first, on the kit `ChangeTimeline` — the state chip, 「原因：…」 on a
 * rejected set, x／N 已核對 with `ProgressSegments`. Times print browser-local `MM/DD HH:mm` (`formatSyncTime`, the same
 * clock as 最近同步). A set with work left opens its existing step page (`changes/:id/confirm|handoff|verify`); a rejected
 * set has nothing to open. Sets those pages do not render (launches, multi-item sets — the caller decides through
 * `inFold`) open in the caller's advanced fold instead. A failed read is `ReadFailed` with 重試, never an empty list. */

const CARD = "surface px-[22px] py-5";

/** Which existing step page a set in this state belongs on (prototype `go`: 等核對 → 核對, 等你到平台完成 → 到平台完成). */
const STEP: Record<TimelineState, FlowStepName | null> = {
  draft: "confirm", platform: "handoff", check: "verify", verified: "verify", stale: "verify", rejected: null,
};

export function ChangesTab({ brandId, campaignId, refreshKey = 0, inFold, onOpenInFold }: {
  brandId: string;
  campaignId: string;
  /** Bumped by the caller after a change it made (approve, report, a new set); re-reads keeping the rows on screen. */
  refreshKey?: number;
  /** True for a set the step pages cannot show; its 打開 calls `onOpenInFold` instead of navigating. */
  inFold?: (row: TimelineRow) => boolean;
  onOpenInFold?: (row: TimelineRow) => void;
}) {
  const read = useApiRead((signal) => getCampaignTimeline(brandId, campaignId, signal), [brandId, campaignId]);
  const { reload } = read;
  useEffect(() => { if (refreshKey) reload(); }, [refreshKey, reload]);

  function action(row: TimelineRow) {
    const step = STEP[row.state];
    if (!step) return undefined;
    const label = row.state === "check" ? "去核對" : "打開";
    if (onOpenInFold && inFold?.(row)) {
      return <Button variant="outline" size="sm" aria-label={`${label}：${row.title}`} onClick={() => onOpenInFold(row)}>{label}</Button>;
    }
    return (
      <Button asChild variant="outline" size="sm">
        <Link to={changeStepPath(brandId, campaignId, row.change_set_id, step)} aria-label={`${label}：${row.title}`}>{label}</Link>
      </Button>
    );
  }

  let body;
  if (read.status === "error") {
    body = <ReadFailed what="變更紀錄讀不到；已核准的變更與平台設定都不受影響。" onRetry={reload} />;
  } else if (!read.data) {
    body = <Skeleton className="h-40 w-full" />;
  } else if (read.data.rows.length === 0) {
    body = <p className="text-sm text-muted-foreground">這個活動還沒有變更</p>;
  } else {
    const rows: ChangeRow[] = read.data.rows.map((row) => ({
      key: row.change_set_id,
      at: formatSyncTime(row.at),
      title: row.title,
      state: row.state,
      reason: row.state === "rejected" ? row.reason : null,
      checked: row.checked,
      total: row.total,
      action: action(row),
    }));
    body = (
      <>
        <ChangeTimeline rows={rows} />
        {read.data.truncated && (
          <p className="mt-4 text-xs text-muted-foreground">只列出最近 {rows.length} 批，更早的變更沒有顯示。</p>
        )}
      </>
    );
  }

  return (
    <section className={CARD} aria-labelledby="changes-timeline">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 id="changes-timeline" className="text-[15px] font-semibold">變更紀錄</h2>
        <span className="text-sm text-muted-foreground">每一批都要到平台完成，再讀回核對</span>
      </div>
      {body}
    </section>
  );
}
