import { Image as ImageIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { QueueItem } from "@/lib/adsTriageApi";

const KIND = {
  stop_loss: { mark: "■", tone: "danger" as const },
  worse: { mark: "▼", tone: "warning" as const },
};

/** `▲12%`／`▼12%`／`持平`；`change_pct` 是比值（`app/ads/triage.py::_compare`），null 就不印
 * 這一段（沒有前期資料可比）。這個百分比只看 `change_pct` 這個欄位，不是從花費／目標反推——
 * 兩者本來就可能不同（`change_pct` 比的是這期跟上一期自己，目標是另一條基準線）。 */
function formatDeltaPct(pct: number | null): string {
  if (pct === null) return "";
  const rounded = Math.round(Math.abs(pct) * 100);
  if (rounded === 0) return "持平";
  return `${pct > 0 ? "▲" : "▼"}${rounded}%`;
}

// `queue`／`triage` 沒有回幣別（見下方 Viz 的說明），花費／成本／目標都印純數字。`format.ts` 的
// `formatCount` 對非整數會印出 `toLocaleString` 的預設精度（最多到 3 位小數，例：5200/15 的
// 每筆成本印成「346.667」）——lib 不在這張票的 touch 範圍，這裡自己包一個最多 2 位小數、不四捨
// 五入到整數的版本（3.1 要留著 3.1，不是 3）。
function formatAmount(value: number | null): string {
  if (value === null) return "累積中";
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}
// 目標／停損線都是「使用者本來要不要設定」的配置值，不是還在累積的量測值——未設定寫「尚未
// 設定」，不是「累積中」（design-system §7：不同的未知理由要有不同的誠實句子）。
function formatTargetAmount(value: number | null): string {
  if (value === null) return "尚未設定";
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

/** 停損線／目標量尺（v7 `.meter`/`.meter u`，prototype ≈ 190）：後端沒有給「量尺該多寬」，
 * 這裡自己訂 marker（停損線或目標）落在軸的 2/3 處，最寬看到 1.5 倍 marker，超過就頂滿
 * （`ponytail`：固定倍率，不是每列自己找「合理上限」——量尺只求「看得出超了多少」，不是精算圖表）。 */
function Meter({ value, marker, tone }: { value: number; marker: number; tone: "danger" | "warning" }) {
  const max = marker * 1.5;
  const fillPct = Math.min(100, Math.max(0, (value / max) * 100));
  const markerPct = Math.min(100, (marker / max) * 100);
  return (
    <div className="relative my-1.5 h-2.5 rounded-full bg-muted" aria-hidden="true" data-testid="meter">
      <div
        data-testid="meter-fill"
        className={cn("absolute inset-y-0 left-0 rounded-full", tone === "danger" ? "bg-danger" : "bg-warning")}
        style={{ width: `${fillPct}%` }}
      />
      <div data-testid="meter-marker" className="absolute -top-1 -bottom-1 w-0.5 bg-foreground" style={{ left: `${markerPct}%` }} />
    </div>
  );
}

// 量尺是這一列的證據，桌面下限 1024 也要看得到（review repair：不准整塊藏起來）——`xl`
// （1280px）以上跟名稱同一行、固定寬度；1024–1279 擠不下按鈕＋名稱＋量尺一整行，量尺退到
// 名稱下面自己一行，用 `order` 讓視覺順序跟著螢幕寬度換，不是複製兩份量尺。寬度在 xl 給
// 300–340px（v7 `.viz` 原本 220px，這裡的卡片留給每個數字的空間比原型窄，字會斷行），窄版
// 頂多 360px、靠左對齊名稱（`pl-16` = 圖示 48px＋間距 16px），不做橫向捲軸（design-system §9）。
const VIZ_CLASS =
  "order-4 basis-full max-w-[360px] pl-16 xl:order-3 xl:basis-auto xl:max-w-none xl:w-[340px] xl:shrink-0 xl:pl-0";
// 兩行文案各自不換行、靠左右對齊（v7 `.cap`），數字用等寬數字（design-system §2.2 `.numeric`）。
const CAPTION_CLASS = "numeric flex justify-between gap-2 text-[11.5px] whitespace-nowrap text-muted-foreground";

/** 一列的量尺＋兩行說明文字，分類只有 stop_loss／worse 兩種（`adsTriageApi.ts` 契約：佇列已被
 * 後端過濾過）。任何一半數字未知就不畫量尺，兩行文字仍照印、缺的那格寫誠實的未知句
 * （design-system §7；花費/筆數是量測值缺「累積中」，目標/停損線是配置值缺「尚未設定」）。
 * 花費／成本／目標不印 `NT$`——`queue`／`triage` 沒有回幣別，硬掛 NT$ 對非台幣廣告帳戶是錯的
 * 標籤，跟 v7 一樣印純數字。 */
function Viz({ item }: { item: QueueItem }) {
  const t = item.triage;
  const resultLabel = t.current.result_label;

  if (t.class === "stop_loss") {
    const spend = t.current.spend;
    // 3× 目標＝停損線，跟後端 `app/ads/triage.py::STOP_LOSS_SPEND_MULTIPLE` 同一個數字——後端
    // 判斷用它分類，這裡只是把同一條線畫出來給使用者看，`queue` 沒有把算好的線回傳。
    const line = t.target.value === null ? null : t.target.value * 3;
    const countText = t.current.result_count === null
      ? "累積中"
      : `${formatCount(t.current.result_count)} 筆${resultLabel}`;
    return (
      <div className={VIZ_CLASS}>
        {spend !== null && line !== null && line > 0 && <Meter value={spend} marker={line} tone="danger" />}
        <div className={CAPTION_CLASS}>
          <span>花了 {formatAmount(spend)}・{countText}</span>
          <span>停損線 {formatTargetAmount(line)}</span>
        </div>
      </div>
    );
  }

  const cost = t.current.cost_per_result;
  const target = t.target.value;
  const delta = formatDeltaPct(t.change_pct);
  return (
    <div className={VIZ_CLASS}>
      {cost !== null && target !== null && target > 0 && <Meter value={cost} marker={target} tone="warning" />}
      <div className={CAPTION_CLASS}>
        <span>每次{resultLabel}成本 {formatAmount(cost)}{delta && ` ${delta}`}</span>
        <span>目標 {formatTargetAmount(target)}</span>
      </div>
    </div>
  );
}

/** 佇列一列（F19-I03，v7 `home()` 的 `row`，prototype ≈ 195–203）：圖示格・分類 chip・廣告
 * 名稱・量尺・一個按鈕。原型另外印活動 chip，這裡拿掉——`QueueItem`／`TriageItem` 只帶
 * `campaign_id`，沒有活動名稱可印（見 `DecisionQueue.tsx` 檔頭註解），不印 id 充數。
 * 只有第一列是主要按鈕樣式（`primary`），其餘都是次要——呼叫端負責傳對 index。「看證據」只
 * 看 `action_url` 有沒有，跟量尺畫不畫得出來無關——量尺不知道，不代表證據頁面不存在。 */
export function QueueRow({ item, primary }: { item: QueueItem; primary: boolean }) {
  const t = item.triage;
  const kind = t.class === "stop_loss" || t.class === "worse" ? KIND[t.class] : null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4">
      <div className="order-1 flex size-12 shrink-0 items-center justify-center rounded-lg bg-muted" aria-hidden="true">
        <ImageIcon className="size-5 text-muted-foreground" />
      </div>
      <div className="order-2 min-w-0 flex-1">
        {kind && (
          <span
            className={cn(
              "inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold",
              kind.tone === "danger" ? "bg-danger/10 text-danger" : "bg-warning/10 text-warning",
            )}
          >
            <span aria-hidden="true">{kind.mark}</span>
            <span>{t.label}</span>
          </span>
        )}
        <p className="mt-1.5 truncate text-sm font-semibold" title={t.name ?? "（未命名廣告）"}>{t.name ?? "（未命名廣告）"}</p>
      </div>
      {/* 暫停提議 chip 在按鈕左邊、同一條垂直中線，單行不換行——兩個都是固定寬度的內容，
       * 這個群組本身不會比第 1 行其他項目撐更高（review fix：原本各自站一行，把第一列撐高）。 */}
      <div className="order-3 flex shrink-0 items-center gap-2 xl:order-4">
        {t.class === "stop_loss" && (
          <span className="inline-flex items-center rounded-full border border-dashed border-border bg-muted px-2.5 py-1 text-xs whitespace-nowrap text-muted-foreground">
            暫停提議・接上後開放
          </span>
        )}
        {item.action_url && (
          <Button asChild size="sm" variant={primary ? "default" : "outline"}>
            <Link to={item.action_url}>看證據</Link>
          </Button>
        )}
      </div>
      <Viz item={item} />
    </div>
  );
}
