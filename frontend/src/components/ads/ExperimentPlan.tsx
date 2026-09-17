import { useEffect, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { readComparison, confirmComparison, type ComparisonState } from "@/lib/adsExperimentApi";
export function ExperimentPlan({brandId, campaignId, refreshKey, onViewPlan}: {
  brandId: string; campaignId: string; refreshKey: unknown; onViewPlan: () => void;
}) {
  const [state,setState] = useState<ComparisonState | null>(null);
  const [error,setError] = useState<string | null>(null);
  const [checked,setChecked] = useState(false);
  const [busy,setBusy] = useState(false);
  const [reload,setReload] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setError(null); setChecked(false); setState(null);
    readComparison(brandId,campaignId).then(s => {if(!cancelled)setState(s);}).catch(e => {if(!cancelled)setError(e instanceof Error ? e.message : "讀取失敗。");});
    return () => {cancelled=true;};
  },[brandId,campaignId,refreshKey,reload]);
  async function confirm() {
    if(!state?.proposal || !checked)return;
    setBusy(true);setError(null);
    try { setState(await confirmComparison(brandId,campaignId,state.proposal.fingerprint));setChecked(false); }
    catch(e){setError(e instanceof Error ? e.message : "確認失敗。");}
    finally{setBusy(false);}
  }
  const p = state?.proposal;
  return <section className="surface p-4 flex flex-col gap-3" aria-label="單一變因比較計畫">
    <h3 className="font-medium">單一變因比較計畫</h3>
    <p className="text-sm text-muted-foreground">系統依現有廣告提出，你核對後確認。只記錄比較計畫，不會新增素材、改預算或對外投放。</p>
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    {!state && !error && <p role="status">讀取比較提案中…</p>}
    {state?.missing && <><p className="text-sm">{state.missing}</p><Button variant="outline" className="self-start" onClick={onViewPlan}>前往投放結構補對照</Button></>}
    {state?.stale && <p role="status" className="text-sm text-warning">原確認已過期：條件或素材有變更，請核對新提案並重新確認。</p>}
    {p && <>
      <p className="text-sm font-medium">假設：{p.hypothesis}</p>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">{p.variants.map((v,i) => <div key={v.ad_id} className="rounded-md border border-border p-3 text-sm"><span className="font-medium">{i === 0 ? "A 對照" : "B 比較"}：{v.name}</span><p>{p.variable}：{v.value}</p><p className="text-xs text-muted-foreground break-all">{v.ad_id}</p></div>)}</div>
      <p className="text-sm">共同條件：{p.shared.group}／{p.shared.audience}／{p.shared.channel}；目標：{p.shared.objective}；每日預算：{p.shared.daily_budget.toLocaleString()}。</p>
      <p className="text-sm">指標：{p.metric_label}；觀察期間：{p.window.start} ～ {p.window.end}。</p>
      <p className="text-sm">判讀條件：完成至少 7 天、兩則每日資料齊全、各至少 10 次轉換；差值除以兩值中較大者達 10%，才標「觀察到差異」。這是操作門檻，不是統計顯著性檢定。</p>
      <p className="text-sm">停止條件：{p.stop}</p>
      <p className="text-xs text-muted-foreground">{p.limitation} 系統只核對設定；實際素材與平台受眾仍需你核對。</p>
      {state?.simulation && <p className="text-sm font-medium">隔離模擬，非市場實證。</p>}
      {(!state?.confirmed || state.stale) && !state?.closed && <>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={checked} disabled={busy} onChange={e=>setChecked(e.target.checked)} />我已核對兩則素材與共同投放條件，除上述變因外，其餘保持一致，並接受觀察限制與判讀條件。</label>
        <Button className="self-start" disabled={!checked || busy} onClick={()=>void confirm()}>{busy ? "確認中…" : "確認這份比較計畫"}</Button>
      </>}
    </>}
    {state?.confirmed && <details><summary className="cursor-pointer text-sm">已保存的確認紀錄{state.stale ? "（已過期）" : ""}</summary><div className="mt-2 text-xs text-muted-foreground"><p>{state.confirmed.hypothesis}</p><p>{state.confirmed.confirmed_at} · {state.confirmed.confirmed_by}</p><p>{state.confirmed.timing === "retrospective" ? "已有成效後才確認：事後觀察，不是事前實驗。" : "尚無回收資料時確認；不代表已完成隨機分流。"}</p></div></details>}
    {state && <div className="rounded-md bg-muted p-3 text-sm"><p className="font-medium">判讀：{state.result.verdict}</p><p>{state.result.reason}</p>{state.result.values.map(v => <p key={v.ad_id}>{v.name}：{v.value.toLocaleString(undefined,{maximumFractionDigits:2})}（花費 {v.spend.toLocaleString()}／轉換 {v.purchases}）</p>)}</div>}
    <Button variant="ghost" className="self-start" disabled={busy} onClick={()=>setReload(n=>n+1)}>重新讀取比較提案</Button>
  </section>;
}
