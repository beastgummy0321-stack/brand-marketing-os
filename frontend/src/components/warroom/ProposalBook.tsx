import { useEffect, useState, type ReactNode } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { Skeleton } from "@/components/layout/Skeleton";
import {
  approveProposal,
  fetchProposal,
  returnProposal,
  updateChannelPlan,
  type ChannelPlan,
  type ProposalResponse,
} from "@/lib/proposalApi";
import { usePagination } from "@/lib/usePagination";

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

  async function approve() {
    setSaving("approve");
    setActionError(null);
    try {
      await approveProposal(brandId, cycleId);
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
