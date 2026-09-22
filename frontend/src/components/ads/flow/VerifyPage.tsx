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
  type SettingValues,
} from "@/lib/adsChangeApi";
import { getQueue, type QueuePayload } from "@/lib/adsTriageApi";
import { ActionBar, FlowHeader, ResultHero, StatusRail, type RailCell } from "../patterns";
import { CLEANUP_HERO_TITLE, CleanupVerifyRows, cleanupOverallState } from "./CleanupVerifyRows";
import {
  campaignChangesPath,
  changeStepPath,
  findFlowTriageItem,
  flowPosition,
  formatTargetAmount,
  isCleanupTriageItem,
  nextOpenQueueItem,
  proposePausePath,
  queueItemEntityId,
  stepFromChangeSet,
} from "./changeFlow";

const STEP_PURPOSE = "系統讀回平台確認";
type Kind = "pause" | "copy" | "budget" | "new_ad";

const STATUS_LABEL: Record<string, string> = { ACTIVE: "啟用", PAUSED: "暫停", ARCHIVED: "已封存", DELETED: "已刪除" };
function statusLabel(value: string | null | undefined): string {
  if (!value) return "尚待確認";
  return STATUS_LABEL[value] ?? "尚待確認";
}
/** `evidence_json.message` only exists on some read-backs (`app/ads/change_control_verify.py`);
 * anything else in that bag is not ours to interpret (feature Decisions). */
function messageOf(item: ChangeItem): string | undefined {
  const value = item.evidence_json.message;
  return typeof value === "string" ? value : undefined;
}
/** 「讀回於」＝`evidence_json.observed_at`，瀏覽器本地時間；沒有就是「尚未讀到」
 * （feature Decisions「Verify」）。 */
function observedAtText(item: ChangeItem): string {
  const value = item.evidence_json.observed_at;
  if (typeof value !== "string") return "尚未讀到";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "尚未讀到" : d.toLocaleString("zh-TW");
}

const CONFIRMED_TITLE: Record<Kind, (item: ChangeItem) => string> = {
  copy: () => "平台上的文案和你核准的一樣",
  pause: () => "平台上這則廣告已經關閉",
  budget: (item) => `平台上的每日預算已經是 ${formatTargetAmount(item.after.daily_amount ?? null)}`,
  // F27-I15: a `new_ad` item's own readback is the ManualHandoffPanel/`ads_handoff_item` aggregate
  // (`app/ads/handoff_check.py::_finish`), never a settings diff like the other three kinds.
  new_ad: () => "平台上這則新廣告已經核對完成",
};
const DEVIATED_TITLE: Record<Kind, string> = {
  copy: "平台上的內文和核准的不一樣",
  pause: "平台上的狀態和核准的不一樣",
  budget: "平台上的每日預算和核准的不一樣",
  new_ad: "平台上這則新廣告和核准的內容不一樣",
};
/** StatusRail 只畫有資料來源的格子：`設定相符` 讀 `evidence_json.setting_matches`；花費停止／
 * 學習期／成效回看／已記入品牌學習都沒有後端支撐，整格省略（feature Decisions「Gaps」）。 */
function confirmedRailNote(item: ChangeItem, kind: Kind): string {
  if (kind === "copy") return "標題、內文";
  if (kind === "budget") return `每日 ${formatTargetAmount(item.after.daily_amount ?? null)}`;
  if (kind === "new_ad") return "已對應平台上的廣告物件";
  return `狀態：${statusLabel(item.after.status)}`;
}

/** deviated 的「你核准的 / 平台目前」對照：文案是逐行標記差異（跟 `ConfirmPage`／`handoff()`
 * 的舊文案收合同一種標記法），其他 kind 只是單一數值，不用逐行邏輯（feature Decisions
 * 「deviated (copy: ... differing lines marked; other kinds: approved value vs observed value)」）。 */
function DeviatedCompare({ item, kind }: { item: ChangeItem; kind: Kind }) {
  const observed = (item.evidence_json.observed ?? {}) as SettingValues;
  if (kind === "copy") {
    const approvedLines = new Set((item.after.body ?? "").split("\n"));
    const observedLines = (observed.body ?? "").split("\n");
    return (
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-card p-4">
          <h3 className="mb-2 text-sm font-medium">你核准的</h3>
          <div className="rounded-md bg-accent/60 p-3 text-sm">
            <b className="block">{item.after.title ?? "—"}</b>
            <p className="mt-1 whitespace-pre-wrap">{item.after.body ?? "—"}</p>
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <h3 className="mb-2 text-sm font-medium">平台目前</h3>
          <div className="rounded-md bg-muted p-3 text-sm">
            <b className="block">{observed.title ?? "—"}</b>
            <p className="mt-1 whitespace-pre-wrap">
              {observedLines.map((line, i) => (
                <span key={i}>
                  {approvedLines.has(line) ? line : <mark>{line}</mark>}
                  {i < observedLines.length - 1 ? "\n" : null}
                </span>
              ))}
            </p>
          </div>
        </div>
      </div>
    );
  }
  const label = kind === "pause" ? "狀態" : "每日預算";
  const approvedValue = kind === "pause" ? statusLabel(item.after.status) : formatTargetAmount(item.after.daily_amount ?? null);
  const observedValue = kind === "pause" ? statusLabel(observed.status) : formatTargetAmount(observed.daily_amount ?? null);
  return (
    <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="mb-2 text-sm font-medium">你核准的</h3>
        <p className="text-sm">{label}：{approvedValue}</p>
      </div>
      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="mb-2 text-sm font-medium">平台目前</h3>
        <p className="text-sm">{label}：{observedValue}</p>
      </div>
    </div>
  );
}

/** 核對結果頁（F22-I04，v7 原型 `verify()`）：三步驟輕流程第三步，只走
 * `changes/:setId/verify` 這條正典網址。原型的 demo 資料只走得到 `confirmed`（`act.check()`
 * 對非 copy kind 一律寫回 confirmed）；`deviated`／`stale` 的畫法照原型 copy kind 的展示邏輯
 * 類推到其他 kind（差異逐行標記只對文字內容有意義）。`pending`（`reported_at` 已寫入）與
 * `reported`／`unknown` 兩種原型沒畫過的狀態，照 feature Decisions 給的文案與動作組裝
 * （neutral hero／`平台上還是原本的設定`），不是重新設計。 */
export function VerifyPage({ brandId, campaignId, setId }: {
  brandId: string; campaignId: string; setId: string;
}) {
  const navigate = useNavigate();
  const homeHref = `/brands/${brandId}/ads`;
  const crumb = [{ label: "投放中心", href: homeHref }, { label: "核對結果" }];

  const [queue, setQueue] = useState<QueuePayload | null>(null);
  const [changeSet, setChangeSet] = useState<ChangeSet | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

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

  // feature Decisions「Step from a change set」：這一步只服務 approved 且已經有讀回紀錄的清單
  // （pending 但 reported_at 還沒寫入的留給 handoff 頁），其他狀態都導去正確的步驟。
  useEffect(() => {
    if (!changeSet) return;
    const { step } = stepFromChangeSet(changeSet);
    if (step !== "verify") navigate(changeStepPath(brandId, campaignId, changeSet.id, step), { replace: true });
  }, [changeSet, brandId, campaignId, navigate]);

  function errorMessage(err: unknown): string {
    return err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。";
  }

  async function handleCheck(item: ChangeItem) {
    if (busy || !changeSet) return;
    setBusy(true);
    setActionError(null);
    try {
      const updated = await actOnChangeItem(brandId, campaignId, changeSet.id, item.id, "check");
      setChangeSet(updated);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  /** F27-I15 Contract F: cleanup 沒有一次核對整批的後端動作，逐項呼叫既有的單項 `check`——跟
   * `handleCheck` 同一顆錯誤處理，只是對每個 item 各跑一次；每一次回應都整份更新
   * `changeSet`（後端 `change_control_data.get` 本來就重算全部 items），中途失敗就停在已完成的
   * 進度，不整批重來。 */
  async function handleCheckAll() {
    if (busy || !changeSet) return;
    setBusy(true);
    setActionError(null);
    try {
      let current = changeSet;
      for (const row of current.items) {
        current = await actOnChangeItem(brandId, campaignId, current.id, row.id, "check");
        setChangeSet(current);
      }
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

  // F27-I15 Contract F: a cleanup set is only ever recognised through the queue's own `cleanup`
  // row (`isCleanupTriageItem`, same lookup `ConfirmPage`/`HandoffPage` use) — never guessed from
  // item shape, so a generic multi-`pause` set with no cleanup row behind it still falls through
  // to the existing "多項變更" workspace link below, unchanged from before this issue.
  const cleanupSet = isCleanupTriageItem(triageItem);
  const item: ChangeItem | undefined = changeSet.items.length === 1 ? changeSet.items[0] : undefined;
  const kindRaw = cleanupSet ? "cleanup" : item ? item.kind : "pause";
  const blocked = !cleanupSet
    && (changeSet.items.length !== 1 || !["pause", "copy", "budget", "new_ad"].includes(kindRaw));

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

  const steps = [
    { label: "確認提議", to: changeStepPath(brandId, campaignId, changeSet.id, "confirm") },
    { label: "到平台完成", to: changeStepPath(brandId, campaignId, changeSet.id, "handoff") },
    { label: "核對結果" },
  ];
  const context = triageItem ? (
    <>
      <Badge variant="outline" className="max-w-[14rem] shrink" title={triageItem.triage.campaign_name}>
        <span className="block w-full min-w-0 truncate">{triageItem.triage.campaign_name}</span>
      </Badge>
      {position && <span>第 {position.pos} 件／共 {position.total} 件</span>}
    </>
  ) : undefined;

  // 「下一件」（F25-I03）：跟 ConfirmPage 的關閉態共用同一顆判斷，不各自算各自的
  // （feature Decisions「下一件」——`changeFlow.ts::nextOpenQueueItem`，涵蓋全部四種 kind）。
  const currentEntityId = triageItem ? queueItemEntityId(triageItem) : undefined;
  const nextAction = nextOpenQueueItem(queue, currentEntityId);
  const nextOrHome = nextAction
    ? <Button asChild><Link to={nextAction.href}>下一件 →</Link></Button>
    : <Button asChild><Link to={homeHref}>回投放中心 →</Link></Button>;

  // F27-I15 Contract F Screens「Flow pages, new-ad and multi-item」: 「verify... one row per item
  // with its own state and a summary hero by the worst state」——整支跟單項 kind 的
  // confirmed/deviated/stale/pending-old/checking 分支是不同的畫法（沒有單一 `before/after` 可比
  // 較），提早分支，不硬套下面的單項邏輯。
  if (cleanupSet) {
    const overall = cleanupOverallState(changeSet.items);
    const hero = (
      <ResultHero
        tone={overall === "confirmed" ? "ok" : overall === "deviated" || overall === "stale" ? "bad" : "warn"}
        title={CLEANUP_HERO_TITLE[overall]}
      />
    );
    return (
      <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
        <Breadcrumb items={crumb} />
        <FlowHeader steps={steps} current={2} title="核對結果" purpose={STEP_PURPOSE} context={context} />
        {hero}
        <CleanupVerifyRows items={changeSet.items} />
        {actionError && <p role="alert" className="text-sm text-destructive">{actionError}</p>}
        <div className="flex-1" />
        <ActionBar>
          <Button variant="outline" disabled={busy} onClick={() => void handleCheckAll()}>{busy ? "核對中…" : "⟳ 全部重新核對"}</Button>
          {nextOrHome}
        </ActionBar>
      </div>
    );
  }

  // Unreachable in practice — the guard above already returned when `!cleanupSet && !item`; this
  // narrows `item` for the type checker without re-deriving the guard's own logic a second time.
  if (!item) return null;

  const kind = kindRaw as Kind;
  const again = (
    <Button variant="outline" disabled={busy} onClick={() => void handleCheck(item)}>
      {busy ? "核對中…" : "⟳ 重新核對"}
    </Button>
  );

  const state: "confirmed" | "deviated" | "stale" | "pending-old" | "checking" =
    item.verification_state === "confirmed" ? "confirmed"
    : item.verification_state === "deviated" ? "deviated"
    : item.verification_state === "stale" ? "stale"
    : item.verification_state === "pending" ? "pending-old"
    : "checking";

  let hero: ReactNode;
  let rail: ReactNode = null;
  let compare: ReactNode = null;
  let bar: ReactNode;

  if (state === "confirmed") {
    hero = <ResultHero tone="ok" title={CONFIRMED_TITLE[kind](item)} note={`讀回於 ${observedAtText(item)}`} />;
    const cells: RailCell[] = item.evidence_json.setting_matches === true
      ? [{ title: "設定相符", note: confirmedRailNote(item, kind), ok: true }]
      : [];
    rail = <StatusRail cells={cells} />;
    bar = (
      <ActionBar>
        {again}
        {nextAction ? (
          <Button asChild><Link to={nextAction.href}>下一件 →</Link></Button>
        ) : (
          <Button asChild><Link to={homeHref}>回投放中心 →</Link></Button>
        )}
      </ActionBar>
    );
  } else if (state === "deviated") {
    hero = <ResultHero tone="warn" title={DEVIATED_TITLE[kind]} note={`讀回於 ${observedAtText(item)}`} />;
    // F27-I15: `DeviatedCompare`'s before/after table only makes sense for a plain settings diff
    // (copy/pause/budget) — a `new_ad` item's evidence is the handoff aggregate, no `observed`/
    // `expected` settings pair to line up (`messageOf(item)` in the hero note is the only signal
    // this kind's evidence carries).
    if (kind !== "new_ad") compare = <DeviatedCompare item={item} kind={kind} />;
    bar = (
      <ActionBar>
        {again}
        <Button asChild>
          <Link to={changeStepPath(brandId, campaignId, changeSet.id, "handoff")}>回平台改成核准內容 →</Link>
        </Button>
      </ActionBar>
    );
  } else if (state === "stale") {
    const staleNote = item.stale_reason ?? messageOf(item) ?? "用現在的資料重新檢討一次；舊紀錄都會保留";
    hero = <ResultHero tone="bad" title="這則廣告的設定變了，原本的核准不再適用" note={staleNote} />;
    const restartHref = kind === "pause"
      ? proposePausePath(brandId, campaignId, item.target_id)
      : campaignChangesPath(brandId, campaignId);
    bar = (
      <ActionBar back={<Button variant="ghost" asChild><Link to={homeHref}>← 投放中心</Link></Button>}>
        <Button asChild><Link to={restartHref}>重新檢討 →</Link></Button>
      </ActionBar>
    );
  } else if (state === "pending-old") {
    hero = <ResultHero tone="warn" title="平台上還是原本的設定" note={messageOf(item) ?? "這項操作尚未完成。"} />;
    bar = (
      <ActionBar>
        {again}
        <Button asChild>
          <Link to={changeStepPath(brandId, campaignId, changeSet.id, "handoff")}>回平台完成 →</Link>
        </Button>
      </ActionBar>
    );
  } else {
    hero = <ResultHero tone="neutral" title="還沒讀到平台上的新設定" note={messageOf(item) ?? "稍後重新核對即可。"} />;
    bar = <ActionBar>{again}</ActionBar>;
  }

  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb items={crumb} />
      <FlowHeader steps={steps} current={2} title="核對結果" purpose={STEP_PURPOSE} context={context} />

      {hero}
      {rail}
      {compare}

      {/* Contract E / F27-I05: only ever set on a `new_ad` set's own `follow_up` once that item
          reads back confirmed and no pause set for the old ad already exists — a plain read, no
          local "is this ready" logic duplicated here. */}
      {changeSet.follow_up && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-4">
          <p className="text-sm text-muted-foreground">新廣告已經確認在平台上，接著可以暫停原本那則廣告。</p>
          <Button asChild><Link to={proposePausePath(brandId, campaignId, changeSet.follow_up.entity_id)}>暫停舊廣告 →</Link></Button>
        </div>
      )}

      {actionError && <p role="alert" className="text-sm text-destructive">{actionError}</p>}

      <div className="flex-1" />
      {bar}
    </div>
  );
}
