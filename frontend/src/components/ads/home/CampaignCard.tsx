import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/format";
import type { CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { getTriage, type TriageClass, type TriageItem } from "@/lib/adsTriageApi";
import { STATUS_LABEL, STATUS_TONE } from "./status";

type Basis = "own" | "break_even" | "trailing_30";
const BASIS_LABEL: Record<Basis, string> = { own: "自訂", break_even: "損益兩平", trailing_30: "近 30 天" };

/** 目標視圖：直接沿用 `TriageItem.target`（`TriageTargetView`）的形狀——campaign 沒有廣告時
 * (`items.length===0`) 這張卡完全不顯示目標（review 裁決 #2），所以不再需要另外打
 * `getTarget()` 湊一份備用視圖，一支 `getTriage` 打完就夠。 */
type TargetView = TriageItem["target"];

type CardState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: TriageItem[] };

const SEGMENTS: { cls: Exclude<TriageClass, "no_target">; label: string; swatch: string }[] = [
  { cls: "stop_loss", label: "停損", swatch: "bg-danger" },
  { cls: "worse", label: "變差", swatch: "bg-warning" },
  { cls: "better", label: "變好", swatch: "bg-success" },
  { cls: "flat", label: "持平", swatch: "bg-muted-foreground/40" },
  { cls: "insufficient", label: "資料不足", swatch: "bg-border" },
];

function chip(tone?: "warn") {
  return cn(
    "inline-flex w-fit shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs",
    tone === "warn" ? "bg-warning/10 text-warning" : "bg-muted text-muted-foreground",
  );
}

/** 目標／成本數字：後端不回幣別，`formatCurrency` 又是寫死 NT$——套在可能來自非台幣帳戶的
 * 數字上是錯的標籤（design-system §7、review 裁決）。v7 原型也只印數字本身（「450」），這裡
 * 照樣不印符號，只留千分位＋等寬數字。`trailing_30` 依據是 spend/result_count 現算出來的，
 * 常是小數（例如 5200/15＝346.67）——不用 `Math.round`，最多留兩位小數，3.1 還是印 3.1，不
 * 印成 3。金額類的總預算不受影響，那是系統自己算的 TWD 整數，繼續用 `formatCurrency`。 */
function formatPlainNumber(value: number): string {
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

/** 五分類長條：分母是「真的判斷出五類之一」的則數，不含 `no_target`（review 裁決——
 * `no_target` 算在分母會讓長條永遠填不滿，也不代表「已判斷但持平」）。呼叫端算完 `no_target`
 * 另外印一顆「N 則無法判斷」的 chip，不混進這條色段。圖例只列非零分類。 */
function Strip({ counts, total }: { counts: Record<Exclude<TriageClass, "no_target">, number>; total: number }) {
  const nonZero = SEGMENTS.filter((s) => counts[s.cls] > 0);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex h-3.5 w-full overflow-hidden rounded-full bg-muted">
        {SEGMENTS.map((s) => (
          <div
            key={s.cls}
            data-segment={s.cls}
            className={s.swatch}
            style={{ width: `${(counts[s.cls] / total) * 100}%` }}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {nonZero.map((s) => (
          <span key={s.cls} className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className={cn("inline-block size-2 rounded-sm", s.swatch)} />
            {s.label} {counts[s.cls]}
          </span>
        ))}
      </div>
    </div>
  );
}

/** 尚未設定目標／讀取失敗共用：整條打斜紋（誠實的未知態，不是量測出來的 0）。 */
function HatchedStrip() {
  return (
    <div
      aria-hidden="true"
      className="h-3.5 w-full rounded-full bg-muted"
      style={{
        backgroundImage:
          "repeating-linear-gradient(45deg, var(--color-border), var(--color-border) 4px, transparent 4px, transparent 8px)",
      }}
    />
  );
}

function TargetBody({
  items, targetHref, workspaceHref,
}: { items: TriageItem[]; targetHref: string; workspaceHref: string }) {
  // 沒有可判讀的廣告（草稿／待發布／剛同步）：不會判斷，催著設目標也沒用——設了也沒有廣告可以
  // 套。唯一的動作是進去活動本身看狀況（review 裁決 #2）。
  if (items.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        <span className={chip()}>沒有廣告資料</span>
        <Link to={workspaceHref} className="w-fit text-sm text-muted-foreground hover:text-primary hover:underline">
          進入活動 ›
        </Link>
      </div>
    );
  }

  const target: TargetView = items[0].target;
  const label = `目標每次${target.result_label}成本`;
  const known: Record<Exclude<TriageClass, "no_target">, number> = {
    stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0,
  };
  let noTargetCount = 0;
  for (const item of items) {
    if (item.class === "no_target") noTargetCount++;
    else known[item.class]++;
  }
  const knownTotal = items.length - noTargetCount;

  if (target.value === null) {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-[20px] font-semibold text-muted-foreground">尚未設定</p>
        <HatchedStrip />
        {/* 頁面已有自己的主要動作（建立投放計畫），這顆是次要按鈕，不搶主按鈕的視覺份量
           （review 裁決）。 */}
        <Button asChild variant="outline" size="sm" className="self-start">
          <Link to={targetHref}>設定目標，才開始判斷</Link>
        </Button>
        {target.missing.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {target.missing.map((m) => (
              <span key={m} className={chip()}>{m}</span>
            ))}
          </div>
        )}
      </div>
    );
  }

  const basisLabel = target.basis ? BASIS_LABEL[target.basis] : null;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="numeric text-[20px] font-semibold">{formatPlainNumber(target.value)}</span>
        {basisLabel && <span className={chip()}>{basisLabel}</span>}
        <Link to={targetHref} className="text-sm text-primary hover:underline">調整</Link>
      </div>
      {knownTotal > 0 && <Strip counts={known} total={knownTotal} />}
      {noTargetCount > 0 && <span className={chip()}>{noTargetCount} 則無法判斷</span>}
    </div>
  );
}

/** 活動卡（F19-I04，v7 原型 `ccard`；review 裁決修正版）：一張卡一個 Campaign，自己打
 * `getTriage` 拿這個 Campaign 的判斷分佈。狀態（草稿／待發布／已結束）與匯入標記不是 triage
 * 的事，直接從 `campaign` 讀，跟讀取狀態無關，隨時看得到。 */
export function CampaignCard({ brandId, campaign }: { brandId: string; campaign: CampaignCardData }) {
  const [state, setState] = useState<CardState>({ status: "loading" });
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    // ponytail: one triage call per card; add a brand-level summary endpoint when a brand has >10 campaigns
    getTriage(brandId, campaign.id)
      .then((triage) => { if (!cancelled) setState({ status: "ready", items: triage.items }); })
      .catch(() => { if (!cancelled) setState({ status: "error" }); });
    return () => { cancelled = true; };
  }, [brandId, campaign.id, reload]);

  const workspaceHref = `/brands/${brandId}/ads/campaigns/${campaign.id}`;
  // F20-I02：卡片名稱現在落在新的活動詳情頁（v7 `campPage()`），不是五分頁工作區——
  // 工作區網址不變，由詳情頁的「全部資料 ›」進去。「沒有廣告資料」時的「進入活動」連結
  // 仍照舊指向工作區（那個空狀態本身就是工作區才有意義的路，跟詳情頁重複沒有新資訊）。
  const detailHref = `${workspaceHref}/detail`;
  const targetHref = `${workspaceHref}/target`;
  const isError = state.status === "error";

  const statusLabel = campaign.origin === "imported" ? "平台活動" : STATUS_LABEL[campaign.status];
  const statusTone = STATUS_TONE[campaign.status];

  // 預算：站內 Campaign 讀自己算好的總預算（`budget_progress.total`）；匯入的平台活動這支卡
  // 目前沒有平台原生預算可讀（那在 `NativeEntity.budget_amount`，另一支 API），照舊卡的作法只
  // 標「平台預算」，不是留白也不是編數字（review 裁決）。金額一律帶著「總預算」這個標籤，不
  // 印一個沒人知道是什麼的裸數字。
  const budgetTotal = campaign.budget_progress.total;
  const budgetChip = campaign.origin === "imported"
    ? <span className={chip()}>平台預算</span>
    : budgetTotal !== null
      ? <span className={chip()}>總預算 {formatCurrency(budgetTotal)}</span>
      : <span className={chip("warn")}>預算待核實</span>;

  return (
    <article
      className={cn(
        // `.surface`（tokens.css，unlayered）比 Tailwind utilities 層的 `bg-muted` 優先權高，
        // `cn()` 疊上去蓋不掉——讀取失敗態乾脆不套 `.surface`，直接用同樣的邊框／圓角／背景
        // 工具類組出來（review 裁決）。
        isError ? "min-w-0 rounded-xl border border-border bg-muted" : "surface",
        "flex flex-col gap-3 p-5",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="min-w-0 flex-1 text-[15px] font-semibold">
          {/* h3／連結本身是 flex row：長名稱只讓名稱那格 truncate，「›」永遠是 shrink-0、
             不被擠掉（review 裁決）；整個 <Link> 還是同一個點擊區域。 */}
          <Link to={detailHref} className="flex min-w-0 items-center gap-0.5 hover:text-primary hover:underline">
            <span className="min-w-0 truncate" title={campaign.name}>{campaign.name}</span>
            {/* aria-hidden：只是「這裡可以點」的視覺提示，不進可及名稱——名稱連結要留純活動
               名稱給 e2e／accessible name 用（review 裁決）。 */}
            <span aria-hidden="true" className="shrink-0 text-muted-foreground">›</span>
          </Link>
        </h3>
        <div className="flex shrink-0 items-center gap-1.5">
          <Badge variant={statusTone}>{statusLabel}</Badge>
          {/* Imported campaigns carry a whole sentence as objective: only the objective text
             truncates, the ad count never does, and the campaign name keeps its room. */}
          <span className={cn(chip(), "inline-flex max-w-[14rem] items-center")}>
            <span className="min-w-0 truncate" title={campaign.objective || undefined}>
              {campaign.objective || "尚待確認"}
            </span>
            {state.status === "ready" && <span className="shrink-0">・{state.items.length} 則</span>}
          </span>
        </div>
      </div>

      {state.status === "loading" && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-3.5 w-20" />
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-3.5 w-full rounded-full" />
        </div>
      )}

      {state.status === "error" && (
        <div className="flex flex-col gap-2">
          <p className="text-[15px] font-semibold text-muted-foreground">暫時讀取不到</p>
          <HatchedStrip />
          <div className="flex flex-wrap items-center gap-2">
            {/* 讀取失敗只是這次沒拿到新的判斷結果，已經存的紀錄沒有被動過——這句話對這個
               失敗態一定為真才印（review 裁決）。 */}
            <span className={chip()}>已保存的紀錄都還在</span>
            {/* aria-label 帶活動名稱：頁面上每張卡都會印「重新讀取」，用 aria-label 讓螢幕
               閱讀器分得出這顆按鈕重試的是哪一張卡（其餘元件的重試各自有自己的可及名稱）。 */}
            <Button
              variant="outline"
              size="sm"
              aria-label={`重新讀取「${campaign.name}」`}
              onClick={() => setReload((v) => v + 1)}
            >
              重新讀取
            </Button>
          </div>
        </div>
      )}

      {state.status === "ready" && (
        <TargetBody items={state.items} targetHref={targetHref} workspaceHref={workspaceHref} />
      )}

      {/* 預算來自 Campaign 清單本身，不是這張卡的 triage 讀取——讀取失敗也照樣看得到
         （review 裁決）。 */}
      <div className="flex flex-wrap items-center gap-2">{budgetChip}</div>
    </article>
  );
}
