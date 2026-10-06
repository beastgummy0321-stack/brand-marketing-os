import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/layout/ui/dialog";
import { closeCampaign, coverageGapOf, type CampaignDetail, type CoverageGap } from "@/lib/adsApi";
import { getCoordinateLearnings, type CoordinateLearnings } from "@/lib/adsLearningsApi";
import { dayList } from "@/lib/orgClock";
import { Chip } from "./patterns";
import { LearningsTable } from "./learnings/LearningsTable";

/** F40-I06: the close dialog lifted out of `PerformanceTab.tsx` unchanged in behaviour (F37 coverage gap →
 * re-read / skip, error text, 確認結案) so the 成效分頁's 「這期狀態列」 (`detail/PeriodStatusRow.tsx`) and the folded
 * old panel open the same one. The server re-validates every close; this only mirrors its last answer. */

/** F04-I23：結案卡與確認對話框共用同一句，served lifecycle 是 `live` 時都要看到——只宣告一次，不抽成新元件。 */
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
  const read = dayList(start, end, 401).filter((day) => !gone.has(day));
  return read.length ? { first: read[0], last: read[read.length - 1] } : null;
}

/** F37 (prototype `#/close`): the close dialog's refusal when the platform read does not cover the
 * window. 缺日 = amber (re-read first, 確認結案 held); 重讀仍失敗 (`can_skip`) = red with the sync error
 * and the explicit skip. The server re-validates every close, so this only mirrors its last answer. */
function CoverageNote({ gap, syncError, syncing, reread, onSync, onSkip, closing }: {
  gap: CoverageGap;
  syncError: string | null;
  syncing: boolean;
  reread: boolean;
  onSync?: () => void;
  onSkip: () => void;
  closing: boolean;
}) {
  const n = gap.missing_days.length;
  const syncButton = (label: string) => (
    <Button type="button" variant="outline" size="sm" onClick={() => onSync?.()} busy={syncing || closing} disabledReason={!onSync ? "目前無法重新讀取平台" : undefined}>
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
          <Button type="button" variant="outline" size="sm" onClick={onSkip} busy={syncing || closing}>
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

/** F46 exits after a closeout: the brand library's 投放學到的 tab ringed on this campaign, and the create page for the
 * next period (`next.new_campaign_href` of Contract L; the plain create page when the view did not say). */
export function learningsHref(brandId: string, campaignId: string): string {
  return `/brands/${encodeURIComponent(brandId)}/library?tab=ads-learnings&campaign=${encodeURIComponent(campaignId)}`;
}

export function nextPlanHref(brandId: string, view: CoordinateLearnings | null | undefined): string {
  return view?.next?.new_campaign_href ?? `/brands/${encodeURIComponent(brandId)}/ads/new`;
}

/** The two exits (prototype `#/close`: 看學到什麼 outline, 用這些學習排下一期 primary). `onLeave` runs before navigating. */
export function LearningExits({ brandId, campaignId, view, onLeave, size = "default" }: {
  brandId: string;
  campaignId: string;
  view: CoordinateLearnings | null | undefined;
  onLeave?: () => void;
  size?: "default" | "sm";
}) {
  return (
    <>
      <Button asChild variant="outline" size={size}>
        <Link to={learningsHref(brandId, campaignId)} onClick={onLeave}>看學到什麼 →</Link>
      </Button>
      <Button asChild size={size}>
        <Link to={nextPlanHref(brandId, view)} onClick={onLeave}>用這些學習排下一期 →</Link>
      </Button>
    </>
  );
}

type Learned = { status: "ready"; view: CoordinateLearnings } | { status: "error" };

/** Prototype `#/close` result: ✓ 已結案：留下 N 則、換掉 M 則, the served rule line, the ranked rows (compact, headless).
 * An empty campaign prints its `empty_reason`; a failed read says so — the exits stay either way. */
function CloseResult({ learned, campaignId }: { learned: Learned; campaignId: string }) {
  const campaign = learned.status === "ready"
    ? learned.view.campaigns.find((x) => x.campaign_id === campaignId) ?? null
    : null;
  const ranked = campaign !== null && campaign.rows.length > 0 ? campaign : null;
  const title = learned.status === "error"
    ? "已結案，學到的暫時讀不到"
    : ranked ? `已結案：留下 ${ranked.counts.keep} 則、換掉 ${ranked.counts.replace} 則` : "已結案";
  return (
    <>
      <div className="flex items-center gap-3 pr-6">
        <span aria-hidden="true" className="grid size-7 shrink-0 place-items-center rounded-full bg-zone-ok font-bold text-success">✓</span>
        <DialogTitle className="text-lg leading-snug">{title}</DialogTitle>
      </div>
      <DialogDescription data-slot="close-result-note">
        {learned.status === "error"
          ? "活動已鎖定；稍後到品牌智庫「投放學到的」再看這期的排名。"
          : ranked ? ranked.rule_text : (campaign?.empty_reason ?? "這期沒有記學習")}
      </DialogDescription>
      {ranked && <LearningsTable campaign={ranked} compact headless />}
    </>
  );
}

/** The one close dialog. Mount it only while open (`{open && <CloseCampaignDialog …/>}`) so each opening starts
 * without the previous refusal; it stays mounted across the workspace's quiet reload after a platform read, and a
 * read that ends while it is open (syncing true → false) releases a held 確認結案 for the server to re-check.
 * F46: after a successful close it stays open on the result (prototype `#/close`) and reads what was learned
 * (`GET …/coordinate-learnings?campaign_id=`); the closed campaign is handed to the parent, and `onClose` runs, only
 * when the dialog is dismissed (關閉, overlay, Escape or either exit link). */
export function CloseCampaignDialog({ brandId, campaign: c, onClose, onCampaignChange, onSync, syncing = false, syncError = "" }: {
  brandId: string;
  campaign: CampaignDetail;
  /** Dismiss (取消, overlay, Escape), and dismissing the result after a successful close. */
  onClose: () => void;
  /** The closed campaign, handed back when the result is dismissed. */
  onCampaignChange: (campaign: CampaignDetail) => void;
  onSync?: () => void;
  syncing?: boolean;
  /** The workspace's last sync failure (job error); the 重讀仍失敗 note shows it. */
  syncError?: string;
}) {
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState<string | null>(null);
  const [coverageGap, setCoverageGap] = useState<CoverageGap | null>(null);
  // A platform read finished after the last refusal: 確認結案 is released and the next click
  // re-validates on the server (the server, not this flag, decides).
  const [reread, setReread] = useState(false);
  const [done, setDone] = useState<{ campaign: CampaignDetail; learned: Learned } | null>(null);

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
      setCoverageGap(null);
      let learned: Learned;
      try {
        learned = { status: "ready", view: await getCoordinateLearnings(brandId, { campaignId: c.id }) };
      } catch {
        learned = { status: "error" };
      }
      setDone({ campaign: updated, learned });
    } catch (err) {
      const gap = coverageGapOf(err);
      if (gap) {
        setCoverageGap(gap);
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

  if (done) {
    const finish = () => {
      onCampaignChange(done.campaign);
      onClose();
    };
    const view = done.learned.status === "ready" ? done.learned.view : null;
    return (
      <Dialog open onOpenChange={(open) => !open && finish()}>
        {/* The footer has its own 關閉; a second corner 關閉 would be the same exit twice (F47-I02). */}
        <DialogContent showCloseButton={false} className="max-h-[calc(100dvh-24px)] gap-3.5 overflow-auto bg-card sm:max-w-[560px]" data-step="result">
          <CloseResult learned={done.learned} campaignId={c.id} />
          <DialogFooter className="mt-1">
            <Button type="button" variant="ghost" onClick={finish}>關閉</Button>
            <LearningExits brandId={brandId} campaignId={c.id} view={view} onLeave={finish} />
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !closing && onClose()}>
      <DialogContent className="bg-card sm:max-w-[560px]">
        <DialogTitle>結案</DialogTitle>
        <DialogDescription className="text-foreground">
          {/* F48-I11: no count — the planned ads are not the platform ads closeout ranks, and that count is not on
              this payload. */}
          結案後會把這期的廣告照每筆成本排名、判定留下或換掉，寫進品牌智庫「投放學到的」。活動之後鎖定，不能再改。
          {c.lifecycle?.state === "live" && ` ${EARLY_CLOSE_SENTENCE}`}
        </DialogDescription>
        {coverageGap && (
          <CoverageNote gap={coverageGap} syncError={lastSyncError} syncing={syncing} reread={reread}
            onSync={onSync} onSkip={() => void handleClose(true)} closing={closing} />
        )}
        {closeError && <p className="text-sm text-danger">{closeError}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} busy={closing}>
            取消
          </Button>
          <Button type="button" onClick={() => void handleClose()} busy={closing || syncing} disabledReason={confirmHeld ? "先重新讀取缺少的日期，或確認略過" : undefined}>
            {closing ? "結案中…" : "確認結案"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
