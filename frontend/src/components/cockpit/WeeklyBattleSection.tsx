import { useCallback, useEffect, useState } from "react";
import { Check, ChevronDown, Images, RefreshCw, ShieldCheck, WalletCards } from "lucide-react";
import {
  approveAllWeeklyProposals,
  approveWeeklyProposal,
  fetchWeeklyProposals,
  fetchWeeklyRejudgeStatus,
  skipWeeklyProposal,
  startWeeklyRejudge,
  type WeeklyGrade,
  type WeeklyProposal,
  type WeeklyProposalsData,
  type WeeklyRejudgeState,
} from "@/lib/weeklyApi";
import { cn } from "@/lib/utils";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: WeeklyProposalsData };

const GRADE_LABEL: Record<WeeklyGrade, string> = {
  save: "省錢・同意即執行",
  spend: "花錢・同意後再確認金額",
  asset: "產素材・核可後排進工作檯",
};

const GRADE_CLASS: Record<WeeklyGrade, string> = {
  save: "border-success/30 bg-success/10 text-success",
  spend: "border-warning/30 bg-warning/10 text-warning",
  asset: "border-border bg-muted text-muted-foreground",
};

function GradeIcon({ grade }: { grade: WeeklyGrade }) {
  const className = "h-4 w-4 shrink-0";
  if (grade === "save") return <ShieldCheck className={className} aria-hidden="true" />;
  if (grade === "spend") return <WalletCards className={className} aria-hidden="true" />;
  return <Images className={className} aria-hidden="true" />;
}

export function WeeklyBattleSection({
  brandId,
  focusProposalId,
}: {
  brandId: string;
  focusProposalId?: string | null;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [rejudge, setRejudge] = useState<WeeklyRejudgeState>({ status: "done" });
  const [expanded, setExpanded] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setState({ status: "loading" });
    try {
      const status = await fetchWeeklyRejudgeStatus(brandId);
      setRejudge(status);
      if (status.status === "running") return;
      const data = await fetchWeeklyProposals(brandId);
      setState({ status: "ready", data });
    } catch (error) {
      setState({
        status: "error",
        message: error instanceof Error ? error.message : "讀取失敗，請稍後再試。",
      });
    }
  }, [brandId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (focusProposalId) setExpanded(true);
  }, [focusProposalId]);

  useEffect(() => {
    if (rejudge.status !== "running") return;
    const timer = window.setInterval(() => {
      void fetchWeeklyRejudgeStatus(brandId)
        .then((status) => {
          setRejudge(status);
          if (status.status === "done") void load(false);
        })
        .catch((error: unknown) => {
          setRejudge({
            status: "failed",
            message: error instanceof Error ? error.message : "判讀狀態讀取失敗。",
          });
        });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [brandId, load, rejudge.status]);

  function replaceData(data: WeeklyProposalsData) {
    setState({ status: "ready", data });
    setActionError(null);
  }

  async function handleRejudge() {
    setActionError(null);
    setNotice(null);
    try {
      const status = await startWeeklyRejudge(brandId);
      setRejudge(status);
    } catch (error) {
      setRejudge({
        status: "failed",
        message: error instanceof Error ? error.message : "判讀失敗，請稍後再試。",
      });
    }
  }

  async function handleApprove(proposal: WeeklyProposal) {
    if (proposal.grade === "spend" && confirmingId !== proposal.id) {
      setConfirmingId(proposal.id);
      setAmounts((current) => ({
        ...current,
        [proposal.id]: proposal.spend_confirmation?.suggested_amount?.toString() ?? "",
      }));
      return;
    }
    const confirmedAmount = proposal.grade === "spend" ? Number(amounts[proposal.id]) : undefined;
    if (proposal.grade === "spend" && (!confirmedAmount || confirmedAmount <= 0)) {
      setActionError("請填大於 0 的確認金額。");
      return;
    }
    setBusyId(proposal.id);
    setActionError(null);
    setNotice(null);
    try {
      const result = await approveWeeklyProposal(brandId, proposal.id, confirmedAmount);
      replaceData(result);
      setConfirmingId(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "核可失敗，請稍後再試。");
    } finally {
      setBusyId(null);
    }
  }

  async function handleSkip(proposalId: string) {
    setBusyId(proposalId);
    setActionError(null);
    setNotice(null);
    try {
      replaceData(await skipWeeklyProposal(brandId, proposalId));
      setConfirmingId(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "略過失敗，請稍後再試。");
    } finally {
      setBusyId(null);
    }
  }

  async function handleApproveAll() {
    setBusyId("all");
    setActionError(null);
    setNotice(null);
    try {
      const result = await approveAllWeeklyProposals(brandId);
      replaceData(result);
      if (result.pending_confirmation.length > 0) {
        setNotice("花錢提案還要逐張確認金額。");
        setExpanded(true);
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "核可失敗，請稍後再試。");
    } finally {
      setBusyId(null);
    }
  }

  const shellClass = "rounded-[var(--radius-xl)] border border-border bg-card p-5 shadow-[var(--shadow-card)]";

  if (rejudge.status === "running") {
    return (
      <section className={shellClass} aria-live="polite">
        <h2 className="font-display text-lg text-foreground">本週作戰</h2>
        <div className="mt-4 flex items-center gap-3 rounded-lg border border-primary/20 bg-primary/5 px-4 py-5 text-sm text-foreground">
          <RefreshCw className="h-5 w-5 animate-spin text-primary motion-reduce:animate-none" aria-hidden="true" />
          <span>正在判讀本週資料。可以先離開，完成後會進收件匣。</span>
        </div>
      </section>
    );
  }

  if (state.status === "loading") {
    return (
      <section className={shellClass} aria-busy="true">
        <h2 className="font-display text-lg text-foreground">本週作戰</h2>
        <p className="mt-4 text-sm text-muted-foreground">正在載入本週提案…</p>
      </section>
    );
  }

  if (state.status === "error" || rejudge.status === "failed") {
    const message = state.status === "error" ? state.message : (rejudge.message ?? "這週資料還判讀不了。");
    return (
      <section className={shellClass}>
        <h2 className="font-display text-lg text-foreground">本週作戰</h2>
        <div className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-4">
          <p className="text-sm font-medium text-danger">判讀失敗</p>
          <p className="mt-1 text-sm text-foreground">{message}</p>
          <div className="mt-3 flex flex-wrap gap-3">
            <button type="button" onClick={() => void handleRejudge()} className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground">再試一次</button>
            <a href={`/brands/${encodeURIComponent(brandId)}/ads`} className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-primary">去看同步狀態</a>
          </div>
        </div>
      </section>
    );
  }

  const { data } = state;
  const actionCards = data.execution_checklist.filter((card) => card.action_card);
  if (data.proposals.length === 0 && actionCards.length === 0) {
    return (
      <section className={shellClass}>
        <h2 className="font-display text-lg text-foreground">本週作戰</h2>
        <div className="mt-4 rounded-lg border border-dashed border-border p-5 text-center">
          <p className="text-sm text-muted-foreground">本週還沒有新提案。系統每週一自動判讀，也可以現在重跑。</p>
          <button type="button" onClick={() => void handleRejudge()} className="mt-3 inline-flex items-center gap-2 rounded-md border border-primary px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10">
            <RefreshCw className="h-4 w-4" aria-hidden="true" />現在就重新判讀
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className={shellClass}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-lg text-foreground">本週作戰</h2>
          <p className="text-sm text-muted-foreground">{data.proposals.length} 張提案等你核可</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {data.proposals.length > 0 && (
            <button type="button" onClick={() => void handleApproveAll()} disabled={busyId !== null} className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50">
              <Check className="h-4 w-4" aria-hidden="true" />{busyId === "all" ? "核可中…" : "一鍵核可全部"}
            </button>
          )}
          {data.proposals.length > 0 && (
            <button type="button" onClick={() => setExpanded((value) => !value)} className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-primary">
              逐張看<ChevronDown className={cn("h-4 w-4 transition-transform", expanded && "rotate-180")} aria-hidden="true" />
            </button>
          )}
          <button type="button" onClick={() => void handleRejudge()} className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-primary">
            <RefreshCw className="h-4 w-4" aria-hidden="true" />現在就重新判讀
          </button>
        </div>
      </div>

      {(notice || actionError) && (
        <p className={cn("mt-3 rounded-md px-3 py-2 text-sm", actionError ? "bg-danger/10 text-danger" : "bg-warning/10 text-warning")} role="status">
          {actionError ?? notice}
        </p>
      )}

      {data.proposals.length > 0 && (
        <ul className="mt-4 flex flex-col gap-2">
          {data.proposals.map((proposal) => (
            <ProposalCard
              key={proposal.id}
              proposal={proposal}
              expanded={expanded}
              focused={proposal.id === focusProposalId}
              busy={busyId !== null}
              confirming={confirmingId === proposal.id}
              amount={amounts[proposal.id] ?? ""}
              onAmountChange={(amount) => setAmounts((current) => ({ ...current, [proposal.id]: amount }))}
              onApprove={() => void handleApprove(proposal)}
              onSkip={() => void handleSkip(proposal.id)}
            />
          ))}
        </ul>
      )}

      {actionCards.length > 0 && (
        <div className="mt-4 border-t border-border pt-4">
          <h3 className="text-sm font-medium text-foreground">已產生的行動卡</h3>
          <ul className="mt-2 flex flex-col gap-2">
            {actionCards.map((card) => (
              <li key={card.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted px-4 py-3 text-sm text-foreground">
                <span>{card.action_card}</span>
                {/* B0-16：card.action_url 是後端算好、已經帶 `/app/` 前綴的完整路徑
                 * （app/ads/weekly_proposals.py），設計上是給一般 <a href> 用的——react-router
                 * 的 <Link to> 會把它當成「相對 basename 的路徑」再疊加一次 `/app` basename，
                 * 變成 `/app/app/...` 雙前綴死連結。改回一般 <a>（整頁導航，跟其他吃同一種
                 * action_url 的元件同一套：AlertsPanel.tsx／InboxItemCard.tsx／
                 * GuideCards.tsx 都是 <a href>，不是 <Link>）。 */}
                {card.action_url && (
                  <a href={card.action_url} className="shrink-0 font-medium text-primary hover:underline">去素材工作檯</a>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/** 駕駛艙與收件匣側板共用的單張週提案卡，核可／略過只走同一組 API。 */
export function ProposalCard({
  proposal,
  expanded,
  focused,
  busy,
  confirming,
  amount,
  onAmountChange,
  onApprove,
  onSkip,
}: {
  proposal: WeeklyProposal;
  expanded: boolean;
  focused: boolean;
  busy: boolean;
  confirming: boolean;
  amount: string;
  onAmountChange: (amount: string) => void;
  onApprove: () => void;
  onSkip: () => void;
}) {
  return (
    <li
      tabIndex={focused ? -1 : undefined}
      aria-current={focused ? "true" : undefined}
      className={cn(
        "rounded-lg border border-border px-4 py-3",
        focused && "border-primary bg-primary/5 ring-1 ring-primary/30",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="flex min-w-0 flex-1 items-start gap-2 text-sm text-foreground">
          <GradeIcon grade={proposal.grade} />
          <span>{proposal.copy}</span>
        </p>
        <span className={cn("shrink-0 rounded-full border px-2.5 py-1 text-xs font-medium", GRADE_CLASS[proposal.grade])}>
          {GRADE_LABEL[proposal.grade]}
        </span>
      </div>

      {expanded && (
        <div className="mt-3 border-t border-border pt-3">
          <p className="text-xs text-muted-foreground">同意後：{proposal.impact}</p>
          {proposal.grade === "spend" && confirming && (
            <label className="mt-3 flex flex-wrap items-center gap-2 text-sm text-foreground">
              確認後金額（元）
              <input
                type="number"
                min="1"
                value={amount}
                onChange={(event) => onAmountChange(event.target.value)}
                className="w-36 rounded-md border border-border bg-background px-3 py-1.5"
              />
            </label>
          )}
          <div className="mt-3 flex gap-2">
            <button type="button" onClick={onApprove} disabled={busy} className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50">
              {busy ? "處理中…" : proposal.grade === "spend" && confirming ? "確認金額並產卡" : "同意"}
            </button>
            <button type="button" onClick={onSkip} disabled={busy} className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground disabled:opacity-50">略過</button>
          </div>
        </div>
      )}
    </li>
  );
}
