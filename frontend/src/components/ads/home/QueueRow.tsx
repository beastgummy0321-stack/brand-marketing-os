import { Image as ImageIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { formatCount, formatCurrency } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { QueueItem } from "@/lib/adsTriageApi";

const KIND = {
  stop_loss: { mark: "■", tone: "danger" as const },
  worse: { mark: "▼", tone: "warning" as const },
};

/** `▲12%`／`▼12%`／`持平`；`change_pct` 是比值（`app/ads/triage.py::_compare`），null 就不印
 * 這一段（沒有前期資料可比）。 */
function formatDeltaPct(pct: number | null): string {
  if (pct === null) return "";
  const rounded = Math.round(Math.abs(pct) * 100);
  if (rounded === 0) return "持平";
  return `${pct > 0 ? "▲" : "▼"}${rounded}%`;
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
        className={cn("absolute inset-y-0 left-0 rounded-full", tone === "danger" ? "bg-danger" : "bg-warning")}
        style={{ width: `${fillPct}%` }}
      />
      <div className="absolute -top-1 -bottom-1 w-0.5 bg-foreground" style={{ left: `${markerPct}%` }} />
    </div>
  );
}

// v7 原型本來就把量尺收在窄版隱藏（prototype `@media(max-width:1100px){.q .viz{display:none}}`）——
// 這裡的卡片比原型窄（左邊還有 232px 側欄跟右邊的月預算卡分走版面），量尺＋兩行文案在桌面下限
// 1024 塞不下按鈕跟名稱，`xl`（1280px）以上才顯示，1024–1279 只留分類、名稱、按鈕，不做橫向
// 捲軸（design-system §9）。
const VIZ_CLASS = "hidden w-56 shrink-0 xl:block";

/** 一列的量尺＋兩行說明文字，分類只有 stop_loss／worse 兩種（`adsTriageApi.ts` 契約：佇列已被
 * 後端過濾過）。任何一半數字未知就不畫量尺，兩行文字仍照印、缺的那格寫「累積中」——不是 0
 * （design-system §7 誠實空狀態；金額／筆數沿用既有 `format.ts`，不是自己拼字串）。 */
function Viz({ item }: { item: QueueItem }) {
  const t = item.triage;
  const resultLabel = t.current.result_label;

  if (t.class === "stop_loss") {
    const spend = t.current.spend;
    const line = t.target.value === null ? null : t.target.value * 3;
    const countText = t.current.result_count === null
      ? "累積中"
      : `${formatCount(t.current.result_count)} 筆${resultLabel}`;
    return (
      <div className={VIZ_CLASS}>
        {spend !== null && line !== null && line > 0 && <Meter value={spend} marker={line} tone="danger" />}
        <div className="flex justify-between gap-2 text-[11.5px] text-muted-foreground">
          <span>花了 {formatCurrency(spend)}・{countText}</span>
          <span>停損線 {line === null ? "累積中" : formatCurrency(line)}</span>
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
      <div className="flex justify-between gap-2 text-[11.5px] text-muted-foreground">
        <span>每次{resultLabel}成本 {formatCurrency(cost)}{delta && ` ${delta}`}</span>
        <span>目標 {target === null ? "累積中" : formatCurrency(target)}</span>
      </div>
    </div>
  );
}

/** 佇列一列（F19-I03，v7 `home()` 的 `row`，prototype ≈ 195–203）：圖示格・分類 chip・廣告
 * 名稱・量尺・一個按鈕。原型另外印活動 chip，這裡拿掉——`QueueItem`／`TriageItem` 只帶
 * `campaign_id`，沒有活動名稱可印（見 `DecisionQueue.tsx` 檔頭註解），不印 id 充數。
 * 只有第一列是主要按鈕樣式（`primary`），其餘都是次要——呼叫端負責傳對 index。 */
export function QueueRow({ item, primary }: { item: QueueItem; primary: boolean }) {
  const t = item.triage;
  const kind = t.class === "stop_loss" || t.class === "worse" ? KIND[t.class] : null;

  return (
    <div className="flex items-center gap-4 p-4">
      <div className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-muted" aria-hidden="true">
        <ImageIcon className="size-5 text-muted-foreground" />
      </div>
      <div className="min-w-0 flex-1">
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
        <p className="mt-1.5 truncate text-sm font-semibold">{t.name ?? "（未命名廣告）"}</p>
      </div>
      <Viz item={item} />
      {/* 直排而不是並排：1024 這個桌面下限，按鈕加上停損的灰階佔位 chip 並排會把名稱擠到
       * 換行甚至橫向溢出（design-system §9 不准有橫向捲軸），直排在窄卡片也站得住。 */}
      <div className="flex shrink-0 flex-col items-end gap-1.5">
        {item.action_url && (
          <Button asChild size="sm" variant={primary ? "default" : "outline"}>
            <Link to={item.action_url}>看證據</Link>
          </Button>
        )}
        {t.class === "stop_loss" && (
          <span className="inline-flex max-w-32 items-center rounded-full border border-dashed border-border bg-muted px-2.5 py-1 text-center text-xs text-muted-foreground">
            暫停提議・接上後開放
          </span>
        )}
      </div>
    </div>
  );
}
