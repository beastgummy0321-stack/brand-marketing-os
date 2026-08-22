import { useEffect, useRef, useState, type ReactNode } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatUsd } from "@/lib/format";
import {
  approveProposal,
  fetchApproveGenerateStatus,
  fetchProposal,
  returnProposal,
  updateChannelPlan,
  type ChannelPlan,
  type ProposalResponse,
} from "@/lib/proposalApi";
import { usePagination } from "@/lib/usePagination";

// 核可後輪詢生成進度的節奏（票 13）：照抄 PlanStep.tsx 出方案輪詢的既有節奏，同一套
// _progress_state 背景引擎，不是另一套等待邏輯。
const GENERATE_POLL_INTERVAL_MS = 3000;
// 付費手測抓到的第二層缺陷：這裡原本寫死 180 秒，但伺服器的逾時天花板會跟著這次核准
// 要跑的生成次數變大（8 次生成時是 720 秒）——寫死的前端死線比伺服器天花板還短，畫面
// 會比伺服器先喊「花比較久」，其實生成明明快成功了。改成讀 approve() 當下
// `proposal.approval.estimated_generation_timeout_seconds`（後端算好、跟伺服器判斷
// 逾時同一個數字），加一段緩衝讓伺服器永遠先判定，前端輪詢死線不會比伺服器早到。
// 這個常數只在該欄位缺席（理論上不會，型別已保證）時當保底。
const GENERATE_POLL_TIMEOUT_FALLBACK_MS = 180_000;
const GENERATE_POLL_DEADLINE_BUFFER_MS = 15_000;

// 獨立審查最後一個 blocker（票 13）：這條路線是 N 次序列生成，不是單次生成，之前
// 套用單次生成慣例寫死的等待秒數，對一個 8 次生成的批次會差了三倍。實測單次生成
// 23～31 秒，這裡取靠上緣的整數 30 秒／次估算一個跟批次規模相稱的粗略等待時間（寧可說長不說短）——用「大約」
// 講清楚這不是精準數字（後端本來就只給得出天花板，見 estimated_generation_timeout_
// seconds），不是重算一次天花板給使用者看。
const SECONDS_PER_GENERATION_ESTIMATE = 30;

function formatGenerateWaitMessage(generationCount: number): string {
  const count = Math.max(1, generationCount);
  const totalSeconds = count * SECONDS_PER_GENERATION_ESTIMATE;
  const duration = totalSeconds < 60 ? "大約半分鐘" : `大約 ${Math.round(totalSeconds / 60)} 分鐘`;
  const batchClause = count > 1 ? `這批共 ${count} 份素材，` : "";
  return `AI 正在生成素材，${batchClause}${duration}，可以先去別的頁面，等一下回來看。`;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; proposal: ProposalResponse };

const CHANNEL_LABELS: Record<string, string> = {
  social: "Meta",
  google_search: "Google 搜尋",
  line_email: "LINE／電子報",
  kol_media: "合作媒體",
  website_landing: "官網購買頁",
};

/**
 * 提案書（F1 畫面 2）。這是新 proposal API 的唯一畫面呼叫端；ready 但沒有管道資料時保留舊
 * `PlanStep` 作為舊資料相容路徑（ponytail：新檔期一定有五列，空陣列代表 T3 前舊檔期）。
 */
export function ProposalBook({
  brandId,
  cycleId,
  onApproved,
  onReturned,
  onOpenWorkbench,
  onFallback,
}: {
  brandId: string;
  cycleId: string;
  onApproved: () => void;
  onReturned: () => void;
  onOpenWorkbench: () => void;
  onFallback: () => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [saving, setSaving] = useState<"approve" | "return" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [channels, setChannels] = useState<ChannelPlan[]>([]);
  const [channelSaving, setChannelSaving] = useState<string | null>(null);
  // 核可後背景生成預選素材的畫面狀態（票 13 驗收 1／2／3）：跟企劃出方案
  // （PlanStep.tsx）同一套「setInterval 輪詢＋deadline ref」寫法，同一個 _progress_state
  // 背景引擎，不是另一套等待邏輯（D1）。生成失敗不影響已經生效的核可（D2）——只是把
  // failed 訊息顯示出來，不把畫面打回「等你核可」。
  const [generateState, setGenerateState] = useState<"idle" | "running" | "partial" | "failed">("idle");
  const [generateError, setGenerateError] = useState<string | null>(null);
  const generatePollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const generatePollDeadlineRef = useRef(0);

  function stopGeneratePolling() {
    if (generatePollTimerRef.current) {
      clearInterval(generatePollTimerRef.current);
      generatePollTimerRef.current = null;
    }
  }

  useEffect(() => stopGeneratePolling, []);

  function load() {
    setState({ status: "loading" });
    fetchProposal(brandId, cycleId)
      .then((proposal) => {
        if (proposal.status === "ready" && proposal.blocks.channels.length === 0) {
          onFallback();
          return;
        }
        setState({ status: "ready", proposal });
        if (proposal.status === "ready") setChannels(proposal.blocks.channels);
      })
      .catch((error: unknown) => {
        setState({ status: "error", message: error instanceof Error ? error.message : "讀取失敗，請稍後再試。" });
      });
  }

  useEffect(load, [brandId, cycleId]);

  async function pollGenerateOnce() {
    if (Date.now() > generatePollDeadlineRef.current) {
      stopGeneratePolling();
      setGenerateState("failed");
      setGenerateError("花比較久，可以先去素材工作檯看看，或稍後再回來查看。");
      return;
    }
    try {
      const status = await fetchApproveGenerateStatus(brandId, cycleId);
      if (status.status === "done") {
        stopGeneratePolling();
        setGenerateState("idle");
      } else if (status.status === "partial") {
        // 撞到花費上限，或部分生成本身失敗——不是靜默成功，但核可依然生效（D2），
        // 所以不套用 failed 的警示紅底，用跟「等你核可」同色階的提醒即可。
        stopGeneratePolling();
        setGenerateState("partial");
        setGenerateError(status.message ?? "這次核可的素材生成沒有全部完成，請到素材工作檯查看。");
      } else if (status.status === "failed") {
        stopGeneratePolling();
        setGenerateState("failed");
        setGenerateError(status.message ?? "生成素材時發生問題，請稍後到素材工作檯查看。");
      }
      // status === "running"：什麼都不做，等下一次輪詢。
    } catch (error) {
      stopGeneratePolling();
      setGenerateState("failed");
      setGenerateError(error instanceof Error ? error.message : "生成素材時發生問題，請稍後到素材工作檯查看。");
    }
  }

  async function approve() {
    setSaving("approve");
    setActionError(null);
    try {
      await approveProposal(brandId, cycleId);
      // approve() 本身已經同步核可完成（D2），立刻重新讀一次讓畫面反映「已核可」，
      // 不必等使用者手動重整；核可後才會開始跑的背景生成另外用輪詢追。
      load();
      setGenerateError(null);
      setGenerateState("running");
      const ceilingSeconds = state.status === "ready" ? state.proposal.approval.estimated_generation_timeout_seconds : null;
      const timeoutMs = ceilingSeconds != null ? ceilingSeconds * 1000 + GENERATE_POLL_DEADLINE_BUFFER_MS : GENERATE_POLL_TIMEOUT_FALLBACK_MS;
      generatePollDeadlineRef.current = Date.now() + timeoutMs;
      stopGeneratePolling();
      generatePollTimerRef.current = setInterval(() => void pollGenerateOnce(), GENERATE_POLL_INTERVAL_MS);
      onApproved();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "核可失敗，請稍後再試。");
    } finally {
      setSaving(null);
    }
  }

  async function returnForAdjustment() {
    if (!window.confirm("會把這期退回開檔階段重新調整，已選的方案要重新選一次。確定要退回嗎？")) return;
    setSaving("return");
    setActionError(null);
    try {
      await returnProposal(brandId, cycleId);
      onReturned();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "送回調整失敗，請稍後再試。");
    } finally {
      setSaving(null);
    }
  }

  async function toggleChannel(channel: string) {
    const previous = channels;
    const next = previous.map((item) => item.channel === channel ? { ...item, enabled: !item.enabled } : item);
    setChannels(next);
    setChannelSaving(channel);
    setActionError(null);
    try {
      const result = await updateChannelPlan(brandId, cycleId, next);
      setChannels(result.channels);
    } catch (error) {
      setChannels(previous);
      setActionError(error instanceof Error ? error.message : "更新失敗，請稍後再試。");
    } finally {
      setChannelSaving(null);
    }
  }

  if (state.status === "loading") {
    return (
      <div className="flex flex-col gap-3">
        {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-20 w-full" />)}
      </div>
    );
  }

  if (state.status === "error") {
    return <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  }

  const { proposal } = state;
  if (proposal.status === "assembling") {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground shadow-[var(--shadow-card)]">
        AI 正在組提案書…（可先離開，好了通知你）
      </div>
    );
  }

  if (proposal.status === "failed") {
    return (
      <div className="rounded-lg border border-warning/40 bg-warning/10 p-6 shadow-[var(--shadow-card)]">
        <h2 className="font-display text-lg text-warning">組裝失敗</h2>
        {proposal.reason && <p className="mt-2 text-sm text-warning">{proposal.reason}</p>}
        <button type="button" onClick={load} className="mt-4 rounded-md border border-warning px-3 py-1.5 text-sm font-medium text-warning hover:bg-warning/10">
          重新嘗試
        </button>
      </div>
    );
  }

  return (
    <section className="flex max-h-[75vh] flex-col gap-4 overflow-y-auto">
      <div className="sticky top-0 z-10 rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-lg text-foreground">這期提案書</h2>
          <p className="mt-1 text-sm text-muted-foreground">確認後開始準備素材。</p>
          {!proposal.approval.approved && (
            <p className="mt-1 text-xs text-muted-foreground">
              這一步會用 AI 產素材，最多花費 {formatUsd(proposal.approval.estimated_generation_cost)}
            </p>
          )}
        </div>
          <div className="flex flex-wrap items-center gap-3">
            {proposal.approval.approved ? <span className="rounded-full bg-success/10 px-3 py-1 text-sm font-medium text-success">已核可</span> : <span className="rounded-full bg-warning/10 px-3 py-1 text-sm font-medium text-warning">等你核可</span>}
            {!proposal.approval.approved && (
              <>
                <button
                  type="button"
                  disabled={saving !== null}
                  onClick={() => void approve()}
                  className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {saving === "approve" ? "送出中…" : "核可提案書（開始做素材）"}
                </button>
                <button
                  type="button"
                  disabled={saving !== null}
                  onClick={() => void returnForAdjustment()}
                  className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {saving === "return" ? "送出中…" : "哪裡不對，退回調整"}
                </button>
              </>
            )}
            <button type="button" onClick={onOpenWorkbench} className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary">前往素材工作檯</button>
          </div>
        </div>
        {proposal.approval.warning && <p className="mt-3 text-sm text-danger">{proposal.approval.warning}</p>}
        {actionError && <p className="mt-3 text-sm text-danger">{actionError}</p>}
      </div>
      {generateState === "running" && (
        <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground shadow-[var(--shadow-card)]">
          {formatGenerateWaitMessage(proposal.approval.generation_count)}
        </div>
      )}
      {generateState === "partial" && (
        <div className="rounded-lg border border-warning/30 bg-warning/10 p-4 text-sm text-warning shadow-[var(--shadow-card)]">
          {generateError}
        </div>
      )}
      {generateState === "failed" && (
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-4 text-sm text-danger shadow-[var(--shadow-card)]">
          {generateError}
        </div>
      )}
      <details className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        <summary className="cursor-pointer font-medium text-foreground">1 管道分工・{channels.length === 0 ? "—" : `啟用 ${channels.filter((item) => item.enabled).length} 條`}</summary>
        <div className="mt-3 flex flex-col gap-2">
          {channels.map((item) => (
            <div key={item.channel} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3 text-sm">
              <span className="font-medium text-foreground">{CHANNEL_LABELS[item.channel] ?? item.channel}</span>
              <button
                type="button"
                disabled={channelSaving === item.channel}
                onClick={() => void toggleChannel(item.channel)}
                className="rounded-md border border-border px-3 py-1.5 font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
              >
                {channelSaving === item.channel ? "更新中…" : item.enabled ? "用" : "不用"}
              </button>
            </div>
          ))}
        </div>
      </details>
      <ProposalSection title="2 預算配置" summary={budgetSummary(proposal.blocks.budget)} value={proposal.blocks.budget} />
      <ProposalSection title="3 素材預覽" summary={countSummary(proposal.blocks.creatives, "則")} value={proposal.blocks.creatives} />
      <ProposalSection title="4 追蹤健檢" summary={trackingBadCount(proposal.blocks.tracking) === "—" ? "—" : `${trackingBadCount(proposal.blocks.tracking)} 紅燈`} value={proposal.blocks.tracking} />
      <ProposalSection title="5 煞車" summary={countSummary(proposal.blocks.brakes, "條")} value={proposal.blocks.brakes} />
      <ProposalSection title="6 排程" summary={scheduleSummary(proposal.blocks.schedule)} value={proposal.blocks.schedule} />
    </section>
  );
}

function ProposalSection({ title, summary, value }: { title: string; summary: string; value: unknown }) {
  return (
    <details className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <summary className="cursor-pointer font-medium text-foreground">{title}・{summary}</summary>
      <div className="mt-2 text-sm leading-6 text-foreground"><ProposalValue value={value} /></div>
    </details>
  );
}

function budgetSummary(budget: unknown): string {
  if (!budget || typeof budget !== "object" || !("budget" in budget) || typeof budget.budget !== "number") return "—";
  return `NT$ ${budget.budget.toLocaleString("zh-TW")}`;
}

function countSummary(value: unknown, unit: string): string {
  if (!Array.isArray(value)) return "—";
  return `${value.length} ${unit}`;
}

function scheduleSummary(schedule: unknown): string {
  if (typeof schedule !== "string") return "已排定";
  const startDate = schedule.match(/^\d{4}-\d{2}-\d{2}/)?.[0];
  return startDate ?? "已排定";
}

function trackingBadCount(tracking: unknown): string {
  if (!tracking || typeof tracking !== "object" || !("channels" in tracking) || !Array.isArray(tracking.channels)) return "—";
  return String(tracking.channels.filter((channel) => channel && typeof channel === "object" && "status" in channel && channel.status === "bad").length);
}

function ProposalValue({ value }: { value: unknown }): ReactNode {
  const items = Array.isArray(value) ? value : [];
  const { page, pageCount, totalCount, pageItems, goToPage, topRef } = usePagination(items);
  if (typeof value === "string" || typeof value === "number") return value;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) {
    return (
      <div ref={topRef} className="space-y-3">
        <ul className="list-disc space-y-1 pl-5">{pageItems.map((item, index) => <li key={index}><ProposalValue value={item} /></li>)}</ul>
        {items.length > 12 && <Pager page={page} pageCount={pageCount} totalCount={totalCount} onChange={goToPage} />}
      </div>
    );
  }
  if (value && typeof value === "object") {
    return <div className="space-y-2">{Object.values(value).map((item, index) => <ProposalValue key={index} value={item} />)}</div>;
  }
  return "—";
}
