import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import {
  actOnChangeItem,
  getChangeControl,
  type ChangeItem,
  type ChangeSet,
} from "@/lib/adsChangeApi";
import { getQueue } from "@/lib/adsTriageApi";
import { useApiRead } from "@/lib/useApiRead";
import { ActionBar, CampaignChip, Disclosure, FlowHeader, ReadFailed, TodoRow, type FlowStep } from "../patterns";
import { useAbContext } from "./AbEvidence";
import { CleanupHandoffRows } from "./CleanupHandoffRows";
import { cleanupSteps } from "./CleanupProposal";
import { NewAdHandoffPanel } from "./NewAdHandoffPanel";
import { PlatformButton } from "./PlatformButton";
import {
  abSteps,
  campaignChangesPath,
  changeStepPath,
  findFlowTriageItem,
  flowPosition,
  formatTargetAmount,
  isAbSet,
  isCleanupTriageItem,
  stepFromChangeSet,
} from "./changeFlow";

const STEP_PURPOSE = "照清單手動修改";

/** 到平台完成頁（F22-I03，v7 原型 `handoff()`）：三步驟輕流程第二步，只走 `changes/:setId/handoff`
 * 這條正典網址——這一步一定已經有 change set（第一步核准時才建立），不像 `ConfirmPage` 還要
 * 撐住 propose 網址。清單內容照 item kind 畫不同的手動步驟；打勾狀態只是頁面上的核取記號
 * （不送後端，離開頁面就重置——feature Decisions／Done「Tick state is local to the page」）。 */
export function HandoffPage({ brandId, campaignId, setId }: {
  brandId: string; campaignId: string; setId: string;
}) {
  const navigate = useNavigate();
  const homeHref = `/brands/${brandId}/ads`;
  const crumb = [{ label: "投放中心", href: homeHref }, { label: "到平台完成" }];

  const [changeSet, setChangeSet] = useState<ChangeSet | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  // Contract K: the queue is context here (campaign chip, 第幾件); a failed read is shown, never silently dropped.
  const queueRead = useApiRead((signal) => getQueue(brandId, signal), [brandId, campaignId, setId, reloadKey]);
  const queue = queueRead.data;

  const [opened, setOpened] = useState(false);
  const [acted, setActed] = useState(false);
  // F27-I15 Contract F: cleanup 的「打開平台」是逐則廣告各自一顆，不是單一的 `opened` 布林值。
  const [cleanupOpened, setCleanupOpened] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    getChangeControl(brandId, campaignId)
      .then((data) => { if (!cancelled) setChangeSet(data.change_sets.find((s) => s.id === setId) ?? null); })
      .catch((err) => { if (!cancelled) setLoadError(err instanceof Error ? err.message : "讀取這份變更清單失敗，請稍後再試。"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [brandId, campaignId, setId, reloadKey]);

  const triageItem = useMemo(() => findFlowTriageItem(queue, changeSet), [queue, changeSet]);
  const position = flowPosition(queue, triageItem);
  // F29-I14 Contract F: an A/B "pause the loser" set reuses the pause handoff under its own three steps.
  const abSet = changeSet?.source !== "cleanup" && isAbSet(changeSet);
  const abContext = useAbContext(brandId, campaignId, abSet ? changeSet?.ab : null);

  // feature Decisions「Step from a change set」：這一步只服務 approved + 還沒回報的清單，
  // 其他狀態（草稿、已拒絕／暫緩、已讀回）都導去正確的步驟，不在這裡重新解讀。
  useEffect(() => {
    if (!changeSet) return;
    const { step } = stepFromChangeSet(changeSet);
    if (step !== "handoff") navigate(changeStepPath(brandId, campaignId, changeSet.id, step), { replace: true });
  }, [changeSet, brandId, campaignId, navigate]);

  function errorMessage(err: unknown): string {
    return err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。";
  }

  async function copyText(text: string) {
    try { await navigator.clipboard.writeText(text); } catch { /* 沒有剪貼簿權限也不擋操作 */ }
    setActed(true);
  }

  async function handleDone(item: ChangeItem) {
    if (busy || !changeSet) return;
    setBusy(true);
    setActionError(null);
    try {
      await actOnChangeItem(brandId, campaignId, changeSet.id, item.id, "report");
      try {
        await actOnChangeItem(brandId, campaignId, changeSet.id, item.id, "check");
      } catch {
        // feature Decisions：report 成功後 check 失敗仍然導去核對結果頁（那裡會顯示「核對中」），
        // 不擋在這一頁重試。
      }
      navigate(changeStepPath(brandId, campaignId, changeSet.id, "verify"));
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  /** F27-I15 Contract F: cleanup 版本的「我做完了」——對清單裡每一則廣告各自 report／check
   * 一次，同 `handleDone` 一顆錯誤處理與「check 失敗仍然前進」規則，只是逐項跑；中途失敗就停在
   * 已完成的進度，錯誤訊息留在這一頁，不整批重試（同 `VerifyPage.tsx::handleCheckAll` 的做法）。 */
  async function handleCleanupDone(items: ChangeItem[]) {
    if (busy || !changeSet) return;
    setBusy(true);
    setActionError(null);
    try {
      let current = changeSet;
      for (const row of items) {
        current = await actOnChangeItem(brandId, campaignId, current.id, row.id, "report");
        setChangeSet(current);
        try {
          current = await actOnChangeItem(brandId, campaignId, current.id, row.id, "check");
          setChangeSet(current);
        } catch {
          // 同 `handleDone`：單則 check 失敗仍然繼續下一則，核對結果頁會顯示「核對中」。
        }
      }
      navigate(changeStepPath(brandId, campaignId, current.id, "verify"));
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading || (queueRead.status === "loading" && !queue)) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={crumb} />
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={crumb} />
        <EmptyState title="讀取失敗" description={loadError} onAction={() => setReloadKey((k) => k + 1)} actionLabel="重新讀取" />
      </div>
    );
  }
  if (!changeSet) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={crumb} />
        <EmptyState
          title="找不到這份變更清單"
          description="網址可能過期，或這份清單已經被另一份取代。"
          actionHref={homeHref}
          actionLabel="回投放中心"
          actionInternal
        />
      </div>
    );
  }

  // F27-I15 Contract F: a cleanup set names itself (`source: "cleanup"`, F29-I04) or is recognised through the queue's
  // own `cleanup` row (`ConfirmPage.tsx`/`VerifyPage.tsx` share the same rule) — never guessed from item shape, and a
  // failed queue read cannot turn it into a "multi-item" set.
  const cleanupSet = changeSet.source === "cleanup" || isCleanupTriageItem(triageItem);
  const queueFailed = queueRead.status === "error" ? (
    <ReadFailed what="待決定清單讀不到：活動名稱與「第幾件」暫時看不到；下面的步驟照舊" onRetry={queueRead.reload} />
  ) : null;
  const item: ChangeItem | undefined = changeSet.items.length === 1 ? changeSet.items[0] : undefined;
  const kind = cleanupSet ? "cleanup" : item ? item.kind : "pause";
  const blocked = !cleanupSet
    && (changeSet.items.length !== 1 || !["pause", "copy", "budget", "new_ad"].includes(kind));

  if (blocked || (!cleanupSet && !item)) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={crumb} />
        <EmptyState
          title="這份清單有多項變更"
          description="請到活動的「變更與核對」查看完整內容並逐項處理。"
          actionHref={campaignChangesPath(brandId, campaignId)}
          actionLabel="前往變更與核對"
          actionInternal
        />
      </div>
    );
  }

  const confirmHref = changeStepPath(brandId, campaignId, changeSet.id, "confirm");
  // F28-I14: cleanup keeps its own four-step light flow (提議／確認／到平台完成／核對結果, prototype v9 `#/d/clean/*`,
  // same steps as `ConfirmPage`). 提議 stays unlinked once approved — the prototype forwards it to 確認 then.
  const steps: FlowStep[] = kind === "cleanup"
    ? cleanupSteps().map((step) => (step.label === "確認" ? { ...step, to: confirmHref } : step))
    : abSet ? abSteps(confirmHref)
    : [{ label: "確認提議", to: confirmHref }, { label: "到平台完成" }, { label: "核對結果" }];
  const headerContext = abSet ? (
    abContext.campaign ? <CampaignChip objective={abContext.campaign.objective} name={abContext.campaign.name} /> : undefined
  ) : triageItem ? (
    <>
      {kind === "cleanup" ? (
        <CampaignChip objective={triageItem.triage.campaign_objective ?? "other"} name={triageItem.triage.campaign_name} />
      ) : <Badge variant="outline" className="max-w-[14rem] shrink" title={triageItem.triage.campaign_name}>
        <span className="block w-full min-w-0 truncate">{triageItem.triage.campaign_name}</span>
      </Badge>}
      {position && <span>第 {position.pos} 件／共 {position.total} 件</span>}
    </>
  ) : undefined;

  // F27-I15 Screens「Flow pages, new-ad and multi-item」: 「handoff = the existing
  // ManualHandoffPanel steps for that item」——沒有既有的一連串 TodoRow 可套，整段換掉。
  if (kind === "new_ad") {
    return (
      <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
        <Breadcrumb items={crumb} />
        <FlowHeader steps={steps} current={1} title="到平台完成" purpose={STEP_PURPOSE} context={headerContext} />
        {queueFailed}
        <NewAdHandoffPanel brandId={brandId} campaignId={campaignId} />
        {actionError && <p role="alert" className="text-sm text-destructive">{actionError}</p>}
        <div className="flex-1" />
        <ActionBar
          back={<Button variant="ghost" asChild><Link to={homeHref}>← 還沒做完，先離開</Link></Button>}
          hint="核對結果由上面的交接面板決定"
        >
          <Button onClick={() => setReloadKey((k) => k + 1)}>看目前核對結果 →</Button>
        </ActionBar>
      </div>
    );
  }

  // F27-I15 Contract F: 「handoff one TodoRow per ad with 打開平台 per item」——每一則各自一列，
  // 底下一顆合併的「我都做完了」才真的呼叫 report／check（`handleCleanupDone`）。
  if (kind === "cleanup") {
    return (
      <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
        <Breadcrumb items={crumb} />
        <FlowHeader steps={steps} current={2} title="到平台完成" purpose={STEP_PURPOSE} context={headerContext} />
        {queueFailed}
        <div className="rounded-xl border border-border bg-card px-6">
          <CleanupHandoffRows
            items={changeSet.items}
            opened={cleanupOpened}
            onOpen={(id) => setCleanupOpened((prev) => new Set(prev).add(id))}
          />
        </div>
        {actionError && <p role="alert" className="text-sm text-destructive">{actionError}</p>}
        <div className="flex-1" />
        <ActionBar
          back={<Button variant="ghost" asChild><Link to={homeHref}>← 還沒做完，先離開</Link></Button>}
          hint="系統會逐則讀回平台核對"
        >
          <Button disabled={busy} onClick={() => void handleCleanupDone(changeSet.items)}>{busy ? "處理中…" : "我都做完了，開始核對 →"}</Button>
        </ActionBar>
      </div>
    );
  }

  // Unreachable in practice — the guard above already returned when `!cleanupSet && !item`, and
  // `new_ad`/`cleanup` both returned their own JSX earlier; this narrows `item` for the type
  // checker without re-deriving that guard's logic a second time.
  if (!item) return null;
  const platformButton = <PlatformButton platformUrl={item.platform_url} target={item.target} onOpen={() => setOpened(true)} />;

  let rows: ReactNode;
  if (kind === "copy") {
    rows = (
      <>
        <TodoRow no={1} done={acted} action={
          <>
            <Button variant="outline" size="sm" onClick={() => void copyText(item.after.title ?? "")}>複製標題</Button>
            <Button variant="outline" size="sm" onClick={() => void copyText(item.after.body ?? "")}>複製內文</Button>
          </>
        }>
          <p>複製新文案</p>
          <div className="mt-2 rounded-md bg-accent/60 p-3 text-sm">
            <b className="block">{item.after.title ?? "—"}</b>
            <p className="mt-1 whitespace-pre-wrap">{item.after.body ?? "—"}</p>
          </div>
        </TodoRow>
        <TodoRow no={2} done={opened} action={platformButton}>在平台編輯這則廣告，貼上</TodoRow>
      </>
    );
  } else if (kind === "pause") {
    rows = (
      <>
        <TodoRow no={1} done={opened} action={platformButton}>
          {abSet ? `打開平台上的「${item.target.name ?? "較貴的那一則"}」` : "打開平台上的這則廣告"}
        </TodoRow>
        <TodoRow no={2} done={acted} action={<Button variant="outline" size="sm" onClick={() => setActed(true)}>我關了</Button>}>
          把這則廣告的開關關掉
        </TodoRow>
      </>
    );
  } else {
    rows = (
      <>
        <TodoRow no={1} done={opened} action={platformButton}>
          打開平台上的「{item.target.name ?? "未命名投放組"}」
        </TodoRow>
        <TodoRow no={2} done={acted} action={
          <Button variant="outline" size="sm" onClick={() => void copyText(formatTargetAmount(item.after.daily_amount ?? null))}>複製金額</Button>
        }>
          每日預算改成 <span className="text-lg font-semibold">{formatTargetAmount(item.after.daily_amount ?? null)}</span>
        </TodoRow>
      </>
    );
  }

  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb items={crumb} />
      <FlowHeader steps={steps} current={1} title="到平台完成" purpose={STEP_PURPOSE} context={headerContext} />
      {queueFailed}

      <div className="rounded-xl border border-border bg-card px-6">
        {rows}
        <TodoRow no={3} action={<span aria-hidden="true" className="text-lg text-muted-foreground">↘</span>}>
          回來按「我做完了」
        </TodoRow>
      </div>

      {kind === "copy" && (
        <Disclosure label="看舊文案">
          <div className="rounded-md bg-muted p-3 text-sm">
            <b className="block">{item.before.title ?? "—"}</b>
            <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{item.before.body ?? "—"}</p>
          </div>
        </Disclosure>
      )}

      {actionError && <p role="alert" className="text-sm text-destructive">{actionError}</p>}

      <div className="flex-1" />
      <ActionBar
        back={<Button variant="ghost" asChild><Link to={homeHref}>← 還沒做完，先離開</Link></Button>}
        hint="系統會讀回平台核對"
      >
        <Button disabled={busy} onClick={() => void handleDone(item)}>{busy ? "處理中…" : "我做完了，開始核對 →"}</Button>
      </ActionBar>
    </div>
  );
}
