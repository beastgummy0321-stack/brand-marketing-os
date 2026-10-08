import type { MonthOrders as Orders } from "@/lib/adsMonthApi";
import type { CommerceEvidence } from "@/lib/adsHomeApi";
import { Disclosure } from "../patterns";
import { money } from "./monthCsv";

const MISSING = {currency: "來源幣別未核實", coverage: "來源涵蓋範圍未核實", payment: "部分付款狀態未知", amount: "部分付款金額未知"};
function SourceDetails({ evidence, label }: { evidence: CommerceEvidence; label: string }) {
  const source = evidence.order_summary;
  return <div className="min-w-0 space-y-1 text-sm [overflow-wrap:anywhere]">
    <b>{label} {evidence.start}–{evidence.end}</b>
    <p>{source.unpaid_count} 筆待付款・{source.unknown_payment_count} 筆付款狀態未知</p>
    <p>{source.unknown_amount_count} 筆金額未知・{source.void_count} 筆取消或作廢</p>
    <p>{source.refunded_count} 筆已退款・{source.known_paid_net_count} 筆已付款金額已知</p>
    <p className="text-xs text-muted-foreground">報表標示幣別：{source.reported_currencies.join("、") || "未提供"}（不是來源幣別核實證明）</p>
    {evidence.limitations.map((text, index) => <p key={index} className="text-xs text-muted-foreground">{text}</p>)}
  </div>;
}
function paidAmount(value: number | null, evidence: CommerceEvidence) {
  if (evidence.order_summary.reported_currencies.length > 1) return "多幣別，無法合計";
  if (value === null) return "付款金額尚未確認";
  return money(value, evidence.order_summary.currency, evidence.order_summary.currency_basis !== "unknown");
}
/** Displays the facade subtotal; mirrors never contribute another amount. */
export function MonthOrders({ orders }: { orders: Orders | null }) {
  return <section aria-label="已收集的已付款訂單淨額" className="surface px-[22px] py-5">
    <h2 className="text-[15px] font-semibold">已收集的已付款訂單淨額</h2>
    {!orders ? <p className="mt-2 text-sm text-muted-foreground">目前無法確認訂單證據</p> : <>
      <div className="mt-3 grid min-w-0 gap-4 sm:grid-cols-2">
        <div className="min-w-0">
          <b className="numeric block text-2xl [overflow-wrap:anywhere]">{paidAmount(orders.this_net, orders.this_evidence)}</b>
          <p className="mt-1 text-sm">{orders.this_evidence.order_summary.paid_count} 筆已付款・{orders.this_count} 筆金額已知・{orders.this_evidence.order_summary.refunded_count} 筆已退款</p>
          <p className="text-xs text-muted-foreground">{orders.this_evidence.start}–{orders.this_evidence.end}・品牌訂單，未歸因單一廣告</p>
        </div>
        <div className="min-w-0">
          <span className="text-sm text-muted-foreground">前期同長度窗口</span>
          <b className="numeric block text-lg [overflow-wrap:anywhere]">{paidAmount(orders.previous_net, orders.previous_evidence)}</b>
          <p className="text-xs text-muted-foreground">{orders.previous_count} 筆金額已知・{orders.previous_evidence.start}–{orders.previous_evidence.end}</p>
        </div>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">僅計入已知金額的付款列，不代表全部收入或廣告獲利</p>
      <p className="mt-1 text-xs text-muted-foreground">{orders.comparison_missing.map((reason) => MISSING[reason]).join("・") || "依已收集付款列比較"}</p>
      <div className="mt-3"><Disclosure label="訂單來源與狀態">
        <div className="grid gap-4 sm:grid-cols-2"><SourceDetails label="本期" evidence={orders.this_evidence} /><SourceDetails label="前期" evidence={orders.previous_evidence} /></div>
      </Disclosure></div>
    </>}
  </section>;
}
