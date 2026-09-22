import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Image as ImageIcon } from "lucide-react";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatCount } from "@/lib/format";
import {
  approveChangeSet,
  createChangeSet,
  decideChangeSet,
  getChangeControl,
  getMonthlyBudget,
  ChangeRequestRejected,
  type ChangeItem,
  type ChangeSet,
  type MonthlyBudget,
} from "@/lib/adsChangeApi";
import { getQueue, type QueueItem, type QueuePayload, type TriageItem } from "@/lib/adsTriageApi";
import { budgetMoney, currentBudgetMonth } from "../MonthlyBudgetPanel";
import { reviewRoundPath } from "../review/reviewFlow";
import { ActionBar, Chip, DecisionSheet, FlowHeader, KindMark, Meter, ReservedSlotCard, Segmented } from "../patterns";
import {
  buildPauseDraftItem,
  campaignChangesPath,
  changeStepPath,
  pauseTitle,
  proposePausePath,
  stepFromChangeSet,
  toChangeInput,
  formatAmount,
  formatTargetAmount,
} from "./changeFlow";

const STEPS = [{ label: "確認提議" }, { label: "到平台完成" }, { label: "核對結果" }];
const STEP_PURPOSE = "核准後才到平台操作";

/** 廣告／投放組縮圖：`null`、還沒讀到或載入失敗都落到同一顆中性佔位圖示，不是空白或破圖示
 * （同 `detail/CampaignDetailPage.tsx` 的 `AdThumb` 慣例；那支沒有 export，這裡另一份小工具，
 * 不是重刻 kit 零件——facts 把 `.thumb` 分在「沒有對應 kit 零件」，layout 用 token 自己刻）。 */
function Tile({ url, icon }: { url?: string | null; icon?: ReactNode }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  const showImage = !!url && !failed;
  return (
    <div className="flex size-16 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-muted" aria-hidden="true">
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- 這裡不是 Next.js 專案。
        <img src={url ?? undefined} alt="" className="size-full object-cover" onError={() => setFailed(true)} />
      ) : (
        icon ?? <ImageIcon className="size-6 text-muted-foreground" />
      )}
    </div>
  );
}

/** 暫停提議的證據卡：有 triage 就是完整量尺版；triage 已經不在佇列裡（entered by :setId 且
 * 廣告已離開佇列）就退回只有名稱與理由的版本（feature Decisions「Confirm (pause)」）。 */
function PauseEvidence({ triage, fallbackName, fallbackReason }: {
  triage: TriageItem | null; fallbackName: string; fallbackReason: string;
}) {
  if (!triage) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-center gap-4">
          <Tile url={null} />
          <div className="min-w-0 flex-1">
            <KindMark kind="stop">停損</KindMark>
            <p className="mt-1.5 truncate text-[15px] font-semibold">{fallbackName}</p>
          </div>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">{fallbackReason}</p>
      </div>
    );
  }
  const line = triage.target.value === null ? null : triage.target.value * 3;
  const max = line === null ? null : line * 1.5;
  const countText = triage.current.result_count === null
    ? "累積中"
    : `${formatCount(triage.current.result_count)} 筆${triage.current.result_label}`;
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center gap-4">
        <Tile url={triage.thumbnail_url} />
        <div className="min-w-0 flex-1">
          <KindMark kind="stop">停損</KindMark>
          <p className="mt-1.5 truncate text-[15px] font-semibold" title={triage.name ?? "（未命名廣告）"}>
            {triage.name ?? "（未命名廣告）"}
          </p>
        </div>
        <Chip tone="ok">✓ 不會新增花費</Chip>
      </div>
      <div className="mt-4 max-w-[560px]">
        <Meter
          value={triage.current.spend}
          max={max}
          marker={line}
          tone="danger"
          left={<>已花 <b className="text-foreground">{formatAmount(triage.current.spend)}</b>・{countText}・{triage.window.days} 天</>}
          right={<>停損線 {formatTargetAmount(line)}（目標 × 3）</>}
        />
      </div>
    </div>
  );
}

function CopyEvidence({ item }: { item: ChangeItem }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center gap-4">
        <Tile url={null} />
        <div className="min-w-0 flex-1">
          <Chip tone="accent">改文案・圖片不變</Chip>
          <p className="mt-1.5 truncate text-[15px] font-semibold">{item.target.name ?? "（未命名廣告）"}</p>
        </div>
        <Chip tone="ok">✓ 不會新增花費</Chip>
      </div>
      <div className="mt-4 grid grid-cols-1 items-center gap-3 md:grid-cols-[1fr_auto_1fr]">
        <div className="rounded-md bg-muted p-3 text-sm">
          <b className="block">{item.before.title ?? "—"}</b>
          <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{item.before.body ?? "—"}</p>
        </div>
        <div aria-hidden="true" className="text-center text-xl text-muted-foreground">→</div>
        <div className="rounded-md bg-accent/60 p-3 text-sm">
          <b className="block">{item.after.title ?? "—"}</b>
          <p className="mt-1 whitespace-pre-wrap">{item.after.body ?? "—"}</p>
        </div>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">原因：{item.reason}</p>
    </div>
  );
}

/** 三段可用度長條，跟 `home/BudgetCard.tsx` 同一份色碼與誠實未知邏輯，但這裡只需要一小條
 * （原型 `budgetBar()` 位置），不是整張「可新增承諾」卡（那張有自己的標題與「調整」入口，
 * 跟這張證據卡的版位不同，不整張借用）。 */
function MiniBudgetBar({ budget }: { budget: MonthlyBudget }) {
  const { amount, known_spend, ongoing_estimate, available, currency } = budget;
  const known = amount !== null && amount > 0 && known_spend !== null && ongoing_estimate !== null && available !== null;
  const pct = (v: number) => Math.max(0, Math.min(100, (v / (amount as number)) * 100));
  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted" aria-hidden="true">
        {known && (
          <>
            <div className="bg-chart-rest" style={{ width: `${pct(known_spend as number)}%` }} />
            <div className="bg-border" style={{ width: `${pct(ongoing_estimate as number)}%` }} />
            <div className="bg-primary" style={{ width: `${pct(available as number)}%` }} />
          </>
        )}
      </div>
      <p className="numeric text-xs text-muted-foreground">
        已花 {budgetMoney(known_spend, currency)}・可用 {budgetMoney(available, currency)}
      </p>
    </div>
  );
}

function BudgetEvidence({ item, brandId }: { item: ChangeItem; brandId: string }) {
  const [budget, setBudget] = useState<MonthlyBudget | null>(null);
  const [budgetError, setBudgetError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getMonthlyBudget(brandId, currentBudgetMonth())
      .then((b) => { if (!cancelled) setBudget(b); })
      .catch(() => { if (!cancelled) setBudgetError(true); });
    return () => { cancelled = true; };
  }, [brandId]);
  const before = item.before.daily_amount ?? null;
  const after = item.after.daily_amount ?? null;
  const pct = before !== null && after !== null && before > 0 ? Math.round(((after - before) / before) * 100) : null;
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center gap-4">
        <Tile icon={<span aria-hidden="true" className="text-2xl">💰</span>} />
        <div className="min-w-0 flex-1">
          <KindMark kind="up">可加預算</KindMark>
          <p className="mt-1.5 truncate text-[15px] font-semibold">{item.target.name ?? "（未命名投放組）"}</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground">每日預算</p>
          <p className="numeric flex items-center gap-2 text-lg font-semibold">
            <span>{formatTargetAmount(before)} → {formatTargetAmount(after)}</span>
            {pct !== null && <Chip tone="ok">{pct > 0 ? "+" : ""}{pct}%</Chip>}
          </p>
        </div>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">原因：{item.reason}</p>
      <div className="mt-4 rounded-md border border-border p-3">
        <h3 className="text-sm font-medium">本月預算放得下</h3>
        {budgetError && <p className="mt-2 text-sm text-warning">月預算暫時讀取不到，不影響上面的核准內容。</p>}
        {!budgetError && !budget && <p className="mt-2 text-sm text-muted-foreground">正在整理月預算…</p>}
        {budget && <MiniBudgetBar budget={budget} />}
      </div>
    </div>
  );
}

type DecisionKind = "rejected" | "deferred";
type QuickPick = "3" | "7" | "custom";

/** 確認提議頁（F22-I02，v7 原型 `confirmPage()`＋拒絕／暫緩 sheet）。兩條路由共用同一支元件：
 * `entityId`（propose route）還沒有 change set，草稿只在第一次核准／拒絕／暫緩時才建立
 * （feature Decisions「Agent choice — the draft is created lazily」，never on page load）；
 * `setId`（changes route）已經有 change set，直接讀。任何非 confirm 的步驟都由這裡導去正確
 * 步驟（`changeFlow.ts::stepFromChangeSet`），也同時把 propose 網址收斂成正典的 changes 網址。 */
export function ConfirmPage({ brandId, campaignId, entityId, setId }: {
  brandId: string; campaignId: string; entityId?: string; setId?: string;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const homeHref = `/brands/${brandId}/ads`;

  const [queue, setQueue] = useState<QueuePayload | null>(null);
  const [changeSet, setChangeSet] = useState<ChangeSet | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [operationId] = useState(() => `triage-pause:${entityId ?? ""}:${crypto.randomUUID()}`);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [sheetOpen, setSheetOpen] = useState(false);
  const [decisionKind, setDecisionKind] = useState<DecisionKind>("deferred");
  const [reason, setReason] = useState("想再觀察幾天");
  const [quickPick, setQuickPick] = useState<QuickPick>("7");
  const [customDate, setCustomDate] = useState("");
  const [sheetError, setSheetError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    const tasks: Promise<unknown>[] = [
      getQueue(brandId).then((q) => { if (!cancelled) setQueue(q); }).catch(() => {}),
    ];
    if (setId) {
      tasks.push(
        getChangeControl(brandId, campaignId)
          .then((data) => { if (!cancelled) setChangeSet(data.change_sets.find((s) => s.id === setId) ?? null); })
          .catch((err) => { if (!cancelled) setLoadError(err instanceof Error ? err.message : "讀取這份變更清單失敗，請稍後再試。"); }),
      );
    }
    Promise.all(tasks).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [brandId, campaignId, setId, reloadKey]);

  const triageItem: QueueItem | null = useMemo(() => {
    if (!queue) return null;
    if (entityId) return queue.items.find((i) => i.triage.entity_id === entityId) ?? null;
    const targetId = changeSet?.items[0]?.target_id;
    return queue.items.find((i) => (changeSet && i.proposal?.change_set_id === changeSet.id) || i.triage.entity_id === targetId) ?? null;
  }, [queue, entityId, changeSet]);
  const position = queue && triageItem ? { pos: queue.items.indexOf(triageItem) + 1, total: queue.items.length } : null;

  // feature Decisions「Step from a change set」：非 confirm 步驟的清單，或還沒對到正典
  // changes/:setId 網址的 propose 頁，都在這裡收斂——I03/I04 加了 handoff/verify 頁之後這裡
  // 才會真的把人送到那兩頁；這批只加了 propose 與 confirm 兩條路由。
  useEffect(() => {
    if (!changeSet) return;
    const { step } = stepFromChangeSet(changeSet);
    const canonical = changeStepPath(brandId, campaignId, changeSet.id, step);
    if (canonical !== location.pathname) navigate(canonical, { replace: true });
  }, [changeSet, brandId, campaignId, location.pathname, navigate]);

  function errorMessage(err: unknown): string {
    return err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。";
  }

  /** 拿到可以動作的 change set：`changeSet` 已經有就直接用；propose 模式第一次寫入時，
   * 先看佇列列有沒有既有提議（`proposal.change_set_id`），有就重用，沒有才建立新草稿
   * （feature Decisions「first reuse proposal.change_set_id when the queue row has one」）。 */
  async function ensureWorkingSet(): Promise<ChangeSet> {
    if (changeSet) return changeSet;
    const existingId = triageItem?.proposal?.change_set_id;
    if (existingId) {
      const data = await getChangeControl(brandId, campaignId);
      const found = data.change_sets.find((s) => s.id === existingId);
      if (found) return found;
    }
    if (!triageItem) throw new Error("這則廣告的資料還沒讀到，請重新整理後再試。");
    return createChangeSet(brandId, campaignId, {
      operation_id: operationId,
      title: pauseTitle(triageItem.triage.name),
      month: currentBudgetMonth(),
      items: [buildPauseDraftItem(triageItem.triage.entity_id)],
    });
  }

  async function approveWithRebuild(target: ChangeSet, rebuilt: boolean): Promise<ChangeSet> {
    try {
      return await approveChangeSet(brandId, campaignId, target);
    } catch (err) {
      // feature Decisions「When approve answers 409 because the premise changed」：只重建一次，
      // 用新的 operation_id 帶 supersedes_id 再核准一次；再失敗就照一般錯誤處理，不無限重試。
      if (err instanceof ChangeRequestRejected && !rebuilt) {
        const rebuiltSet = await createChangeSet(brandId, campaignId, {
          operation_id: crypto.randomUUID(),
          title: target.title,
          month: target.month,
          items: target.items.map(toChangeInput),
          supersedes_id: target.id,
        });
        setChangeSet(rebuiltSet);
        return approveWithRebuild(rebuiltSet, true);
      }
      throw err;
    }
  }

  async function handleApprove() {
    if (busy) return;
    setBusy(true);
    setActionError(null);
    try {
      const target = await ensureWorkingSet();
      const updated = await approveWithRebuild(target, false);
      setChangeSet(updated);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function openSheet() {
    setDecisionKind("deferred");
    setReason("想再觀察幾天");
    setQuickPick("7");
    setCustomDate("");
    setSheetError(null);
    setSheetOpen(true);
  }

  function revisitAt(): Date | null {
    if (decisionKind !== "deferred") return null;
    if (quickPick === "custom") {
      if (!customDate) return null;
      const d = new Date(customDate);
      return Number.isNaN(d.getTime()) ? null : d;
    }
    const d = new Date();
    d.setDate(d.getDate() + (quickPick === "3" ? 3 : 7));
    return d;
  }
  const revisit = revisitAt();
  const revisitValid = decisionKind !== "deferred" || (revisit !== null && revisit.getTime() > Date.now());

  async function handleSaveDecision() {
    if (busy) return;
    const trimmedReason = reason.trim();
    if (!trimmedReason) { setSheetError("請填寫原因。"); return; }
    if (!revisitValid) { setSheetError("請選一個之後的時間。"); return; }
    setBusy(true);
    setSheetError(null);
    setActionError(null);
    try {
      const target = await ensureWorkingSet();
      const updated = await decideChangeSet(brandId, campaignId, target.id, {
        decision: decisionKind,
        reason: trimmedReason,
        ...(decisionKind === "deferred" ? { revisit_at: revisit!.toISOString() } : {}),
      });
      setChangeSet(updated);
      setSheetOpen(false);
    } catch (err) {
      setSheetError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "確認" }]} />
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-28 w-full max-w-[560px]" />
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "確認" }]} />
        <EmptyState title="讀取失敗" description={loadError} onAction={() => setReloadKey((k) => k + 1)} actionLabel="重新讀取" />
      </div>
    );
  }
  if (entityId && !triageItem) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "確認" }]} />
        <EmptyState
          title="找不到這則廣告的停損提議"
          description="可能已經處理過，或資料剛好還沒同步到投放中心。"
          actionHref={homeHref}
          actionLabel="回投放中心"
          actionInternal
        />
      </div>
    );
  }
  if (setId && !changeSet) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "確認" }]} />
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

  const { closed } = changeSet ? stepFromChangeSet(changeSet) : { closed: false };
  const item = changeSet && changeSet.items.length === 1 ? changeSet.items[0] : undefined;
  const kind = item ? item.kind : "pause";
  const blocked = changeSet !== null && (changeSet.items.length !== 1 || (kind !== "pause" && kind !== "copy" && kind !== "budget"));

  if (blocked && changeSet) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "確認" }]} />
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

  const title = kind === "copy" ? "確認變更" : kind === "budget" ? "提議：加預算" : "提議：暫停這則廣告";
  const approveLabel = kind === "copy" ? "核准，接著到平台操作" : kind === "budget" ? "核准加碼，接著到平台操作" : "核准暫停，接著到平台操作";
  const closedLabel = changeSet
    ? (changeSet.status === "superseded" ? "已由新清單取代" : `${changeSet.status === "rejected" ? "已拒絕" : "已暫緩"}・${changeSet.reason ?? ""}`)
    : "";
  const nextPauseItem = queue?.items.find((i) => i.id !== triageItem?.id && i.triage.class === "stop_loss" && !i.proposal);
  // 改文案清單、還沒關閉（草稿）、承接自某一輪檢討：返回鍵改成「修改內容」回那一輪的改文案頁
  // （v7 原型 `confirmPage()` 的 `back:i.kind==="copy"?["修改內容",...]`）；已關閉或核准之後的清單
  // （`stepFromChangeSet` 這裡不會再回傳 confirm 步驟）都留原本的「投放中心」（issue Done 3）。
  const editCopyHref = !closed && kind === "copy" && changeSet?.review_id
    ? reviewRoundPath(brandId, campaignId, changeSet.review_id, "copy")
    : null;

  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "確認" }]} />
      <FlowHeader
        steps={STEPS}
        current={0}
        title={title}
        purpose={STEP_PURPOSE}
        aside={closed ? <Chip tone="neutral">{closedLabel}</Chip> : undefined}
        context={triageItem ? (
          <>
            <Badge variant="outline" className="max-w-[14rem] shrink" title={triageItem.triage.campaign_name}>
              <span className="block w-full min-w-0 truncate">{triageItem.triage.campaign_name}</span>
            </Badge>
            {position && <span>第 {position.pos} 件／共 {position.total} 件</span>}
          </>
        ) : undefined}
      />

      {kind === "pause" && (
        <PauseEvidence
          triage={triageItem?.triage ?? null}
          fallbackName={item?.target.name ?? "（未命名廣告）"}
          fallbackReason={item?.reason ?? ""}
        />
      )}
      {kind === "copy" && item && <CopyEvidence item={item} />}
      {kind === "budget" && item && <BudgetEvidence item={item} brandId={brandId} />}

      {kind === "pause" && (
        <ReservedSlotCard
          title="這則主打什麼？"
          description="暫停後把這則廣告主打的訴求記入品牌學習，這個判斷還沒接上。"
          tag="接上後開放"
        />
      )}

      {actionError && <p role="alert" className="text-sm text-destructive">{actionError}</p>}

      <div className="flex-1" />
      <ActionBar
        back={<Button variant="ghost" asChild><Link to={editCopyHref ?? homeHref}>← {editCopyHref ? "修改內容" : "投放中心"}</Link></Button>}
        hint={!closed ? "核准不會改動平台" : undefined}
      >
        {!closed && (
          <Button variant="outline" disabled={busy} onClick={openSheet}>拒絕／暫緩</Button>
        )}
        {!closed ? (
          <Button disabled={busy} onClick={() => void handleApprove()}>{busy ? "處理中…" : `${approveLabel} →`}</Button>
        ) : nextPauseItem ? (
          <Button asChild>
            <Link to={proposePausePath(brandId, nextPauseItem.triage.campaign_id, nextPauseItem.triage.entity_id)}>下一件 →</Link>
          </Button>
        ) : null}
      </ActionBar>

      {sheetOpen && (
        <DecisionSheet
          actions={<>
            <Button variant="outline" disabled={busy} onClick={() => setSheetOpen(false)}>取消</Button>
            <Button disabled={busy} onClick={() => void handleSaveDecision()}>{busy ? "保存中…" : "保存"}</Button>
          </>}
        >
          <Segmented
            label="決定"
            options={[{ value: "deferred", label: "暫緩" }, { value: "rejected", label: "拒絕" }]}
            value={decisionKind}
            onChange={setDecisionKind}
          />
          <label className="flex min-w-[200px] flex-1 flex-col gap-1 text-sm">
            原因
            <Input value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy} />
          </label>
          {decisionKind === "deferred" && (
            <label className="flex flex-col gap-1 text-sm">
              何時重看
              <div className="flex items-center gap-2">
                <Segmented
                  label="何時重看"
                  options={[{ value: "3", label: "3 天後" }, { value: "7", label: "7 天後" }, { value: "custom", label: "自訂" }]}
                  value={quickPick}
                  onChange={setQuickPick}
                />
                {quickPick === "custom" && (
                  <Input type="date" aria-label="重看日期" value={customDate} onChange={(e) => setCustomDate(e.target.value)} disabled={busy} />
                )}
              </div>
            </label>
          )}
          {sheetError && <p role="alert" className="w-full text-xs text-destructive">{sheetError}</p>}
        </DecisionSheet>
      )}
    </div>
  );
}
