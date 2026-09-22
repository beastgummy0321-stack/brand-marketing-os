import { useEffect, useMemo, useState } from "react";
import { Image as ImageIcon } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { getMonthlyBudget, type MonthlyBudget } from "@/lib/adsChangeApi";
import {
  dismissSuggestion, getMonthSummary,
  type MonthCampaignRow, type MonthOrders, type MonthSuggestion, type MonthSummary, type SuggestionKind,
} from "@/lib/adsMonthApi";
import { getAdsLearnings, type AdsLearning } from "@/lib/adsLearningsApi";
import { listCampaigns, type CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { getTriage, type TriageClosedBlock, type TriageClosedItem, type TriageItem } from "@/lib/adsTriageApi";
import { ActionBar, CampaignChip, Chip, LearnCard, Meter, Segmented, type ObjectiveKey } from "../patterns";
import { budgetMoney, currentBudgetMonth } from "../MonthlyBudgetPanel";

/** 每月回顧（F24-I04 起，F27-I19 改由 Contract G 的月摘要驅動；v7 原型 `month()`）：活動照常
 * 投放，這頁只整理帳——內部投放計畫與平台原生物件不受影響，這裡不寫任何東西回廣告平台。
 * 全品牌花費／訂單／各活動／這個月關掉／下月建議都讀 `getMonthSummary`＋`getMonthlyBudget`
 * （月選單切換時兩個一起重打）；素材分組跟品牌學習清單各自留自己的資料來源（見下方對應
 * 區塊的說明），一個失敗不拖累其他區塊（design-system §1.7 worker self-check #9）。 */

// 純數字，最多兩位小數，不四捨五入到整數（各活動列的花費／成本／目標沒有個別幣別，跟
// `home/CampaignCard.tsx`／`detail/CampaignDetailPage.tsx` 各自留一份的先例一樣，這支不在
// `frontend/src/lib/**`，不能共用一份）。未知的量測值＝「累積中」（design-system §7）。
function formatAmount(value: number | null): string {
  if (value === null) return "累積中";
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

// 本機日曆日期小工具（同 `wait/WaitPage.tsx` 的先例，各自留一份）。
function parseLocalDateParts(iso: string): { y: number; m: number; d: number } {
  const [y, m, d] = iso.split("-").map(Number);
  return { y, m, d };
}
function formatYMD(iso: string): string {
  const { y, m, d } = parseLocalDateParts(iso);
  return `${y}/${m}/${d}`;
}
function shiftMonth(base: string, delta: number): string {
  const [y, m] = base.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

// `▲12%`／`▼12%`／`持平`；同 `home/QueueRow.tsx::formatDeltaPct` 的先例（各自留一份，那支不在
// `frontend/src/lib/**`）。`change_pct` 是比值，`null` 就不印（沒有前一期資料可比）。
function formatChangePct(pct: number | null): string {
  if (pct === null) return "";
  const rounded = Math.round(Math.abs(pct) * 100);
  if (rounded === 0) return "持平";
  return `${pct > 0 ? "▲" : "▼"}${rounded}%`;
}

// F27-I27: one objective-family rule, not two -- every `campaign_objective` field below comes
// straight from `app/ads/repository.py::campaign_objective_family` (the SAME function
// `CampaignChip` on campaign cards/triage items already reads through, F27-I09). No more local
// keyword guessing off the raw `objective` string; this helper only supplies `CampaignChip`'s
// required, non-null prop when the backend value is `null`/`undefined` (unknown campaign, or an
// older hand-written test fixture that never set it) -- never a different classification.
function chipObjective(family?: ObjectiveKey | null): ObjectiveKey {
  return family ?? "other";
}

const VERDICT: Record<MonthCampaignRow["verdict"], { label: string; tone: "ok" | "warn" | "neutral" }> = {
  met: { label: "達標", tone: "ok" },
  missed: { label: "未達標", tone: "warn" },
  unjudged: { label: "未判斷", tone: "neutral" },
};

const CONFIDENCE: Record<AdsLearning["confidence"], { label: string; tone: "neutral" | "accent" | "ok" }> = {
  observed: { label: "觀察到", tone: "neutral" },
  likely: { label: "可能成立", tone: "accent" },
  validated: { label: "成立", tone: "ok" },
};

const SUGGESTION_ICON: Record<SuggestionKind, string> = { refresh: "🖼", cleanup: "🧹", no_target: "🎯" };

/** 未知態的量尺（`Meter`／`patterns/**` 是這張票的 `do_not_touch`，不能加一個「打斜紋」變體
 * 進共用元件）——同 `home/CampaignCard.tsx` 的 `HatchedStrip` 先例，這支自己留一份，尺寸跟
 * `Meter` 的軸一致（`h-2.5 rounded-md`），這樣兩種量尺疊在同一欄看起來還是同一組。 */
function HatchedMeter({ left, right }: { left?: string; right?: string }) {
  return (
    <div data-slot="meter">
      <div
        aria-hidden="true"
        className="mt-1.5 mb-1 h-2.5 rounded-md bg-muted"
        style={{
          backgroundImage:
            "repeating-linear-gradient(45deg, var(--color-border), var(--color-border) 4px, transparent 4px, transparent 8px)",
        }}
      />
      {(left || right) && (
        <div className="numeric flex justify-between gap-2 text-[11.5px] text-muted-foreground">
          <span>{left}</span>
          <span>{right}</span>
        </div>
      )}
    </div>
  );
}

/** 廣告縮圖（同 `detail/CampaignDetailPage.tsx` 的 `AdThumb` 先例，這支不在 touch 範圍內，
 * 不能匯出共用，這裡自己留一份一樣的行為：`null` 或載入失敗都落到中性佔位圖示）。 */
function MaterialThumb({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  const showImage = url !== null && !failed;
  return (
    <div
      data-testid="material-thumb"
      className="flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted"
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

type MonthChoice = "this" | "last";

type MonthState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; summary: MonthSummary; budget: MonthlyBudget };

/** 全品牌花費卡：月選單驅動這張卡＋商城訂單卡＋各活動／這個月關掉／下月建議（月摘要＋月
 * 預算一起重打，見 `MonthReviewPage` 的 `monthState`）。`total_spend === null`（這個月有已知
 * 天數缺花費，或跨幣別）沒有量尺，只印「花費未核實」；`budget.amount === null`（月總額還沒
 * 設定）打斜紋量尺；兩者都有值才是真的量尺。 */
function SpendCard({ summary, budget }: { summary: MonthSummary; budget: MonthlyBudget }) {
  return (
    <div className="surface p-5">
      <div className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
        <span>全品牌花費</span>
        <span>{budget.amount === null ? "月總額 尚未設定" : `月總額 ${budgetMoney(budget.amount, budget.currency)}`}</span>
      </div>
      {summary.total_spend === null ? (
        <p className="mt-1 text-2xl font-semibold text-muted-foreground">花費未核實</p>
      ) : (
        <>
          <p className="numeric mt-1 text-2xl font-semibold">{budgetMoney(summary.total_spend, summary.currency)}</p>
          {budget.amount === null ? (
            <HatchedMeter />
          ) : (
            <Meter value={summary.total_spend} max={budget.amount} tone="success" />
          )}
        </>
      )}
    </div>
  );
}

/** 商城訂單卡：讀月摘要自己的 `orders`（calendar month，跟 `spend` 同一顆 `monthState`）；
 * 「本月至今（N 天）」用 `days_elapsed`，上月淨額跟 ▲/▼ 變化都是回應本來就有的欄位，這裡
 * 不再自己拿現在跟上一期比（Feature Decisions「like-for-like」已經在後端做完）。 */
function OrdersCard({ orders, daysElapsed }: { orders: MonthOrders; daysElapsed: number }) {
  const delta = formatChangePct(orders.change_pct);
  return (
    <div className="surface p-5">
      <div className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
        <span>商城訂單淨額・品牌整體</span>
        <span>上月 {formatAmount(orders.previous_net)}</span>
      </div>
      <p className="numeric mt-1 flex items-baseline gap-2 text-2xl font-semibold">
        {formatAmount(orders.this_net)}
        {delta && <span className="text-sm font-semibold">{delta}</span>}
      </p>
      <Meter value={orders.this_net} max={orders.previous_net} tone="success" />
      <p className="mt-1 text-[11.5px] text-muted-foreground">本月至今（{daysElapsed} 天）</p>
    </div>
  );
}

/** 一個活動一列（Feature Decisions「各活動 rows」）：這一列是版面，不是共用元件——`TodoRow`
 * 的編號插槽塞不進活動 chip（原型的 `.todo` 只是「有上邊界＋間距」的通用列樣式，這裡跟
 * `記入品牌學習` 的 `LearningRow` 一樣自己組 flex row，兩邊都沒有編號圈／勾選圈）。verdict
 * 直接讀月摘要回應（後端已經判過達標／未達標／未判斷），這裡只負責畫，不再自己重算。 */
function CampaignRow({ brandId, row }: { brandId: string; row: MonthCampaignRow }) {
  const detailHref = `/brands/${brandId}/ads/campaigns/${row.campaign_id}/detail`;
  const costLabel = `每次${row.result_label}成本`;
  const canBar = row.target !== null && row.target > 0 && row.cost_per_result !== null;
  const verdict = VERDICT[row.verdict];

  return (
    <div className="flex flex-wrap items-center gap-4 border-t border-border py-3.5 first:border-t-0">
      <Link
        to={detailHref}
        title={row.name}
        className="flex w-full max-w-[220px] min-w-0 shrink-0 items-center hover:text-primary hover:underline sm:w-52"
      >
        <CampaignChip objective={chipObjective(row.campaign_objective)} name={row.name} strong />
      </Link>
      <div className="min-w-28 shrink-0 text-right">
        <p className="text-[11.5px] text-muted-foreground">花費</p>
        <p className="numeric text-sm font-semibold">{formatAmount(row.spend)}</p>
      </div>
      <div className="min-w-[200px] flex-1">
        {canBar ? (
          <Meter
            value={row.cost_per_result}
            max={(row.target as number) * 2}
            marker={row.target}
            tone={row.verdict === "met" ? "success" : "warning"}
            left={`${costLabel} ${formatAmount(row.cost_per_result)}`}
            right={`目標 ${formatAmount(row.target)}`}
          />
        ) : (
          <HatchedMeter
            left={`${costLabel} ${formatAmount(row.cost_per_result)}`}
            right={row.target === null ? "尚未設定目標" : `目標 ${formatAmount(row.target)}`}
          />
        )}
      </div>
      <Chip tone={verdict.tone} className="w-16 shrink-0 justify-center">{verdict.label}</Chip>
    </div>
  );
}

// 一組最多畫幾張縮圖（coordinator 一步修正 2026-09-22）：原型只示範個位數，真實品牌一個
// class 常有 20＋則廣告，全印成磚牆不是設計。超過的量不丟掉，摺成一顆中性 Chip；group
// 標頭的計數 chip 仍印全部則數，不受這個上限影響。
const MATERIAL_TILE_LIMIT = 12;

interface MaterialTile { entity_id: string; thumbnail_url: string | null }

/** 一個素材分組卡：標頭計數用 `count`（不受 12 張縮圖上限影響），`note` 是這一組的白話說明
 * （v8 原型 `month()` 每張卡標題下都有一行）。 */
function MaterialGroupCard({ title, tone, note, count, tiles }: {
  title: string; tone: "ok" | "bad" | "neutral"; note: string; count: number; tiles: MaterialTile[];
}) {
  const shown = tiles.slice(0, MATERIAL_TILE_LIMIT);
  const hidden = count - shown.length;
  return (
    <div className="surface p-5">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[15px] font-semibold">{title}</h3>
        <Chip tone={tone}>{count} 則</Chip>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{note}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {count === 0 ? (
          <p className="text-xs text-muted-foreground">目前沒有廣告落在這一類。</p>
        ) : (
          <>
            {shown.map((item) => <MaterialThumb key={item.entity_id} url={item.thumbnail_url} />)}
            {hidden > 0 && <Chip tone="neutral">＋{hidden} 則</Chip>}
          </>
        )}
      </div>
    </div>
  );
}

/** 素材（F26-I03，依 Feature Decisions「I03」重分三組）：有效／還看不出兩組仍讀「投放中」的
 * `items`（F26-I01 起 `classify()` 只判讀活躍廣告，class 篩選照舊有效）；無效・已停改讀每個
 * 活動自己的 `closed` 區塊——已暫停或已封存的廣告，不論這個月才關掉還是更早都在裡面；不再讀
 * 仍在投放的 `stop_loss`，那一類交給佇列的 stop_loss 列處理，這裡不重複判斷。`worse`／
 * `no_target` 同 F24，不在這裡列——那兩類在活動卡與佇列已經有自己的處理入口。這個月確切
 * 關掉幾則（`closed_this_month`）是月摘要自己的欄位，畫在「記入品牌學習」區塊上方
 * （`ClosedThisMonthNote`），不在這裡重複——三張卡自己的 note 仍然只講「含這個月關掉的」，
 * 不重複月摘要那一行的確切數字。 */
function MaterialGroups({ items, closedItems, closedTotal }: {
  items: TriageItem[]; closedItems: TriageClosedItem[]; closedTotal: number;
}) {
  const better = items.filter((item) => item.class === "better");
  const flatInsufficient = items.filter((item) => item.class === "flat" || item.class === "insufficient");
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      <MaterialGroupCard title="有效" tone="ok" note="投放中，成本在目標內" count={better.length} tiles={better} />
      <MaterialGroupCard
        title="無效・已停" tone="bad" note="已暫停或封存，含這個月關掉的"
        count={closedTotal} tiles={closedItems}
      />
      <MaterialGroupCard
        title="還看不出" tone="neutral" note="投放中，樣本還不夠"
        count={flatInsufficient.length} tiles={flatInsufficient}
      />
    </div>
  );
}

interface CampaignRowTriage { campaign: CampaignCardData; items: TriageItem[]; closed: TriageClosedBlock }

type MaterialState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; rows: CampaignRowTriage[] };

type LearningsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; learnings: AdsLearning[] };

/** 這個月關掉幾則：`closed_this_month !== null` 印 `LearnCard`；`null`（這個月落在
 * `closed_tracking_since` 之前，還沒開始記錄）印一行灰字說明從什麼時候起才有紀錄
 * （Feature Decisions「這個月關掉 N 則」／else 分支）。 */
function ClosedThisMonthNote({ closedThisMonth, trackingSince }: { closedThisMonth: number | null; trackingSince: string }) {
  if (closedThisMonth !== null) {
    return (
      <div className="mb-3">
        <LearnCard title={`這個月關掉 ${closedThisMonth} 則`} />
      </div>
    );
  }
  return <p className="mb-3 text-xs text-muted-foreground">關閉時間從 {formatYMD(trackingSince)} 起記錄</p>;
}

/** 一則品牌學習：📒 圖示＋文字＋（活動已知才印）活動 chip＋「N 次同方向」＋信心 chip。跟
 * `CampaignRow` 一樣自己組 flex row，不套 `TodoRow`（原型的 `.todo` 只是列樣式，兩邊都沒有
 * 編號圈）。「N 次同方向」統一用這個文字模板（Feature Decisions 的字面字），不跟原型範例
 * 資料的手寫文案（`"1 次"`、無「同方向」）走。F27-I27：活動 chip 的家族直接讀
 * `learning.campaign_objective`（`GET .../learnings` 自己就帶，見 `ads_learnings.py`），不再
 * 另打 `listCampaigns` 查表猜關鍵字；`campaign_objective` 是 `null` 只代表這則學習的活動本身
 * 已經查不到（已刪除／未知），退回純文字，不硬造一個家族。 */
function LearningRow({ learning }: { learning: AdsLearning }) {
  const conf = CONFIDENCE[learning.confidence];
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-border py-3.5 first:border-t-0">
      <span className="text-lg" aria-hidden="true">📒</span>
      <p className="min-w-0 flex-1 text-sm font-medium">{learning.text}</p>
      {learning.campaign_id && learning.campaign_name && (
        learning.campaign_objective ? (
          <span className="w-44 shrink-0">
            <CampaignChip objective={chipObjective(learning.campaign_objective)} name={learning.campaign_name} />
          </span>
        ) : (
          <span className="w-44 shrink-0 truncate text-xs text-muted-foreground" title={learning.campaign_name}>
            {learning.campaign_name}
          </span>
        )
      )}
      <span className="w-24 shrink-0 text-right text-xs text-muted-foreground">{learning.count} 次同方向</span>
      <Chip tone={conf.tone} className="w-20 shrink-0 justify-center">{conf.label}</Chip>
    </div>
  );
}

/** ✦ 下月建議一張卡：`採用` 導去 `action_url`（沒有就停用按鈕，型別容許 `null`）；`略過` 呼叫
 * `dismissSuggestion` 成功後從清單移掉這張卡（Feature Decisions「dismissSuggestion then remove
 * the card」）。`採用` 是 `Button variant="outline"`（原型 `class="btn sm"`，沒有 `.pri`，跟
 * 一般主要動作的 `.btn.pri` 不同——`ui-evidence.cjs` 的 pieces 對照已經印出這個對應）。 */
function SuggestionCard({ brandId, month, suggestion, onDismissed }: {
  brandId: string; month: string; suggestion: MonthSuggestion; onDismissed: (key: string) => void;
}) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function adopt() {
    if (suggestion.action_url) navigate(suggestion.action_url);
  }
  function skip() {
    setBusy(true);
    setError("");
    dismissSuggestion(brandId, month, suggestion.key)
      .then(() => onDismissed(suggestion.key))
      .catch((err: unknown) => {
        setBusy(false);
        setError(err instanceof Error ? err.message : "略過失敗，請稍後再試。");
      });
  }

  return (
    <div className="surface p-5">
      <CampaignChip objective={chipObjective(suggestion.campaign_objective)} name={suggestion.campaign_name} suffix={suggestion.objective} />
      <p className="mt-2.5 mb-1 text-[15px] font-semibold">{SUGGESTION_ICON[suggestion.kind]} {suggestion.title}</p>
      <p className="mb-3.5 text-[13px] text-muted-foreground">{suggestion.why}</p>
      {error && <p role="alert" className="mb-2 text-xs text-warning">{error}</p>}
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={busy || !suggestion.action_url} onClick={adopt}>採用</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={skip}>略過</Button>
      </div>
    </div>
  );
}

/** 下月建議整節：本地留一份可變清單（初始＝`monthState` 給的 `suggestions`），略過後從這份
 * 清單移掉，月份切換（`monthState` 整顆重打）會連著重新初始化。 */
function SuggestionsSection({ brandId, month, suggestions }: { brandId: string; month: string; suggestions: MonthSuggestion[] }) {
  const [visible, setVisible] = useState(suggestions);
  useEffect(() => setVisible(suggestions), [suggestions]);

  if (visible.length === 0) {
    return <p className="text-sm text-muted-foreground">這個月沒有下月建議。</p>;
  }
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {visible.map((suggestion) => (
        <SuggestionCard
          key={suggestion.key} brandId={brandId} month={month} suggestion={suggestion}
          onDismissed={(key) => setVisible((prev) => prev.filter((s) => s.key !== key))}
        />
      ))}
    </div>
  );
}

export function MonthReviewPage({ brandId }: { brandId: string }) {
  const homeHref = `/brands/${brandId}/ads`;
  const thisMonth = useMemo(() => currentBudgetMonth(), []);
  const lastMonth = useMemo(() => shiftMonth(thisMonth, -1), [thisMonth]);
  const [monthChoice, setMonthChoice] = useState<MonthChoice>("this");
  const selectedMonth = monthChoice === "this" ? thisMonth : lastMonth;

  // 月摘要＋月預算：驅動全品牌花費卡／訂單卡／各活動／這個月關掉／下月建議，月選單切換
  // 兩個一起重打（Feature Decisions「the month Segmented ... refetches the summary AND the
  // budget」）。
  const [monthState, setMonthState] = useState<MonthState>({ status: "loading" });
  const [monthReload, setMonthReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setMonthState({ status: "loading" });
    Promise.all([getMonthSummary(brandId, selectedMonth), getMonthlyBudget(brandId, selectedMonth)])
      .then(([summary, budget]) => {
        if (!cancelled) setMonthState({ status: "ready", summary, budget });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setMonthState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
    return () => {
      cancelled = true;
    };
  }, [brandId, selectedMonth, monthReload]);

  // 素材分組（F26 規則，跟月份無關——永遠讀「現在」投放中／已關的廣告）：一次讀全品牌的
  // Campaign，再逐一打 triage（F27-I27 起不再順便留查表——「記入品牌學習」的活動 chip 家族
  // 直接讀 `learning.campaign_objective`，見 `LearningRow`）。
  const [materialState, setMaterialState] = useState<MaterialState>({ status: "loading" });
  const [materialReload, setMaterialReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setMaterialState({ status: "loading" });
    listCampaigns(brandId)
      .then((campaigns) => {
        const open = campaigns.filter((c) => c.status !== "closed");
        return Promise.all(
          open.map((campaign) =>
            getTriage(brandId, campaign.id).then((triage) => ({ campaign, items: triage.items, closed: triage.closed })),
          ),
        );
      })
      .then((rows) => {
        if (!cancelled) setMaterialState({ status: "ready", rows });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setMaterialState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
    return () => {
      cancelled = true;
    };
  }, [brandId, materialReload]);

  // 品牌學習清單（Contract D，跟月份無關——這個品牌至今累積的紀錄，最多 50 筆）。
  const [learningsState, setLearningsState] = useState<LearningsState>({ status: "loading" });
  const [learningsReload, setLearningsReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLearningsState({ status: "loading" });
    getAdsLearnings(brandId)
      .then((learnings) => {
        if (!cancelled) setLearningsState({ status: "ready", learnings });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLearningsState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
    return () => {
      cancelled = true;
    };
  }, [brandId, learningsReload]);

  const titleMonthNum = Number(selectedMonth.split("-")[1]);
  const lastMonthNum = Number(lastMonth.split("-")[1]);
  const thisMonthNum = Number(thisMonth.split("-")[1]);
  const nextMonthNum = Number(shiftMonth(selectedMonth, 1).split("-")[1]);

  const allItems = materialState.status === "ready" ? materialState.rows.flatMap((r) => r.items) : [];
  const allClosedItems = materialState.status === "ready" ? materialState.rows.flatMap((r) => r.closed.items) : [];
  const closedTotal = materialState.status === "ready" ? materialState.rows.reduce((sum, r) => sum + r.closed.total, 0) : 0;

  return (
    <div className="flex max-w-[1180px] flex-col gap-5">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "每月回顧" }]} />

      <PageHeader
        title={`${titleMonthNum} 月回顧`}
        description="活動照常投放，這裡只整理帳"
        actions={
          <Segmented
            label="選擇月份"
            value={monthChoice}
            onChange={setMonthChoice}
            options={[
              { value: "last", label: `${lastMonthNum} 月` },
              { value: "this", label: `${thisMonthNum} 月` },
            ]}
          />
        }
      />

      {monthState.status === "loading" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="surface p-5"><Skeleton className="h-24 w-full" /></div>
          <div className="surface p-5"><Skeleton className="h-24 w-full" /></div>
        </div>
      )}
      {monthState.status === "error" && (
        <EmptyState
          title="讀取失敗"
          description={monthState.message}
          onAction={() => setMonthReload((v) => v + 1)}
          actionLabel="重新讀取"
        />
      )}
      {monthState.status === "ready" && (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <SpendCard summary={monthState.summary} budget={monthState.budget} />
            {monthState.summary.orders && (
              <OrdersCard orders={monthState.summary.orders} daysElapsed={monthState.summary.days_elapsed} />
            )}
          </div>

          <div>
            <h2 className="mb-3 text-[15px] font-semibold">各活動</h2>
            {monthState.summary.campaigns.length === 0 ? (
              <EmptyState title="沒有可回顧的活動" description="這個月沒有從廣告平台匯入的活動可回顧。" />
            ) : (
              <div className="surface px-5">
                {monthState.summary.campaigns.map((row) => (
                  <CampaignRow key={row.campaign_id} brandId={brandId} row={row} />
                ))}
              </div>
            )}
          </div>
        </>
      )}

      <div>
        <h2 className="mb-3 text-[15px] font-semibold">素材</h2>
        {materialState.status === "loading" && (
          <div className="surface p-5">
            <Skeleton className="h-24 w-full" />
          </div>
        )}
        {materialState.status === "error" && (
          <EmptyState
            title="讀取失敗"
            description={materialState.message}
            onAction={() => setMaterialReload((v) => v + 1)}
            actionLabel="重新讀取"
          />
        )}
        {materialState.status === "ready" && (
          <MaterialGroups items={allItems} closedItems={allClosedItems} closedTotal={closedTotal} />
        )}
      </div>

      {monthState.status === "ready" && (
        <div>
          <h2 className="mb-3 text-[15px] font-semibold">記入品牌學習</h2>
          <ClosedThisMonthNote
            closedThisMonth={monthState.summary.closed_this_month}
            trackingSince={monthState.summary.closed_tracking_since}
          />
          {learningsState.status === "loading" && (
            <div className="surface p-5"><Skeleton className="h-16 w-full" /></div>
          )}
          {learningsState.status === "error" && (
            <EmptyState
              title="讀取失敗"
              description={learningsState.message}
              onAction={() => setLearningsReload((v) => v + 1)}
              actionLabel="重新讀取"
            />
          )}
          {learningsState.status === "ready" && (
            learningsState.learnings.length === 0 ? (
              <p className="text-sm text-muted-foreground">還沒有記錄。</p>
            ) : (
              <div className="surface px-5">
                {learningsState.learnings.map((learning) => (
                  <LearningRow key={learning.id} learning={learning} />
                ))}
              </div>
            )
          )}
        </div>
      )}

      {monthState.status === "ready" && (
        <div>
          <h2 className="mb-3 text-[15px] font-semibold">✦ {nextMonthNum} 月建議</h2>
          <SuggestionsSection brandId={brandId} month={selectedMonth} suggestions={monthState.summary.suggestions} />
        </div>
      )}

      <ActionBar back={<Button variant="ghost" asChild><Link to={homeHref}>← 投放中心</Link></Button>} />
    </div>
  );
}
