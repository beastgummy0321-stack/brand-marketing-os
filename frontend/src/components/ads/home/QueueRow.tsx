import { useEffect, useState } from "react";
import { Image as ImageIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { QueueItem, QueueKind, QueueScale } from "@/lib/adsTriageApi";
import { KindMark } from "../patterns";
import { proposalAction } from "./status";

// F25-I02: `scale_budget`／`refresh_creative` join `stop_loss`／`worse` as the queue's four row
// kinds (feature Decisions "Home rows", prototype `home()`'s `row()`) — every row now carries a
// `KindMark` variant, keyed off `item.kind_key` (the row's own identity) rather than
// `item.triage.class` (the *ad's* classification, which for a `scale_budget`/`refresh_creative`
// row is its best/first ad's own class — `better`/`flat`/etc, never one of these four).
const KIND_VARIANT: Record<QueueKind, "stop" | "worse" | "up" | "fresh"> = {
  stop_loss: "stop", worse: "worse", scale_budget: "up", refresh_creative: "fresh",
};
// `scale_budget`／`refresh_creative` 列的分類文字是這一列本身的身份（可加預算／補素材），不是
// best ad 自己的 `triage.label`（對這兩種列印的是「變好」「持平」之類）——跟 v7 `home()` 的
// `row()` 一樣直接掛中文，不從後端另要一個欄位（`DecisionQueue.tsx` 的 `PENDING_LABEL` 用同一組
// 字，只是那邊是接上前的佔位列）。
function kindLabel(item: QueueItem): string {
  switch (item.kind_key) {
    case "scale_budget": return "可加預算";
    case "refresh_creative": return "補素材";
    default: return item.triage.label;
  }
}
// scale_budget 列的標題是預算擁有者名稱（adset 或活動自己，`QueueScaleOwner.name` 可能是
// `null`）；refresh_creative 列的標題是句子本身，不是廣告名稱（`refresh.readable_count`）。兩者
// 都防禦 `item.scale`／`item.refresh` 缺席（型別上是選用欄位，實際上永遠隨 `kind_key` 一起出現
// ——`adsTriageApi.ts` 的欄位註解），退回廣告名稱那條路不會讓列空白。
function rowTitle(item: QueueItem): string {
  if (item.kind_key === "scale_budget" && item.scale) return item.scale.owner.name ?? "（未命名）";
  if (item.kind_key === "refresh_creative" && item.refresh) {
    return `能判讀的素材只剩 ${item.refresh.readable_count} 則`;
  }
  return item.triage.name ?? "（未命名廣告）";
}

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
// F25-I02: `success` 是可加預算列自己的 tone（見下面的 `ScaleViz`）——排進這一列的廣告本來就都
// 已經在目標內（Rule A：連續兩期成本 ≤ 目標），量尺色只是把這件事畫出來，不是又算了一次。
function Meter({ value, marker, tone }: { value: number; marker: number; tone: "danger" | "warning" | "success" }) {
  const max = marker * 1.5;
  const fillPct = Math.min(100, Math.max(0, (value / max) * 100));
  const markerPct = Math.min(100, (marker / max) * 100);
  const fillClass = tone === "danger" ? "bg-danger" : tone === "warning" ? "bg-warning" : "bg-success";
  return (
    // `data-slot="meter"`／`data-variant`：跟 `patterns/FlowPieces.tsx` 的共用 `Meter` 同一組
    // 慣例——`ui-evidence.cjs` 靠這兩個屬性認出「這是量尺」，本地重刻的這支不掛就等於對證據
    // 工具隱形（F25-I02 review fix：可加預算列的 tone=success 用不了共用 `Meter`——那支的
    // 「未知就不畫」比這支的「頂到 1.5 倍 marker」規則不同，硬套會動到停損／變差既有列，
    // 但仍要接上同一組事實標記）。
    <div
      className="relative my-1.5 h-2.5 rounded-full bg-muted"
      aria-hidden="true"
      data-testid="meter"
      data-slot="meter"
      data-variant={tone}
    >
      <div data-testid="meter-fill" className={cn("absolute inset-y-0 left-0 rounded-full", fillClass)} style={{ width: `${fillPct}%` }} />
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

/** 停損／變差列的量尺＋兩行說明文字（F25-I02：`scale_budget`／`refresh_creative` 列另外走
 * `ScaleViz`／`RefreshTiles`，這支只管 `t.class` 是 `stop_loss`／`worse` 的兩種）。任何一半數字
 * 未知就不畫量尺，兩行文字仍照印、缺的那格寫誠實的未知句（design-system §7；花費/筆數是量測值
 * 缺「累積中」，目標/停損線是配置值缺「尚未設定」）。花費／成本／目標不印 `NT$`——`queue`／
 * `triage` 沒有回幣別，硬掛 NT$ 對非台幣廣告帳戶是錯的標籤，跟 v7 一樣印純數字。 */
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

/** 可加預算列的量尺（F25-I02，feature Decisions "Home rows"）：`scale.cost_per_result` 對
 * `scale.target.value`，tone 固定 `success`——排進這一列的廣告本來就都已經在目標內（Rule A：連續
 * 兩期成本 ≤ 目標），量尺色只是畫出這件事，不是又比較了一次。文案「<成果標籤>成本 X」／
 * 「目標 Y」跟停損／變差列同一組小工具（`formatAmount`／`formatTargetAmount`），但沒有「每次」
 * 前綴、沒有變化百分比——照 feature Decisions 原文抄，不是漏寫。 */
function ScaleViz({ scale }: { scale: QueueScale }) {
  const cost = scale.cost_per_result;
  const target = scale.target.value;
  const resultLabel = scale.target.result_label;
  return (
    <div className={VIZ_CLASS}>
      {cost !== null && target !== null && target > 0 && <Meter value={cost} marker={target} tone="success" />}
      <div className={CAPTION_CLASS}>
        <span>{resultLabel}成本 {formatAmount(cost)}</span>
        <span>目標 {formatTargetAmount(target)}</span>
      </div>
    </div>
  );
}

/** 補素材列的縮圖格（34px）：跟 `detail/CampaignDetailPage.tsx` 的 `AdThumb` 同一條規則——`null`
 * 或載入失敗都落到中性佔位圖示，不是空白、不是破圖示（`thumbnail_url` 可能是一條會過期的
 * Meta CDN 連結）。 */
function RefreshTile({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  const showImage = url !== null && !failed;
  return (
    <div
      className="flex size-[34px] shrink-0 items-center justify-center overflow-hidden rounded-md bg-muted"
      aria-hidden="true"
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- 這裡不是 Next.js 專案。
        <img src={url} alt="" className="size-full object-cover" onError={() => setFailed(true)} />
      ) : (
        <ImageIcon className="size-3.5 text-muted-foreground" />
      )}
    </div>
  );
}

/** `refresh.thumbnails` 最多 4 則，不足的份自己補中空虛線格到 4（feature Decisions "Home rows"：
 * "tiles from `refresh.thumbnails` padded with hollow dashed tiles to 4"）——後端從不補，這裡
 * 補，不是後端漏做。 */
function RefreshTiles({ thumbnails }: { thumbnails: (string | null)[] }) {
  const shown = thumbnails.slice(0, 4);
  const hollow = 4 - shown.length;
  return (
    <div className={cn(VIZ_CLASS, "flex items-center gap-1.5")}>
      {shown.map((url, i) => <RefreshTile key={i} url={url} />)}
      {Array.from({ length: hollow }).map((_, i) => (
        <div
          key={`hollow-${i}`}
          data-testid="refresh-tile-hollow"
          className="size-[34px] shrink-0 rounded-md border border-dashed border-border"
          aria-hidden="true"
        />
      ))}
    </div>
  );
}

/** 佇列一列（F19-I03，v7 `home()` 的 `row`，prototype ≈ 195–203；F25-I02 加上 `scale_budget`／
 * `refresh_creative` 兩種）：圖示格・分類 chip（`KindMark`）・活動 chip・標題・量尺（或補素材列的
 * 縮圖格）・一個按鈕。v7 的活動 chip 帶彩色字母圖示（`CAMP[c].cls`/`.ic`）——這裡沒有這份資料，
 * 只印中性 chip＋活動名稱（F19-I07，見 feature Decisions：不臆造圖示）。只有第一列是主要按鈕
 * 樣式（`primary`），其餘都是次要——呼叫端負責傳對 index。
 *
 * F22-I05：停損列不再印靜態的「暫停提議・接上後開放」佔位——`item.proposal` 已經接上真的
 * 三步流程，按鈕本身（`proposalAction`）就是誠實的目前進度，旁邊再放一顆「接上後開放」反而
 * 是舊話。F23-I05：變差列現在也接上同一支 `proposalAction`（`kind: "review"`，見
 * `home/status.ts`「Queue row state for `worse` rows」）——不再看 `item.action_url`。 */
export function QueueRow({ item, primary }: { item: QueueItem; primary: boolean }) {
  const t = item.triage;
  const title = rowTitle(item);

  // `item.brand_id` 這批（品牌底下的佇列查詢）一律有值；型別留 `null` 是沿用 `interrupt` 表
  // 的共用欄位定義——沒有值就組不出 `/brands/:brandId/...` 連結，誠實地退回今天的
  // `action_url` 這條路，不假造品牌 id。scale_budget 的入口用預算擁有者（adset 或活動自己）的
  // id，不是 best ad 的 `entity_id`（feature Decisions "Home rows"，"budget branch = the pause
  // branch on a budget set"）。refresh_creative 不經過 `proposalAction`——固定按鈕，按鈕區塊自己
  // 判斷 `item.kind_key`，不落進這裡。
  const action = (() => {
    if (item.brand_id === null) return null;
    if (t.class === "stop_loss") {
      const a = proposalAction(item.brand_id, t.campaign_id, t.entity_id, item.proposal, "pause");
      // F25-I02：home 列的停損「沒有提案」入口字樣從「去處理」改印「看提議」——detail 頁的
      // `AdRow` 走同一支 `proposalAction`，字樣照舊不動（feature Decisions "Home rows"：
      // "detail-page 「去處理」 unchanged"），所以只在這一列自己覆寫這一種狀態的 label，
      // 不改共用函式的預設值（改了會連 detail 頁一起變）。
      return item.proposal === null ? { ...a, label: "看提議" } : a;
    }
    if (t.class === "worse") {
      return proposalAction(item.brand_id, t.campaign_id, t.entity_id, item.proposal, "review");
    }
    if (item.kind_key === "scale_budget" && item.scale) {
      return proposalAction(item.brand_id, t.campaign_id, item.scale.owner.id, item.proposal, "budget");
    }
    return null;
  })();

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4">
      <div className="order-1 flex size-12 shrink-0 items-center justify-center rounded-lg bg-muted" aria-hidden="true">
        <ImageIcon className="size-5 text-muted-foreground" />
      </div>
      <div className="order-2 min-w-0 flex-1">
        {/* Lead review fix 2026-09-21：分類 chip／活動 chip 同一行不換行——活動 chip 是
         * `min-w-0 shrink` 把 Badge 預設的 `w-fit shrink-0` 蓋掉，長名稱在自己框裡截斷成
         * 「…」，不會擠到換行或被外層裁掉右邊框。 */}
        <div className="flex flex-nowrap items-center gap-1.5">
          <span className="shrink-0">
            <KindMark kind={KIND_VARIANT[item.kind_key]}>{kindLabel(item)}</KindMark>
          </span>
          {t.campaign_name && (
            // Badge 本身是 `inline-flex justify-center`——直接把 `truncate` 放在 Badge 上，
            // 溢出的文字會被置中裁切（左右各切一段、看不到「…」），要另包一層佔滿寬度的
            // `<span>` 自己 truncate 才會在右邊出現省略號（lead review fix 2026-09-21）。
            <Badge variant="outline" className="min-w-0 max-w-[14rem] shrink" title={t.campaign_name}>
              <span className="min-w-0 w-full truncate">{t.campaign_name}</span>
            </Badge>
          )}
        </div>
        <p className="mt-1.5 truncate text-sm font-semibold" title={title}>{title}</p>
      </div>
      {/* 暫停提議 chip 在按鈕左邊、同一條垂直中線，單行不換行——兩個都是固定寬度的內容，
       * 這個群組本身不會比第 1 行其他項目撐更高（review fix：原本各自站一行，把第一列撐高）。
       * Lead review fix 2026-09-21：xl 給固定寬度、內容靠右——停損列多一顆暫停提議 chip，
       * 沒有它的變差列不能因此把量尺往右推，兩種列的量尺欄在 xl 要對齊同一個 x 座標。 */}
      <div className="order-3 flex shrink-0 items-center gap-2 xl:order-4 xl:w-56 xl:justify-end">
        {item.kind_key === "refresh_creative" ? (
          // 補素材列的按鈕固定「準備新素材」，不看回合狀態——沒有提案，也永遠不會完成
          // （feature Decisions "Home rows"："refresh rows never count as done"）。`action_url`
          // 已經是活動工作區的素材分頁（`app/ads/triage.py::_queue_candidates`），不必自己組。
          item.action_url && (
            <Button asChild size="sm" variant={primary ? "default" : "outline"}>
              <Link to={item.action_url}>準備新素材</Link>
            </Button>
          )
        ) : action ? (
          <Button asChild size="sm" variant={action.done ? "ghost" : primary ? "default" : "outline"}>
            <Link to={action.href}>{action.label}</Link>
          </Button>
        ) : (
          item.action_url && (
            <Button asChild size="sm" variant={primary ? "default" : "outline"}>
              <Link to={item.action_url}>看證據</Link>
            </Button>
          )
        )}
      </div>
      {item.kind_key === "refresh_creative"
        ? <RefreshTiles thumbnails={item.refresh?.thumbnails ?? []} />
        : item.kind_key === "scale_budget" && item.scale
        ? <ScaleViz scale={item.scale} />
        : <Viz item={item} />}
    </div>
  );
}
