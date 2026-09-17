import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/layout/ui/dialog";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import { readSimulation, saveSimulation, startSimulation, type SimulationDay, type SimulationRow } from "@/lib/adsSimulationApi";

const FIELDS = [["spend", "花費"], ["impressions", "曝光"], ["clicks", "點擊"], ["purchases", "轉換數"], ["revenue", "營收"]] as const;
type Values = Record<(typeof FIELDS)[number][0], string>;
type Entry = Values & { received: boolean };
function entries(c: CampaignDetail, rows: SimulationRow[]): Record<string, Entry> {
  return Object.fromEntries(c.groups.flatMap(g => g.ads.map(a => {
    const row = rows.find(r => r.ad_id === a.id);
    return [a.id, { received: !!row, spend: row ? String(row.spend) : "", impressions: row ? String(row.impressions) : "", clicks: row ? String(row.clicks) : "", purchases: row ? String(row.purchases) : "", revenue: row ? String(row.revenue) : "" }];
  })));
}
export function SimulationRecovery({ brandId, campaign: c, onChanged, onSaved }: {
  brandId: string; campaign: CampaignDetail; onChanged: (c: CampaignDetail) => void; onSaved: () => void;
}) {
  const today = new Date().toLocaleDateString("sv-SE");
  const [day, setDay] = useState(c.start_date || today);
  const [data, setData] = useState<SimulationDay | null>(null);
  const [values, setValues] = useState<Record<string, Entry>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const campaignRef = useRef(c);
  campaignRef.current = c;
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setData(null); setError(null);
    readSimulation(brandId, c.id, day).then(next => {
      if (!cancelled) { setData(next); setValues(entries(campaignRef.current, next.rows)); setDirty(false); }
    }).catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : "讀取失敗。"); });
    return () => { cancelled = true; };
  }, [brandId, c.id, c.status, day, reload]);
  async function start() {
    setBusy(true); setError(null);
    try {
      await startSimulation(brandId, c.id);
      onChanged(await getCampaign(brandId, c.id)); setConfirmOpen(false); setReload(n => n + 1);
    } catch (e) { setError(e instanceof Error ? e.message : "啟用失敗。"); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!data) return;
    const rows: SimulationRow[] = [];
    for (const [ad_id, value] of Object.entries(values)) {
      if (!value.received) continue;
      if (FIELDS.some(([key]) => !value[key].trim() || !Number.isFinite(Number(value[key])) || Number(value[key]) < 0)) {
        setError("已回收的廣告每個欄位都要填；真零請填 0，尚無資料請取消「已回收」。"); return;
      }
      rows.push({ ad_id, spend: Number(value.spend), impressions: Number(value.impressions), clicks: Number(value.clicks), purchases: Number(value.purchases), revenue: Number(value.revenue) });
    }
    setBusy(true); setError(null);
    try { setData(await saveSimulation(brandId, c.id, day, data.revision, rows)); setDirty(false); onSaved(); }
    catch (e) { setError(e instanceof Error ? e.message : "儲存失敗，已保留輸入。"); }
    finally { setBusy(false); }
  }
  const readOnly = busy || !!data?.closed || !!data?.reason;
  return <details className="surface p-4">
    <summary className="cursor-pointer font-medium">隔離模擬成效回收</summary>
    <div className="mt-4 flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">僅供隔離測試品牌。每日增量會接到同一套成效、結案與同品牌學習；不會對外投放，也不是市場實證。</p>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {!data ? error ? <Button variant="outline" onClick={() => setReload(n => n + 1)}>重新讀取模擬入口</Button> : <p role="status">讀取模擬入口中…</p> : <>
        {data.reason && <p className="text-sm text-warning">{data.reason}</p>}
        {!data.started ? <Button className="self-start" disabled={readOnly} onClick={() => setConfirmOpen(true)}>啟用隔離模擬回收</Button> : <>
          <p className="text-sm font-medium">隔離模擬已啟用；此品牌不可再使用真實平台配對。</p>
          <label className="text-sm">資料日期（該日增量，不是截至當日累計）<Input aria-label="模擬資料日期" type="date" min={c.start_date || undefined} max={[today, c.end_date || today].sort()[0]} value={day} disabled={busy} onChange={e => {
            if (e.target.value && (!dirty || window.confirm("這一天的變更尚未儲存，確定切換日期？"))) setDay(e.target.value);
          }} /></label>
          <p className="text-xs text-muted-foreground">儲存會取代這一天整份快照，重送不累加；取消「已回收」代表缺資料，填 0 才是真零。每次修正都會更新版本。</p>
          {c.groups.map(g => <fieldset key={g.id} className="min-w-0 rounded-md border border-border p-3">
            <legend className="px-1 text-sm font-medium">{g.name}</legend>
            {g.ads.map(a => { const value = values[a.id]; if (!value) return null;
              return <div key={a.id} className="py-3 border-b border-border last:border-0">
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" aria-label={`已回收：${a.name}`} checked={value.received} disabled={readOnly} onChange={e => { setValues(v => ({...v, [a.id]: {...v[a.id], received: e.target.checked}})); setDirty(true); }} />{a.name} · {a.id}</label>
                <p className="mt-1 text-xs text-muted-foreground">對應本輪廣告及其已選素材；受眾：{a.audience_key || "尚未設定"}</p>
                {value.received && <div className="mt-2 grid grid-cols-2 gap-3 xl:grid-cols-5">{FIELDS.map(([key,label]) => <label key={key} className="text-xs">{label}<Input aria-label={`${a.name} ${label}`} type="number" min="0" step={key === "spend" || key === "revenue" ? "0.01" : "1"} value={value[key]} disabled={readOnly} onChange={e => {setValues(v => ({...v,[a.id]:{...v[a.id],[key]:e.target.value}}));setDirty(true);}} /></label>)}</div>}
              </div>;
            })}
          </fieldset>)}
          {data.closed ? <p className="text-sm">已結案，成效快照與來源紀錄已凍結。</p> : <Button className="self-start" disabled={readOnly} onClick={() => void save()}>{busy ? "儲存中…" : "儲存這一天的模擬成效"}</Button>}
          <p role="status" className="text-xs text-muted-foreground">{dirty ? "有尚未儲存的變更" : data.revision ? `此日期已保存，第 ${data.revision} 版 · ${data.saved_at}` : "此日期尚無回收快照"}</p>
          <details><summary className="cursor-pointer text-sm">回收來源紀錄</summary><ul className="mt-2 space-y-1 text-xs">{Object.entries(data.receipts).sort().map(([date,r]) => <li key={date}>{date} · 第 {r.revision} 版 · {r.ad_count} 則已回收／{r.missing_ad_count} 則缺資料 · {r.saved_at} · {r.saved_by}</li>)}</ul></details>
        </>}
      </>}
    </div>
    <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}><DialogContent>
      <DialogTitle>確認此品牌只用於隔離演練</DialogTitle>
      <DialogDescription>此品牌之後不能進行真實平台配對或回收。活動「{c.name}」將綁定模擬 ID；不產生隨機成效，數字由你逐日輸入。模擬學習只留在此品牌，不能當正式營運資料。</DialogDescription>
      {error && <p className="text-sm text-danger">{error}</p>}
      <DialogFooter><Button variant="outline" disabled={busy} onClick={() => setConfirmOpen(false)}>取消</Button><Button disabled={busy} onClick={() => void start()}>{busy ? "啟用中…" : "確認啟用隔離演練"}</Button></DialogFooter>
    </DialogContent></Dialog>
  </details>;
}
