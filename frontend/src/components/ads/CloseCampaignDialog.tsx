import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/layout/ui/dialog";
import { closeCampaign, CoverageMissingError, type CampaignDetail } from "@/lib/adsApi";
import { Chip } from "./patterns";

/** F40-I06: the close dialog lifted out of `PerformanceTab.tsx` unchanged in behaviour (F37 coverage gap →
 * re-read / skip, error text, 確認結案) so the 成效分頁's 「這期狀態列」 (`detail/PeriodStatusRow.tsx`) and the folded
 * old panel open the same one. The server re-validates every close; this only mirrors its last answer. */

/** F04-I23：結案卡與確認對話框共用同一句，`live` 時都要看到——只宣告一次，不抽成新元件。 */
export const EARLY_CLOSE_SENTENCE = "提前結案會用到目前為止的成效判定，判定後這個 Campaign 不再更新成效";

/** `2026-09-27` → `09/27` (prototype day chips). */
export function shortDay(day: string): string {
  return day.slice(5).replace("-", "/");
}

export function DayChips({ days }: { days: string[] }) {
  return (
    <span className="flex flex-wrap gap-1.5">
      {days.map((day) => <Chip key={day} className="rounded-md px-2 py-0.5">{shortDay(day)}</Chip>)}
    </span>
  );
}

/** F37 資料狀態: the part of the campaign window the platform read has covered. `coverage.start/end`
 * is the window itself (`start_date … min(end_date, org yesterday)`), so trailing unread days are
 * trimmed off before saying 「平台已讀到」; gaps in the middle stay listed by the warning line. */
export function coveredRange(start: string, end: string, missing: string[]): { first: string; last: string } | null {
  const gone = new Set(missing);
  const days: string[] = [];
  for (let t = Date.parse(`${start}T00:00:00Z`); t <= Date.parse(`${end}T00:00:00Z`) && days.length <= 400; t += 86_400_000) {
    days.push(new Date(t).toISOString().slice(0, 10));
  }
  const read = days.filter((day) => !gone.has(day));
  return read.length ? { first: read[0], last: read[read.length - 1] } : null;
}

/** F37 (prototype `#/close`): the close dialog's refusal when the platform read does not cover the
 * window. 缺日 = amber (re-read first, 確認結案 held); 重讀仍失敗 (`can_skip`) = red with the sync error
 * and the explicit skip. The server re-validates every close, so this only mirrors its last answer. */
function CoverageNote({ gap, syncError, syncing, reread, onSync, onSkip, closing }: {
  gap: CoverageMissingError;
  syncError: string | null;
  syncing: boolean;
  reread: boolean;
  onSync?: () => void;
  onSkip: () => void;
  closing: boolean;
}) {
  const n = gap.missing_days.length;
  const syncButton = (label: string) => (
    <Button type="button" variant="outline" size="sm" onClick={() => onSync?.()} disabled={!onSync || syncing || closing}>
      <RefreshCw size={14} className={syncing ? "animate-spin" : "hidden"} />
      {syncing ? "讀取中…" : label}
    </Button>
  );
  if (gap.can_skip) {
    return (
      <div role="alert" className="flex flex-col gap-1.5 rounded-md border border-danger/30 bg-danger/10 p-3 text-sm">
        <b className="font-semibold">重新讀取失敗：{syncError || "上次讀取平台沒有成功；已保留前次資料。"}</b>
        <p className="text-xs">
          {gap.never_synced ? "還沒讀到任何平台資料。" : `仍有 ${n} 天讀不到（${gap.missing_days.map(shortDay).join("、")}）。`}
          可以先跳過這幾天結案，判定會是「看不出」並記下缺的日期。
        </p>
        <div className="flex flex-wrap gap-2">
          {syncButton("再讀一次")}
          <Button type="button" variant="outline" size="sm" onClick={onSkip} disabled={syncing || closing}>
            仍讀不到，跳過缺日結案
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div role="alert" className="flex flex-col gap-1.5 rounded-md border border-warning/30 bg-warning/10 p-3 text-sm">
      <b className="font-semibold">
        {gap.never_synced ? "這個活動還沒讀過平台資料，先讀取再結案。" : `有 ${n} 天還沒讀到平台資料，先補讀再結案。`}
      </b>
      {n > 0 && <DayChips days={gap.missing_days} />}
      <p className="text-xs text-muted-foreground">
        {reread ? "已重新讀取；按「確認結案」再核對一次。" : "缺的日子不會被當成 0；讀到之後這裡會自動放行。"}
      </p>
      <div>{syncButton("重新讀取平台")}</div>
    </div>
  );
}

/** The one close dialog. Mount it only while open (`{open && <CloseCampaignDialog …/>}`) so each opening starts
 * without the previous refusal; it stays mounted across the workspace's quiet reload after a platform read, and a
 * read that ends while it is open (syncing true → false) releases a held 確認結案 for the server to re-check. */
export function CloseCampaignDialog({ brandId, campaign: c, onClose, onCampaignChange, onSync, syncing = false, syncError = "" }: {
  brandId: string;
  campaign: CampaignDetail;
  /** Dismiss (取消, overlay, Escape) and after a successful close. */
  onClose: () => void;
  onCampaignChange: (campaign: CampaignDetail) => void;
  onSync?: () => void;
  syncing?: boolean;
  /** The workspace's last sync failure (job error); the 重讀仍失敗 note shows it. */
  syncError?: string;
}) {
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState<string | null>(null);
  const [coverageGap, setCoverageGap] = useState<CoverageMissingError | null>(null);
  // A platform read finished after the last refusal: 確認結案 is released and the next click
  // re-validates on the server (the server, not this flag, decides).
  const [reread, setReread] = useState(false);

  const wasSyncing = useRef(syncing);
  useEffect(() => {
    if (wasSyncing.current && !syncing) setReread(true);
    wasSyncing.current = syncing;
  }, [syncing]);

  async function handleClose(skipMissing = false) {
    if (c.origin === "imported") return;
    setClosing(true);
    setCloseError(null);
    try {
      const updated = skipMissing
        ? await closeCampaign(brandId, c.id, { skip_missing: true })
        : await closeCampaign(brandId, c.id);
      onCampaignChange(updated);
      setCoverageGap(null);
      onClose();
    } catch (err) {
      if (err instanceof CoverageMissingError) {
        setCoverageGap(err);
        setReread(false);
      } else {
        setCloseError(err instanceof Error ? err.message : "結案失敗，請稍後再試。");
      }
    } finally {
      setClosing(false);
    }
  }

  const observations = (c.context_json.external_sync as { observations?: { error?: unknown } } | undefined)?.observations;
  const lastSyncError = syncError || (typeof observations?.error === "string" ? observations.error : null);
  const confirmHeld = coverageGap !== null && (!reread || syncing);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>結案</DialogTitle>
        <DialogDescription>
          結案後會對照成功條件寫下判定，並在品牌智庫留一條學習，Campaign 之後會被鎖定，不能再改。
          {c.status === "live" && ` ${EARLY_CLOSE_SENTENCE}`}
        </DialogDescription>
        {coverageGap && (
          <CoverageNote gap={coverageGap} syncError={lastSyncError} syncing={syncing} reread={reread}
            onSync={onSync} onSkip={() => void handleClose(true)} closing={closing} />
        )}
        {closeError && <p className="text-sm text-danger">{closeError}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={closing}>
            取消
          </Button>
          <Button type="button" onClick={() => void handleClose()} disabled={closing || confirmHeld}>
            {closing ? "結案中…" : "確認結案"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
