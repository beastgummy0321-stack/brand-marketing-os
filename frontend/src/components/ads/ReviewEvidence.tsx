import { useState } from "react";
import { AlertTriangle, ReceiptText, Target } from "lucide-react";
import { Link } from "react-router-dom";
import type { CommerceEvidence, ReviewRound, ReviewSeries } from "@/lib/adsReviewApi";
import { Disclosure } from "./patterns";

const reviewNumber = (value: number | null | undefined) => value == null ? "尚待確認" : value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
function seriesKey(value: ReviewSeries) { return [value.metric_scope, value.attribution_key, value.currency, value.source].join("|"); }
function Commerce({ current, previous, brandId }: { current: CommerceEvidence; previous: CommerceEvidence; brandId: string }) {
  const now = current.order_summary, before = previous.order_summary;
  return <section className="surface" aria-label="商城與通路證據">
    <div className="surface-header"><div className="flex items-center gap-2"><ReceiptText className="size-5 text-primary" /><h3 className="font-semibold">商城與通路</h3></div><p className="mt-1 text-xs text-muted-foreground">品牌整體 · 不能分配成單則廣告的營收</p></div>
    <div className="surface-body space-y-3">
      <div className="grid grid-cols-2 gap-3"><div><p className="text-xs text-muted-foreground">本期匯入訂單</p><p className="mt-1 text-xl font-semibold">{reviewNumber(now.count)} 筆</p></div><div><p className="text-xs text-muted-foreground">付款狀態未確認</p><p className="mt-1 text-xl font-semibold">{reviewNumber(now.unknown_payment_count)} 筆</p></div></div>
      <table className="w-full text-sm"><caption className="sr-only">商城當期與前期對照</caption><thead><tr><th className="text-left">報表數值</th><th className="text-right">前期</th><th className="text-right">本期</th></tr></thead><tbody>
        <tr><td className="py-2">訂單淨額</td><td className="text-right">{reviewNumber(before.order_net_amount)}</td><td className="text-right">{reviewNumber(now.order_net_amount)}</td></tr>
        <tr><td className="py-2">明確付款訂單淨額</td><td className="text-right">{reviewNumber(before.paid_net_amount)}</td><td className="text-right">{reviewNumber(now.paid_net_amount)}</td></tr>
      </tbody></table>
      <p className="text-xs text-muted-foreground">幣別：{now.currency ?? "原始來源未確認"}。報表淨額已扣已知退款；不等同經會計核實的入帳金額。</p>
      <p className="rounded-md bg-warning/10 p-3 text-sm">報表是否涵蓋完整期間仍待確認。資料缺漏、未付款與退款，都可能影響判讀。</p>
      <Link className="inline-block text-sm font-medium text-primary" to={`/brands/${brandId}/orders`}>補齊或檢視商城報表 →</Link>
      <Disclosure label="查看通路來源與資料限制">
        <div className="space-y-3 text-sm">{current.channels.map((channel, i) => <div key={i} className="flex flex-wrap justify-between gap-2 border-b border-border pb-2"><div><p>{channel.channel} · {channel.source ?? "既有來源"}</p><p className="text-xs text-muted-foreground">{channel.source_type === "order_mirror" ? "由訂單同步，不與訂單再次相加" : channel.source_type === "manual" ? "人工回報" : "匯入來源"} · {channel.row_count} 筆</p></div><p>{reviewNumber(channel.amount)} {channel.currency ?? "幣別未確認"}</p></div>)}{current.limitations.map((text, i) => <p className="text-muted-foreground" key={i}>{text}</p>)}</div>
      </Disclosure>
    </div>
  </section>;
}

export function ReviewEvidence({ review, brandId }: { review: ReviewRound; brandId: string }) {
  const evidence = review.evidence_json;
  const [key, setKey] = useState("");
  const current = evidence.current.series.find(row => seriesKey(row) === key) ?? evidence.current.series[0];
  const previous = current ? evidence.previous.series.find(row => seriesKey(row) === seriesKey(current)) : undefined;
  const rows = [["spend", "平台花費"], ["purchases", "平台回報購買"], ["cpa", "平台購買成本"], ["roas", "平台回報 ROAS"]] as const;
  return <div className="space-y-4">
    {evidence.source_review && <section className="surface" aria-label="新測試的上一輪來源"><div className="surface-header"><h3 className="font-semibold">這次新測試，承接上一輪的哪個問題</h3><p className="mt-1 text-sm text-muted-foreground">{evidence.source_review.recommendation.hypothesis}</p></div><div className="surface-body space-y-2 text-sm"><p>{evidence.source_review.recommendation.next_step}</p><p className="text-xs text-muted-foreground">來源判讀期間：{evidence.source_review.window.start} — {evidence.source_review.window.end}。原廣告與本次廣告各自保存成效，不混成同一則廣告的歷史。</p><Link className="inline-block font-medium text-primary" to={`?tab=performance&review=${encodeURIComponent(evidence.source_review.review_id)}`}>查看來源檢討與決定 →</Link><Disclosure label="查看新測試交接證據"><p>物件身分：{evidence.source_review.readback.entity_exists ? "已觀測" : "尚待確認"} · 設定：{evidence.source_review.readback.setting_matches === true ? "讀回相符" : "仍待核對"}。不代表已開始投遞。</p>{evidence.source_review.limitations.map((text, i) => <p className="mt-1 text-muted-foreground" key={i}>{text}</p>)}</Disclosure></div></section>}
    <div className="grid items-start gap-4 xl:grid-cols-[1.2fr_1fr]">
      <section className="surface" aria-label="單則廣告成效">
        <div className="surface-header"><div className="flex items-center gap-2"><Target className="size-5 text-primary" /><h3 className="font-semibold">單則廣告成效</h3></div><p className="mt-1 text-xs text-muted-foreground">{evidence.window.start} — {evidence.window.end} · {evidence.window.timezone ?? "帳戶時區待確認"}</p></div>
        <div className="surface-body space-y-4">
          <div className="rounded-lg border border-border p-4"><h4 className="font-semibold">{evidence.target.name ?? "平台廣告"}</h4><p className="mt-1 text-xs text-muted-foreground">{evidence.target.platform} · {evidence.target.source_account} · {evidence.target.native_id}</p><p className="mt-3 line-clamp-3 whitespace-pre-wrap text-sm">{evidence.conditions.creative_snapshot.copy_fields?.body ?? "文案尚未取得"}</p><p className="mt-2 text-xs text-muted-foreground">以上為最近讀取的素材摘要，不代表整個觀察期間使用同一版本。</p></div>
          {evidence.current.series.length > 1 && <label className="block text-sm">資料口徑<select className="mt-1 w-full" value={current ? seriesKey(current) : ""} onChange={event => setKey(event.target.value)}>{evidence.current.series.map(series => <option key={seriesKey(series)} value={seriesKey(series)}>{series.currency ?? "幣別未知"} · {series.attribution_key} · {series.source}</option>)}</select></label>}
          <table className="w-full text-sm"><caption className="sr-only">同一則廣告在相同資料口徑下的前後期數值</caption><thead><tr><th className="text-left">平台指標</th><th className="text-right">前期</th><th className="text-right">本期</th></tr></thead><tbody>{rows.map(([metric, label]) => <tr key={metric}><td className="py-2">{label}</td><td className="text-right">{reviewNumber(previous?.metrics[metric])}</td><td className="text-right font-medium">{reviewNumber(current?.metrics[metric])}</td></tr>)}</tbody></table>
          <p className="text-xs text-muted-foreground">{current?.currency ?? "幣別待確認"} · 本期有資料 {evidence.current.days_present} / {evidence.current.days_expected} 天 · 前期 {evidence.window.previous_start} — {evidence.window.previous_end}</p>
          <div className="flex gap-2 rounded-md bg-warning/10 p-3 text-sm"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" /><p>平台回報不等於真實營收；不能據此認定圖片或文案造成改善。{evidence.conditions.history === "mixed" ? "期間內有素材或設定變動。" : "整段期間的素材與設定歷史尚未證實。"}</p></div>
        </div>
      </section>
      <Commerce current={evidence.commerce.current} previous={evidence.commerce.previous} brandId={brandId} />
    </div>
    <Disclosure label="查看完整判讀依據、缺漏與上一輪結果">
      <div className="grid gap-4 xl:grid-cols-2 text-sm"><div className="space-y-2"><h3 className="font-semibold">資料來源與限制</h3>{evidence.sources.map(source => <p key={source.id}>{source.text}</p>)}{evidence.limitations.map((value, index) => <p className="text-muted-foreground" key={index}>{value}</p>)}</div><div className="space-y-2"><h3 className="font-semibold">上一輪承接</h3>{evidence.previous_review ? <><p>{evidence.previous_review.reason ?? "已帶入上一輪判讀與執行結果。"}</p>{evidence.previous_review.result_json.recommendations?.map(item => <p key={item.id}>{item.hypothesis}</p>)}<p>已帶入 {evidence.previous_review.actions.length} 項操作核對紀錄；完成檢討不代表所有操作完成。</p></> : <p className="text-muted-foreground">這是首次檢討，尚無上一輪結論。</p>}</div></div>
    </Disclosure>
  </div>;
}
