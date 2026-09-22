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
import { Chip, ReservedSlotCard } from "../patterns";
import { proposalAction } from "../home/status";

// 跟 `home/CampaignCard.tsx` 的 `BASIS_LABEL` 同一份小工具——那支檔案沒有匯出，
// 這頁又不在 `frontend/src/lib/**`（do_not_touch），沿用既有先例各自留一份（precedent:
// `QueueRow.tsx`／`CampaignCard.tsx` 都各留一份自己的格式化小工具，不強行共用一個 lib）。
type Basis = "own" | "break_even" | "trailing_30";
const BASIS_LABEL: Record<Basis, string> = { own: "自訂", break_even: "損益兩平", trailing_30: "近 30 天" };

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
// v7 `campPage()` 分類 summary 右側的提示（prototype ≈ 350）：只有「持平」「資料不足」有
// 固定字句；停損／變差／變好／尚未設定目標一律不印。「資料不足」原型還會接一句
// 「（目標 × 3）」的金額，那個 3 倍數字是後端常數（`STOP_LOSS_SPEND_MULTIPLE`），
// `TriageItem` 沒有把它带出來——lead 裁決：不在前端算，只印沒有金額的句子。
const GROUP_HINT: Partial<Record<TriageClass, string>> = {
  flat: "照常投放",
  insufficient: "還沒花到可判讀的金額",
};

/** 這個活動預設要開哪些分類（review fix：從不能讓整頁只剩收合列）。有停損／變差就開那
 * 兩類（Feature Outcome）；兩類都不存在時（今天的真實 Beast Prime 資料、尚未設定目標的
 * 活動都是這樣），改開 `GROUP_ORDER` 裡第一個有廣告的分類，讓使用者一進來就看得到列。 */
function initialOpenGroups(items: TriageItem[]): Set<TriageClass> {
  const present = new Set(items.map((item) => item.class));
  if (present.has("stop_loss") || present.has("worse")) return new Set(DEFAULT_OPEN);
  const first = GROUP_ORDER.find((cls) => present.has(cls));
  return first ? new Set([first]) : new Set();
}

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
 * 在佇列裡才有的「去處理」。ladder／「14 天幾乎沒投」照 Feature Decisions 省略，不是漏做。
 *
 * lead 裁決（review fix）：「去處理」不能連 `queueItem.action_url`——F20-I01 把佇列的
 * `action_url` 改指到「這一頁」（`.../detail?ad=<id>`），這裡再用它會原地繞一圈、按了
 * 沒反應。六步驟審核流程還沒重建前，這顆按鈕連去既有工作區的「成效」分頁（現有的處理
 * 入口）；還是不是在佇列裡（`queueItem` 有沒有值）決定要不要印這顆按鈕。
 *
 * F22-I05：停損分類的廣告改走 `proposalAction`（跟 `home/QueueRow.tsx` 同一支），按鈕印目前
 * 進度而不是固定的「去處理」。F23-I05：`worse` 分類現在也走同一支（`kind: "review"`）——
 * 這批唯一還留著舊「去處理」規則的分類只剩不在 stop_loss／worse 的其他項（目前沒有，這裡
 * 留一個誠實的 fallback，不是預期路徑）。 */
function AdRow({
  brandId,
  item,
  queueItem,
  reviewHref,
  highlighted,
  rowRef,
}: {
  brandId: string;
  item: TriageItem;
  queueItem?: QueueItem;
  reviewHref: string;
  highlighted: boolean;
  rowRef: (el: HTMLDivElement | null) => void;
}) {
  const name = item.name ?? "（未命名廣告）";
  const costLabel = `每次${item.current.result_label}成本`;
  const action = queueItem && (item.class === "stop_loss" || item.class === "worse")
    ? proposalAction(
        brandId, item.campaign_id, item.entity_id, queueItem.proposal,
        item.class === "worse" ? "review" : "pause",
      )
    : null;
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
        {action ? (
          <Button asChild size="sm" variant={action.done ? "ghost" : "outline"}>
            <Link to={action.href}>{action.label}</Link>
          </Button>
        ) : (
          queueItem && (
            <Button asChild size="sm" variant="outline">
              <Link to={reviewHref}>去處理</Link>
            </Button>
          )
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
  brandId,
  cls,
  items,
  queueByEntity,
  reviewHref,
  open,
  onToggle,
  highlightId,
  registerRow,
}: {
  brandId: string;
  cls: TriageClass;
  items: TriageItem[];
  queueByEntity: Map<string, QueueItem>;
  reviewHref: string;
  open: boolean;
  onToggle: (open: boolean) => void;
  highlightId: string | null;
  registerRow: (id: string, el: HTMLDivElement | null) => void;
}) {
  return (
    <details
      open={open}
      onToggle={(e) => onToggle(e.currentTarget.open)}
      // `overflow-hidden` 不能加在這裡——`:focus-visible` 是外擴 3px 的 outline
      // （tokens.css），加了會把鍵盤聚焦 summary 的框裁掉一截（`CampaignTargetPage.tsx`
      // 同一個坑的既有修法）。不需要它也能看：`.surface` 本身圓角，內容背景跟卡片同色。
      className="group surface"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2.5 px-4 py-3 [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className={cn("size-2.5 shrink-0 rounded-sm", GROUP_SWATCH[cls])} />
        <span className="text-sm font-semibold">{items[0].label}</span>
        <Badge variant="secondary">{items.length} 則</Badge>
        {GROUP_HINT[cls] && (
          <span className="ml-auto truncate text-xs text-muted-foreground">{GROUP_HINT[cls]}</span>
        )}
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180", !GROUP_HINT[cls] && "ml-auto")} />
      </summary>
      <div className="border-t border-border">
        {items.map((item) => (
          <AdRow
            key={item.entity_id}
            brandId={brandId}
            item={item}
            queueItem={queueByEntity.get(item.entity_id)}
            reviewHref={reviewHref}
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
    Promise.all([
      listCampaigns(brandId),
      getTriage(brandId, campaignId),
      // review fix：佇列只餵這頁一顆選用的「去處理」按鈕，不是這頁存在的理由——`getQueue`
      // 失敗不該連目標／分類／列都一起讀不出來（同 `AdsHomePage.tsx:19-20` 佇列／月預算／
      // 活動卡三塊分開讀取、互不拖累的原則）。失敗時當作「這次沒有廣告在佇列裡」，頁面照常
      // 顯示，只是沒有「去處理」按鈕。
      getQueue(brandId).catch(() => ({ items: [] as QueueItem[] })),
    ])
      .then(([campaigns, triage, queue]) => {
        if (cancelled) return;
        setState({
          status: "ready",
          campaign: campaigns.find((c) => c.id === campaignId) ?? null,
          items: triage.items,
          queue: queue.items,
        });
        setOpenGroups(initialOpenGroups(triage.items));
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

  // review fix：`openGroups` 每次收合／展開都是新的 `Set`，這個 effect 原本連著它一起重跑，
  // 使用者手動摺疊別的分類就會把畫面重新捲回高亮那一列一次。只在真的換了一個新的
  // `highlightId` 時捲一次；捲過就記住，之後任何 `openGroups` 變化都不再觸發。
  const scrolledToRef = useRef<string | null>(null);
  useEffect(() => {
    if (!highlightId || scrolledToRef.current === highlightId) return;
    const el = rowRefs.current.get(highlightId);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    scrolledToRef.current = highlightId;
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
      <div className="flex max-w-[1180px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "活動" }]} />
        <Skeleton className="h-9 w-80" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex max-w-[1180px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "活動" }]} />
        <EmptyState title="讀取失敗" description={state.message} onAction={() => setReload((v) => v + 1)} actionLabel="重新讀取" />
      </div>
    );
  }

  const { campaign, items } = state;

  if (campaign === null) {
    return (
      <div className="flex max-w-[1180px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "活動" }]} />
        <EmptyState title="讀取失敗" description="找不到這個 Campaign。" onAction={() => setReload((v) => v + 1)} actionLabel="重新讀取" />
      </div>
    );
  }

  const budgetTotal = campaign.budget_progress.total;
  const budgetChip = campaign.origin === "imported"
    ? <Chip>平台預算</Chip>
    : budgetTotal !== null
      ? <Chip>總預算 {formatCurrency(budgetTotal)}</Chip>
      : <Chip tone="warn">預算待核實</Chip>;

  // 沒有廣告資料（草稿／待發布／剛同步）：跟 `home/CampaignCard.tsx` 同一條規則——不會
  // 判斷，催著設目標也沒用，只留「全部資料 ›」進去活動本身（review 裁決 #2 的同一個理由）。
  const target = items.length > 0 ? items[0].target : null;
  const hasTarget = target !== null && target.value !== null;

  return (
    // v7 `.page{max-width:1180px}`（prototype 行 27）：不跟著殼一路撐到 1920——名稱跟數字
    // 中間空一大段反而更難對照。跟 `SettingsPage.tsx` 用同一種寫法（外層 `max-w-[…px]`
    // 字面值，不是共用元件），這裡照抄原型的 1180px。
    <div className="flex max-w-[1180px] flex-col gap-5">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: campaign.name }]} />

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold" title={campaign.name}>{campaign.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {/* review fix：跟 `home/CampaignCard.tsx:215-221` 同一顆欄位同一種處理——匯入
               活動的 objective 是一整句話，只有它自己截斷，「・N 則」永遠印得出來，
               1024 寬不會被擠到換行。 */}
            <Chip className="max-w-[14rem] items-center">
              <span className="min-w-0 truncate" title={campaign.objective || undefined}>
                {campaign.objective || "尚待確認"}
              </span>
              <span className="shrink-0">・{items.length} 則</span>
            </Chip>
            {items.length > 0 && (
              hasTarget ? (
                <Chip>
                  目標每次{target!.result_label}成本 {formatTargetAmount(target!.value)}
                  {target!.basis && `・${BASIS_LABEL[target!.basis]}`}
                </Chip>
              ) : (
                <Chip tone="warn">尚未設定目標</Chip>
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
                brandId={brandId}
                cls={cls}
                items={groupedItems.get(cls)!}
                queueByEntity={queueByEntity}
                reviewHref={`${workspaceHref}?tab=performance`}
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
