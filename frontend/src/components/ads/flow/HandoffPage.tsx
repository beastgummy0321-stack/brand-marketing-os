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
import { getQueue, type QueuePayload } from "@/lib/adsTriageApi";
import { ActionBar, Disclosure, FlowHeader, TodoRow } from "../patterns";
import {
  campaignChangesPath,
  changeStepPath,
  findFlowTriageItem,
  flowPosition,
  formatTargetAmount,
  stepFromChangeSet,
} from "./changeFlow";

const STEP_PURPOSE = "照清單手動修改";

/** 「↗ 打開平台」：有 `platform_url` 就在新分頁開啟；沒有（今天還沒有這個能力，或缺識別欄位）
 * 就换成標的名稱＋原生編號＋「複製編號」（feature Decisions「Agent choice — ↗ 打開平台」）。
 * 兩種情況都會回報 `onOpen`——這一步「打開平台」在畫面上算不算做完，退回複製編號版一樣算。 */
function PlatformButton({ platformUrl, target, onOpen }: {
  platformUrl: string | null; target: ChangeItem["target"]; onOpen: () => void;
}) {
  const [copied, setCopied] = useState(false);
  if (platformUrl) {
    return (
      <Button variant="outline" asChild>
        <a href={platformUrl} target="_blank" rel="noreferrer" onClick={onOpen}>↗ 打開平台</a>
      </Button>
    );
  }
  async function copyId() {
    try { await navigator.clipboard.writeText(target.native_id); } catch { /* 沒有剪貼簿權限也不擋操作 */ }
    setCopied(true);
    onOpen();
  }
  return (
    <div className="flex flex-col items-end gap-1 text-right text-xs text-muted-foreground">
      <span className="max-w-[10rem] truncate" title={target.name ?? undefined}>{target.name ?? "（未命名）"}</span>
      <span className="numeric">{target.native_id}</span>
      <Button variant="outline" size="sm" onClick={() => void copyId()}>{copied ? "已複製" : "複製編號"}</Button>
    </div>
  );
}

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

  const [queue, setQueue] = useState<QueuePayload | null>(null);
  const [changeSet, setChangeSet] = useState<ChangeSet | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [opened, setOpened] = useState(false);
  const [acted, setActed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    Promise.all([
      getQueue(brandId).then((q) => { if (!cancelled) setQueue(q); }).catch(() => {}),
      getChangeControl(brandId, campaignId)
        .then((data) => { if (!cancelled) setChangeSet(data.change_sets.find((s) => s.id === setId) ?? null); })
        .catch((err) => { if (!cancelled) setLoadError(err instanceof Error ? err.message : "讀取這份變更清單失敗，請稍後再試。"); }),
    ]).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [brandId, campaignId, setId, reloadKey]);

  const triageItem = useMemo(() => findFlowTriageItem(queue, changeSet), [queue, changeSet]);
  const position = flowPosition(queue, triageItem);

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

  if (loading) {
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

  const item: ChangeItem | undefined = changeSet.items.length === 1 ? changeSet.items[0] : undefined;
  const kind = item ? item.kind : "pause";
  const blocked = changeSet.items.length !== 1 || (kind !== "pause" && kind !== "copy" && kind !== "budget");

  if (blocked || !item) {
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

  const steps = [
    { label: "確認提議", to: changeStepPath(brandId, campaignId, changeSet.id, "confirm") },
    { label: "到平台完成" },
    { label: "核對結果" },
  ];
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
        <TodoRow no={1} done={opened} action={platformButton}>打開平台上的這則廣告</TodoRow>
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
      <FlowHeader
        steps={steps}
        current={1}
        title="到平台完成"
        purpose={STEP_PURPOSE}
        context={triageItem ? (
          <>
            <Badge variant="outline" className="max-w-[14rem] shrink" title={triageItem.triage.campaign_name}>
              <span className="block w-full min-w-0 truncate">{triageItem.triage.campaign_name}</span>
            </Badge>
            {position && <span>第 {position.pos} 件／共 {position.total} 件</span>}
          </>
        ) : undefined}
      />

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
