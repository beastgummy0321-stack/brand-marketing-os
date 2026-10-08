import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import { getCoordinateLearnings, type CoordinateLearnings } from "@/lib/adsLearningsApi";
import { ReadFailed } from "../patterns/ReadFailed";
import { figure, useAdsRules } from "../patterns/rules";
import { GroupSummary } from "./GroupSummary";
import { LearningsTable } from "./LearningsTable";
import {Disclosure, formatAmount} from "../patterns";
import {QualifiedLearningList} from "./QualifiedLearningList";
import {useLearningScope} from "./useLearningScope";

export type LearningsLoad =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: CoordinateLearnings; refreshing?: boolean; error?: string };

/** One read of Contract L for the brand. The host owns it so a sub-nav count can show once read. */
export function useCoordinateLearnings(brandId: string): { state: LearningsLoad; reload: () => void } {
  const [state, setState] = useState<LearningsLoad>({ status: "loading" });
  const [round, setRound] = useState(0);
  const saved = useRef<{brandId: string; data: CoordinateLearnings} | null>(null);
  const [owner, setOwner] = useState(brandId);
  useEffect(() => {
    const ctrl = new AbortController();
    const previous = saved.current?.brandId === brandId ? saved.current.data : null;
    setOwner(brandId);
    setState(previous ? {status: "ready", data: previous, refreshing: true} : { status: "loading" });
    getCoordinateLearnings(brandId, {}, ctrl.signal)
      .then((data) => {
        if (ctrl.signal.aborted) return;
        saved.current = {brandId, data};
        setState({ status: "ready", data });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        const message = err instanceof Error ? err.message : "讀取失敗，請稍後再試。";
        setState(previous ? {status: "ready", data: previous, error: message} : { status: "error", message });
      });
    return () => ctrl.abort();
  }, [brandId, round]);
  const reload = useCallback(() => setRound((n) => n + 1), []);
  return { state: owner === brandId ? state : {status: "loading"}, reload };
}

/** Ranked rows across every listed campaign: the 投放學到的 sub-nav count. */
export function learningsCount(data: CoordinateLearnings): number {
  return data.campaigns.reduce((sum, c) => sum + c.rows.length, 0);
}

function Heading({ action }: { action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="text-[25px] font-semibold">投放學到的</h2>
        <p className="mt-1 text-[13px] text-muted-foreground">查看能用來規劃下一期的經驗與適用範圍。</p>
      </div>
      {action}
    </div>
  );
}

/** 品牌智庫 → 「投放學到的」 (prototype f46-learnings `#/library`): header + 「用這些學習排下一期 →」, the 怎麼判 rule
 * strip, 各顧客群 summary, then one ranked table per closed campaign (newest first). `highlightCampaignId` (the
 * closeout's 「看學到什麼 →」 lands with `?campaign=`) rings that table and scrolls to it. A failed read is its own
 * state with 重新讀取, never the empty state. */
export function LearningsTab({ brandId, state, onRetry, highlightCampaignId }: {
  brandId: string;
  state: LearningsLoad;
  onRetry: () => void;
  highlightCampaignId?: string | null;
}) {
  const ready = state.status === "ready";
  const scope = useLearningScope(brandId, ready ? state.data : null);
  const [rankOpen, setRankOpen] = useState(false);
  const located = useRef<string | null>(null);
  const validHighlight = ready && state.data.campaigns.some(c => c.campaign_id === highlightCampaignId) ? highlightCampaignId : null;
  const rules = useAdsRules();
  useEffect(() => {
    if (validHighlight && located.current !== validHighlight) setRankOpen(true);
  }, [validHighlight]);
  useEffect(() => {
    if (!rankOpen || !validHighlight || located.current === validHighlight) return;
    const frame = requestAnimationFrame(() => {
      const element = document.getElementById(`camp-${validHighlight}`);
      if (element) {
        element.scrollIntoView?.({block: "start"});
        located.current = validHighlight;
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [rankOpen, validHighlight]);

  if (state.status === "loading") {
    return (
      <div aria-label="投放學到的讀取中" className="flex flex-col gap-4">
        <Skeleton className="h-10 w-1/2" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-24" />
        <Skeleton className="h-40" />
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="flex flex-col gap-[18px]">
        <Heading />
        <ReadFailed what={`投放學到的讀不到（${state.message}）；結案記下的排名沒有遺失。`} onRetry={onRetry} retryLabel="重新讀取" />
      </div>
    );
  }
  const { campaigns, groups } = state.data;
  const evidence = scope.data;
  const next = scope.product && evidence && !scope.busy && !scope.optionsError && !scope.error
    ? evidence.next?.sell_way_id === scope.product.id ? evidence.next.new_campaign_href
      : `/brands/${encodeURIComponent(brandId)}/ads/new?sell_way=${encodeURIComponent(scope.product.id)}`
    : null;
  const retry = () => { onRetry(); scope.reload(); };
  // The 怎麼判 strip names how one campaign was judged — the highlighted one (from a closeout), else the newest with
  // ranked rows — in its served `rule_text`, then the brand-wide sample flag from the served rules.
  const focus = campaigns.find((c) => c.campaign_id === highlightCampaignId && c.rule_text)
    ?? campaigns.find((c) => c.rule_text) ?? null;
  const adsHome = `/brands/${encodeURIComponent(brandId)}/ads`;
  return (
    <div data-slot="learning-screen" className="flex min-w-0 flex-col gap-5">
      <Heading
        action={next ? <Button asChild><Link to={next}>用可參考資料規劃下一期 →</Link></Button>
          : <Button disabledReason={scope.busy ? "正在核對商品與歷史" : "先選擇有效商品，並重新讀取可參考範圍"}>用可參考資料規劃下一期 →</Button>}
      />
      <div className="surface flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-[13px] text-muted-foreground">
        <span>目前商品 <b className="text-foreground">{scope.product?.name ?? "請先選擇商品範圍"}</b></span>
        <span>{evidence?.evidence_context ? `${formatAmount(evidence.evidence_context.eligible_count)} 條可參考 · 其餘資料保留在歷史` : "歷史適用性尚未核實"}</span>
      </div>
      <Disclosure label="下一期商品範圍">
        <label className="flex min-w-0 flex-col gap-2 text-sm">選擇商品
          <select aria-label="選擇商品" value={scope.selection} onChange={event => scope.setSelection(event.target.value)} className="h-10 w-full min-w-0 rounded-md border border-border bg-background px-3">
            <option value="">請選擇商品</option>
            {scope.selection && !scope.product && <option value={scope.selection}>原選擇已不可用，請核對</option>}
            {scope.products?.map(product => <option key={product.id} value={product.id}>{product.name}</option>)}
          </select>
        </label>
        <p className="mt-2 text-xs text-muted-foreground">選擇保留在本頁；按上方規劃下一期，才會帶入新活動草稿。</p>
      </Disclosure>
      {(scope.optionsError || scope.error || state.error) && <ReadFailed what={`${scope.optionsError ?? scope.error ?? state.error}；保留同商品上次讀取的資料與你的選擇，尚未核實最新狀態。`} onRetry={retry} retryLabel="重新讀取" />}
      {(scope.busy || state.refreshing) && <p role="status" className="text-sm text-muted-foreground">正在讀取；上次資料保留，尚未核實最新狀態。</p>}
      <QualifiedLearningList key={scope.selection} data={evidence} onRetry={retry} loading={scope.busy}>
      <Disclosure label="每期廣告排名" open={rankOpen} onOpenChange={setRankOpen}>
      <div aria-label="怎麼判" className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 rounded-lg bg-background px-3 py-2 text-[12.5px] text-muted-foreground">
        <b className="font-semibold text-foreground">怎麼判</b>
        {focus && (
          <span data-part="rule-text">
            {focus.campaign_id === highlightCampaignId ? "這一期" : "最近一期"}：{focus.rule_text}
          </span>
        )}
        {focus && rules && <span aria-hidden="true" className="text-border">｜</span>}
        {rules && (
          <span data-part="sample-rule">成交少於 {figure(rules.grade.sample_few)} 筆標「{rules.labels.flags.few}」</span>
        )}
      </div>
      {groups.length > 0 && (
        <section aria-labelledby="learn-groups-h">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h3 id="learn-groups-h" className="text-sm font-semibold">各顧客群・{campaigns.length} 期合計</h3>
            <span className="text-xs text-muted-foreground">每筆＝花費 ÷ 成交</span>
          </div>
          <GroupSummary groups={groups} />
        </section>
      )}
      <section aria-labelledby="learn-camps-h" className="flex flex-col gap-3">
        <h3 id="learn-camps-h" className="text-sm font-semibold">每期每則廣告排名</h3>
        {campaigns.map((c) => (
          <LearningsTable
            key={c.campaign_id}
            campaign={c}
            highlight={c.campaign_id === highlightCampaignId}
            campaignHref={`${adsHome}/campaigns/${encodeURIComponent(c.campaign_id)}`}
          />
        ))}
      </section>
      {campaigns.length === 0 && <div data-slot="learnings-empty" className="flex flex-col items-center gap-2 px-5 py-9 text-center"><b>還沒有結案的活動</b><span className="text-[13px] text-muted-foreground">活動結案後，每則廣告會照每筆成本排在這裡。</span><Button asChild variant="outline" size="sm"><Link to={adsHome}>到投放中心</Link></Button></div>}
      </Disclosure>
      </QualifiedLearningList>
    </div>
  );
}
