import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import { getCoordinateLearnings, type CoordinateLearnings } from "@/lib/adsLearningsApi";
import { ReadFailed } from "../patterns/ReadFailed";
import { figure, useAdsRules } from "../patterns/rules";
import { GroupSummary } from "./GroupSummary";
import { LearningsTable } from "./LearningsTable";

export type LearningsLoad =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: CoordinateLearnings };

/** One read of Contract L for the brand. The host owns it so a sub-nav count can show once read. */
export function useCoordinateLearnings(brandId: string): { state: LearningsLoad; reload: () => void } {
  const [state, setState] = useState<LearningsLoad>({ status: "loading" });
  const [round, setRound] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    setState({ status: "loading" });
    getCoordinateLearnings(brandId, {}, ctrl.signal)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
    return () => ctrl.abort();
  }, [brandId, round]);
  const reload = useCallback(() => setRound((n) => n + 1), []);
  return { state, reload };
}

/** Ranked rows across every listed campaign: the 投放學到的 sub-nav count. */
export function learningsCount(data: CoordinateLearnings): number {
  return data.campaigns.reduce((sum, c) => sum + c.rows.length, 0);
}

function Heading({ action }: { action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="text-[15px] font-semibold">投放學到的</h2>
        <p className="mt-0.5 text-[13px] text-muted-foreground">每期結案時，每則廣告照每筆成本排名，決定下一期留下或換掉</p>
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
  const rules = useAdsRules();
  useEffect(() => {
    if (!ready || !highlightCampaignId) return;
    document.getElementById(`camp-${highlightCampaignId}`)?.scrollIntoView?.({ block: "start" });
  }, [ready, highlightCampaignId]);

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
  const { campaigns, groups, next } = state.data;
  // The 怎麼判 strip names how one campaign was judged — the highlighted one (from a closeout), else the newest with
  // ranked rows — in its served `rule_text`, then the brand-wide sample flag from the served rules.
  const focus = campaigns.find((c) => c.campaign_id === highlightCampaignId && c.rule_text)
    ?? campaigns.find((c) => c.rule_text) ?? null;
  const adsHome = `/brands/${encodeURIComponent(brandId)}/ads`;
  if (campaigns.length === 0) {
    return (
      <div className="flex flex-col gap-[18px]">
        <Heading />
        <div data-slot="learnings-empty" className="flex flex-col items-center gap-2 px-5 py-9 text-center">
          <b>還沒有結案的活動</b>
          <span className="text-[13px] text-muted-foreground">活動結案後，每則廣告會照每筆成本排在這裡。</span>
          <Button asChild variant="outline" size="sm"><Link to={adsHome}>到投放中心</Link></Button>
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-[18px]">
      <Heading
        action={next && (
          <Button asChild variant="outline" size="sm"><Link to={next.new_campaign_href}>用這些學習排下一期 →</Link></Button>
        )}
      />
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
    </div>
  );
}
