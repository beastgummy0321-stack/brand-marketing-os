import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Info, Wallet } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { getOrgId } from "@/lib/auth";
import { getMonthlyBudget, saveMonthlyBudget, type MonthlyBudget } from "@/lib/adsChangeApi";
import { DEFAULT_ORG_TIMEZONE, orgToday } from "@/lib/orgClock";
import { Disclosure } from "./patterns/Disclosure";

/** F36-I09 (ruling G): the budget month is the org's today (YYYY-MM), not the browser's. Pass
 * `useOrgClock().timezone`; callers without a workspace fall back to the org default. */
export const currentBudgetMonth = (timezone: string = DEFAULT_ORG_TIMEZONE) => orgToday(timezone).slice(0, 7);
/** F46-I09: the one link every 「設定／提高 N 月月預算」 exit uses — the ads home opens the monthly-budget form on it. */
export const BUDGET_EDIT_PARAM = "budget";
export const monthlyBudgetHref = (brandId: string) => `/brands/${encodeURIComponent(brandId)}/ads?${BUDGET_EDIT_PARAM}=edit`;
export function budgetMoney(value: number | null, currency: string | null) {
  return value === null ? "尚待確認" : `${currency ?? "幣別待確認"} ${value.toLocaleString("zh-TW", { maximumFractionDigits: 2 })}`;
}

/** `startEditing` (F46-I09) opens the edit form once the budget is read, prefilled with the saved amount (empty when
 * unset — no invented default). */
function BudgetPanel({ brandId, month, refresh = 0, compact = false, startEditing = false }: { brandId: string; month: string; refresh?: number; compact?: boolean; startEditing?: boolean }) {
  const [budget, setBudget] = useState<MonthlyBudget | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("");
  const [saved, setSaved] = useState(false);
  const lifetime = useRef(new AbortController());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    getMonthlyBudget(brandId, month, controller.signal).then(value => {
      if (!controller.signal.aborted) setBudget(value);
    }).catch(() => { if (!controller.signal.aborted) setError("月預算暫時讀取不到。請重新讀取，已保存的總額不會消失。"); });
    return () => controller.abort();
  }, [brandId, month, refresh, reload]);

  const autoEdited = useRef(false);
  useEffect(() => {
    if (!startEditing || !budget || autoEdited.current) return;
    autoEdited.current = true;
    edit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startEditing, budget]);

  function edit() {
    setAmount(budget?.amount?.toString() ?? ""); setCurrency(budget?.currency ?? "");
    setEditing(true); setSaved(false); setError("");
  }
  async function save() {
    if (!budget || busy || !amount.trim() || !Number.isFinite(Number(amount)) || Number(amount) < 0 || !/^[A-Z]{3}$/.test(currency)) return;
    setBusy(true); setError("");
    const signal = lifetime.current.signal;
    try {
      const value = await saveMonthlyBudget(brandId, { month, currency, amount: Number(amount), expected_revision: budget.revision }, signal);
      if (!signal.aborted) { setBudget(value); setEditing(false); setSaved(true); }
    } catch (err) {
      if (!signal.aborted) setError(err instanceof Error ? err.message : "總額尚未確認保存，請重新讀取後再試。");
    } finally { if (!signal.aborted) setBusy(false); }
  }
  const validAmount = amount.trim() && Number.isFinite(Number(amount)) && Number(amount) >= 0;
  const blockedReason = budget?.amount === null ? "請先設定月總額，再確認需要花費的變更。" : budget?.available !== null && budget?.available !== undefined ? "本月額度已用完或不足，暫不核准新增花費。" : "可用額度尚未確認，暫不核准新增花費。";
  return <section className="surface" aria-label="每月品牌廣告預算">
    <div className="surface-header flex-wrap gap-3">
      <div className="flex items-center gap-2"><Wallet className="size-5 text-primary" /><div><h2>本月廣告預算</h2><p className="text-xs text-muted-foreground">{month} · 節慶額度包含在總額內</p></div></div>
      {budget && !editing && <Button size="sm" variant="outline" onClick={edit}>{budget.amount === null ? "設定月總額" : "調整月總額"}</Button>}
    </div>
    <div className={compact ? "surface-body space-y-2" : "surface-body space-y-4"}>
      {!budget && !error && <p role="status" className="text-sm text-muted-foreground">正在整理月預算…</p>}
      {budget && <>
        <dl className={`grid grid-cols-2 gap-4 ${compact ? "sm:grid-cols-4" : ""}`}>
          {[["月總額", budget.amount], ["已回收花費", budget.known_spend], ["持續投放預估", budget.ongoing_estimate], ["可新增承諾", budget.available]].map(([label, value]) => <div key={String(label)} className="min-w-0"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-words text-lg font-semibold numeric">{budgetMoney(value as number | null, budget.currency)}</dd></div>)}
        </dl>
        {!budget.can_increase && <div className="flex items-start gap-2 rounded-md bg-warning/10 p-3 text-sm"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" /><p>{blockedReason}仍可檢視、補齊資料與核准降低風險的變更。</p></div>}
        {!compact && budget.notice && <p className="text-xs text-muted-foreground">{budget.notice}</p>}
        <Disclosure label="查看預算依據與待補資料">
          <div className="space-y-3 text-sm">
            {compact && budget.notice && <p>{budget.notice}</p>}
            <p>估算涵蓋至 {budget.period_end}，包含下一次檢討後仍持續投放的期間。已核准但未核對完成的降額，不會先增加可用額度。</p>
            <p>已保留的新增承諾：{budgetMoney(budget.reserved_increases, budget.currency)}</p>
            {budget.uncertainties.length > 0 && <ul className="list-disc space-y-1 pl-5">{budget.uncertainties.map((reason, index) => <li key={index}>{reason}</li>)}</ul>}
            <Button asChild size="sm" variant="outline"><Link to={`/brands/${brandId}/ads/connections`}>查看資料連線</Link></Button>
            <div className="grid gap-3 xl:grid-cols-3">
              <p><strong className="block">系統提醒</strong><span className="text-muted-foreground">依最新可取得資料提醒額度與異常。</span></p>
              <p><strong className="block">核准前檢查</strong><span className="text-muted-foreground">每份清單檢查月額、相關設定與資料缺口。</span></p>
              <p><strong className="block">平台實際限額</strong><span className="text-muted-foreground">本機總額不代表平台限額已設定或已核對。</span></p>
            </div>
          </div>
        </Disclosure>
        {editing && <form className="rounded-lg border border-border bg-background p-4 space-y-3" onSubmit={event => { event.preventDefault(); void save(); }}>
          <p className="font-medium text-sm">只需確認本月總額，其他計算交給系統。</p>
          <div className="grid gap-3 grid-cols-[120px_minmax(0,1fr)]">
            <label className="text-sm">幣別<Input aria-label="月預算幣別" value={currency} maxLength={3} placeholder="例如 TWD" onChange={e => setCurrency(e.target.value.toUpperCase())} disabled={busy || budget.revision > 0} /></label>
            <label className="text-sm">每月品牌總額<Input aria-label="每月品牌總額" type="number" min="0" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} disabled={busy} /></label>
          </div>
          <div className="flex flex-wrap gap-2"><Button type="submit" disabled={busy || !validAmount || !/^[A-Z]{3}$/.test(currency)}>{busy ? "保存中…" : "確認月總額"}</Button><Button type="button" variant="outline" disabled={busy} onClick={() => setEditing(false)}>取消修改</Button></div>
        </form>}
      </>}
      {error && <div role="alert" className="space-y-2 text-sm text-destructive"><p>{error}</p><Button size="sm" variant="outline" onClick={() => setReload(value => value + 1)}>重新讀取月預算</Button></div>}
      {saved && <p role="status" className="text-sm text-success">月總額已保存；不會另外增加可花的錢。</p>}
      {!compact && <p className="flex items-start gap-2 text-xs text-muted-foreground"><Info className="size-4 shrink-0" />本機設定不會讓平台自動停止花費。</p>}
    </div>
  </section>;
}
export function MonthlyBudgetPanel(props: Parameters<typeof BudgetPanel>[0]) {
  return <BudgetPanel key={`${getOrgId()}:${props.brandId}:${props.month}`} {...props} />;
}
