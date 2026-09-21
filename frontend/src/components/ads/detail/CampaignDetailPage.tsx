import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Image as ImageIcon } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/format";
import { listCampaigns, type CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { getQueue, getTriage, type QueueItem, type TriageClass, type TriageItem } from "@/lib/adsTriageApi";
import { ReservedSlotCard } from "../patterns";

// 跟 `home/CampaignCard.tsx` 的 `BASIS_LABEL`／`chip()` 同一份小工具——那支檔案沒有匯出，
// 這頁又不在 `frontend/src/lib/**`（do_not_touch），沿用既有先例各自留一份（precedent:
// `QueueRow.tsx`／`CampaignCard.tsx` 都各留一份自己的格式化小工具，不強行共用一個 lib）。
type Basis = "own" | "break_even" | "trailing_30";
const BASIS_LABEL: Record<Basis, string> = { own: "自訂", break_even: "損益兩平", trailing_30: "近 30 天" };

function chip(tone?: "warn") {
  return cn(
    "inline-flex w-fit shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs",
    tone === "warn" ? "bg-warning/10 text-warning" : "bg-muted text-muted-foreground",
  );
}

// 花費／每次成果成本沒有幣別（`triage`／`queue` 不回幣別，見 `QueueRow.tsx` 同名函式的
// 註解）——純數字，最多兩位小數，不用 `Math.round`；未知的量測值＝「累積中」。
function formatAmount(value: number | null): string {
  if (value === null) return "累積中";
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}
// 目標是使用者本來要不要設定的配置值，不是還在累積的量測值——未設定寫「尚未設定」
// （design-system §7：不同的未知理由要有不同的誠實句子）。
function formatTargetAmount(value: number | null): string {
  if (value === null) return "尚未設定";
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

// v7 `campPage()` 的五個分類（prototype ≈ 343）＋後端真實存在、prototype 假資料沒示範過的
// `no_target`（`app/ads/triage.py::LABELS`）：活動還沒設定目標時，每一則廣告都落在這一類，
// 不是硬塞進「資料不足」。順序跟 `home/CampaignCard.tsx` 的 `SEGMENTS` 一致，`no_target`
// 排在最後（同樣「還看不出好壞」的精神，但成因不同，不合併圖例）。
const GROUP_ORDER: TriageClass[] = ["stop_loss", "worse", "better", "flat", "insufficient", "no_target"];
const GROUP_SWATCH: Record<TriageClass, string> = {
  stop_loss: "bg-danger",
  worse: "bg-warning",
  better: "bg-success",
  flat: "bg-muted-foreground/40",
  insufficient: "bg-border",
  no_target: "bg-border",
};
// Feature Outcome：停損／變差預設展開，其餘收合。
const DEFAULT_OPEN: TriageClass[] = ["stop_loss", "worse"];

/** 廣告縮圖（issue Done #：`TriageItem.thumbnail_url` 可能是 `null`，也可能是一條會過期的
 * Meta CDN 連結）——`null` 或載入失敗都落到同一顆中性佔位圖示，不是空白、不是破圖示。 */
function AdThumb({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  const showImage = url !== null && !failed;
  return (
    <div
      className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted"
      aria-hidden="true"
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- 這裡不是 Next.js 專案。
        <img src={url} alt="" className="size-full object-cover" onError={() => setFailed(true)} />
      ) : (
        <ImageIcon className="size-4 text-muted-foreground" />
      )}
    </div>
  );
}

/** 一列廣告（v7 `rowOf()`，prototype ≈ 346–348）：縮圖・名稱・花費・每次成果成本・
 * 在佇列裡才有的「去處理」。ladder／「14 天幾乎沒投」照 Feature Decisions 省略，不是漏做。 */
function AdRow({
  item,
  queueItem,
  highlighted,
  rowRef,
}: {
  item: TriageItem;
  queueItem?: QueueItem;
  highlighted: boolean;
  rowRef: (el: HTMLDivElement | null) => void;
}) {
  const name = item.name ?? "（未命名廣告）";
  const costLabel = `每次${item.current.result_label}成本`;
  return (
    <div
      ref={rowRef}
      data-testid={`ad-row-${item.entity_id}`}
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border px-4 py-3 first:border-t-0",
        highlighted && "rounded-lg border-primary bg-accent/60 ring-1 ring-inset ring-primary",
      )}
    >
      <AdThumb url={item.thumbnail_url} />
      <p className="min-w-40 flex-1 truncate text-sm font-medium" title={name}>
        {name}
      </p>
      <div className="w-24 shrink-0 text-right">
        <p className="text-[11.5px] text-muted-foreground">花費</p>
        <p className="numeric text-sm font-semibold">{formatAmount(item.current.spend)}</p>
      </div>
      <div className="w-28 shrink-0 text-right">
        <p className="truncate text-[11.5px] text-muted-foreground" title={costLabel}>{costLabel}</p>
        <p className="numeric text-sm font-semibold">{formatAmount(item.current.cost_per_result)}</p>
      </div>
      <div className="w-24 shrink-0 text-right">
        {queueItem?.action_url && (
          <Button asChild size="sm" variant="outline">
            <Link to={queueItem.action_url}>去處理</Link>
          </Button>
        )}
      </div>
    </div>
  );
}

/** 一個分類的收合群組（v7 `<details class="grp">`，prototype ≈ 350）：色塊・分類名稱（後端
 * `label`，不臆造中文）・則數。用原生 `<details>`／`<summary>` 而不是 `patterns/Disclosure`
 * ——`Disclosure` 的 `label` 只收純字串（給「進階設定」那種單行文字用），這裡要色塊＋徽章
 * 兩截版面，且 `patterns/**` 是這張票的 do_not_touch，不能為了塞進去改它的簽章。原生
 * `<details>` 的可及性（鍵盤、螢幕報讀器）本來就到位，不用另外補。 */
function Group({
  cls,
  items,
  queueByEntity,
  open,
  onToggle,
  highlightId,
  registerRow,
}: {
  cls: TriageClass;
  items: TriageItem[];
  queueByEntity: Map<string, QueueItem>;
  open: boolean;
  onToggle: (open: boolean) => void;
  highlightId: string | null;
  registerRow: (id: string, el: HTMLDivElement | null) => void;
}) {
  return (
    <details
      open={open}
      onToggle={(e) => onToggle(e.currentTarget.open)}
      className="group surface overflow-hidden"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2.5 px-4 py-3 [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className={cn("size-2.5 shrink-0 rounded-sm", GROUP_SWATCH[cls])} />
        <span className="text-sm font-semibold">{items[0].label}</span>
        <Badge variant="secondary">{items.length} 則</Badge>
        <ChevronDown className="ml-auto size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-border">
        {items.map((item) => (
          <AdRow
            key={item.entity_id}
            item={item}
            queueItem={queueByEntity.get(item.entity_id)}
            highlighted={item.entity_id === highlightId}
            rowRef={(el) => registerRow(item.entity_id, el)}
          />
        ))}
      </div>
    </details>
  );
}

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; campaign: CampaignCardData | null; items: TriageItem[]; queue: QueueItem[] };

/** 活動詳情頁（F20-I02，v7 原型 `campPage()`，prototype ≈ 341–355）：這個活動的廣告按判斷
 * 分類分組，停損／變差預設展開；佇列裡的廣告多一顆「去處理」。名稱／目標／預算沿用
 * `home/CampaignCard.tsx` 已經在用的同一支 `listCampaigns`／`getTriage`，不再多打一支
 * API（issue Done #2）。 */
export function CampaignDetailPage({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  const [searchParams] = useSearchParams();
  const highlightAdParam = searchParams.get("ad");

  const [state, setState] = useState<State>({ status: "loading" });
  const [reload, setReload] = useState(0);
  const [openGroups, setOpenGroups] = useState<Set<TriageClass>>(() => new Set(DEFAULT_OPEN));
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    Promise.all([listCampaigns(brandId), getTriage(brandId, campaignId), getQueue(brandId)])
      .then(([campaigns, triage, queue]) => {
        if (cancelled) return;
        setState({
          status: "ready",
          campaign: campaigns.find((c) => c.id === campaignId) ?? null,
          items: triage.items,
          queue: queue.items,
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
    return () => {
      cancelled = true;
    };
  }, [brandId, campaignId, reload]);

  // `?ad=<entity_id>`（issue Done #4）：那一則所在的分類強制展開；不認得的 id 忽略，
  // 不影響原本的預設展開分類。只在第一次讀到這個 id 時處理一次，不因為使用者手動收合
  // 又被這段效果重新撐開。
  const [handledAdParam, setHandledAdParam] = useState<string | null>(null);
  useEffect(() => {
    if (state.status !== "ready" || !highlightAdParam || highlightAdParam === handledAdParam) return;
    const item = state.items.find((i) => i.entity_id === highlightAdParam);
    if (!item) return;
    setOpenGroups((prev) => new Set(prev).add(item.class));
    setHighlightId(item.entity_id);
    setHandledAdParam(highlightAdParam);
  }, [state, highlightAdParam, handledAdParam]);

  useEffect(() => {
    if (!highlightId) return;
    const el = rowRefs.current.get(highlightId);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlightId, openGroups]);

  const groupedItems = useMemo(() => {
    const map = new Map<TriageClass, TriageItem[]>();
    if (state.status === "ready") {
      for (const item of state.items) {
        const list = map.get(item.class);
        if (list) list.push(item);
        else map.set(item.class, [item]);
      }
    }
    return map;
  }, [state]);

  const queueByEntity = useMemo(() => {
    const map = new Map<string, QueueItem>();
    if (state.status === "ready") {
      for (const q of state.queue) map.set(q.triage.entity_id, q);
    }
    return map;
  }, [state]);

  const homeHref = `/brands/${brandId}/ads`;
  const workspaceHref = `/brands/${brandId}/ads/campaigns/${campaignId}`;
  const targetHref = `${workspaceHref}/target`;

  if (state.status === "loading") {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "活動" }]} />
        <Skeleton className="h-9 w-80" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "活動" }]} />
        <EmptyState title="讀取失敗" description={state.message} onAction={() => setReload((v) => v + 1)} actionLabel="重新讀取" />
      </div>
    );
  }

  const { campaign, items } = state;

  if (campaign === null) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "活動" }]} />
        <EmptyState title="讀取失敗" description="找不到這個 Campaign。" onAction={() => setReload((v) => v + 1)} actionLabel="重新讀取" />
      </div>
    );
  }

  const budgetTotal = campaign.budget_progress.total;
  const budgetChip = campaign.origin === "imported"
    ? <span className={chip()}>平台預算</span>
    : budgetTotal !== null
      ? <span className={chip()}>總預算 {formatCurrency(budgetTotal)}</span>
      : <span className={chip("warn")}>預算待核實</span>;

  // 沒有廣告資料（草稿／待發布／剛同步）：跟 `home/CampaignCard.tsx` 同一條規則——不會
  // 判斷，催著設目標也沒用，只留「全部資料 ›」進去活動本身（review 裁決 #2 的同一個理由）。
  const target = items.length > 0 ? items[0].target : null;
  const hasTarget = target !== null && target.value !== null;

  return (
    <div className="flex flex-col gap-5">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: campaign.name }]} />

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold" title={campaign.name}>{campaign.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className={chip()}>{campaign.objective || "尚待確認"}・{items.length} 則</span>
            {items.length > 0 && (
              hasTarget ? (
                <span className={chip()}>
                  目標每次{target!.result_label}成本 {formatTargetAmount(target!.value)}
                  {target!.basis && `・${BASIS_LABEL[target!.basis]}`}
                </span>
              ) : (
                <span className={chip("warn")}>尚未設定目標</span>
              )
            )}
            {budgetChip}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {items.length > 0 && (
            <Button variant="outline" asChild>
              <Link to={targetHref}>{hasTarget ? "調整目標" : "設定目標"}</Link>
            </Button>
          )}
          <Button variant="ghost" asChild>
            <Link to={workspaceHref}>全部資料 ›</Link>
          </Button>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="surface p-5">
          <p className="text-sm text-muted-foreground">沒有廣告資料，這個活動還沒有可以判斷的內容。</p>
        </div>
      ) : (
        <>
          {!hasTarget && (
            <div className="flex flex-wrap items-center gap-3 rounded-xl bg-warning/10 p-4">
              <span aria-hidden="true" className="text-lg">🎯</span>
              <p className="flex-1 text-sm font-medium text-warning">沒有目標，這個活動的廣告都還不會被判斷</p>
              <Button size="sm" asChild>
                <Link to={targetHref}>設定目標 →</Link>
              </Button>
            </div>
          )}

          {/* 容量卡（Feature Decisions）：`「同時在投 N 則／提議暫停」` 這個能力還沒接上——
             一張佔位卡，不是假出一個「撐得起幾則」的數字。 */}
          <ReservedSlotCard
            title={`同時在投 ${items.length} 則`}
            description="預算能撐得起幾則廣告、要不要提議暫停沒在投的廣告，這個判斷還沒接上。"
            tag="接上後開放"
          />

          <div className="flex flex-col gap-2.5">
            {GROUP_ORDER.filter((cls) => (groupedItems.get(cls)?.length ?? 0) > 0).map((cls) => (
              <Group
                key={cls}
                cls={cls}
                items={groupedItems.get(cls)!}
                queueByEntity={queueByEntity}
                open={openGroups.has(cls)}
                onToggle={(isOpen) =>
                  setOpenGroups((prev) => {
                    const next = new Set(prev);
                    if (isOpen) next.add(cls);
                    else next.delete(cls);
                    return next;
                  })
                }
                highlightId={highlightId}
                registerRow={(id, el) => {
                  if (el) rowRefs.current.set(id, el);
                  else rowRefs.current.delete(id);
                }}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
