import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Clock3, RefreshCw, ShieldCheck } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Badge } from "@/components/layout/ui/badge";
import { getOrgId } from "@/lib/auth";
import { formatInstant, useOrgClock } from "@/lib/orgClock";
import { getRuntime, saveMonitor, type ReviewMonitor, type RuntimeData } from "@/lib/adsRuntimeApi";
import { Disclosure, useAdsRules } from "./patterns";
import { useAssetDraftGuard } from "./useAssetDraftGuard";

const states: Record<ReviewMonitor["state"], string> = { scheduled: "等待下次檢討", waiting: "等待資料與觀察期", queued: "已安排檢討", running: "正在整理建議", ready: "建議已備妥", needs_attention: "需要確認後續處理", paused: "自動檢討已暫停" };
/** An instant as 「MM/DD HH:MM」 on the org clock (F50 Contract K); none yet → 「尚無紀錄」. */
const date = (value: string | null, timezone: string) => formatInstant(value, timezone, "md_hm") || "尚無紀錄";
function Tracking({ brandId, campaignId, entityId, refreshKey }: { brandId: string; campaignId: string; entityId: string; refreshKey: string }) {
  const { timezone } = useOrgClock();
  // F50 Contract I (decision 11): the day range is served (`limits.review_days`, the range `review_monitor` checks);
  // before the rules load nothing is checked here and the server's own sentence comes back.
  const days = useAdsRules()?.limits.review_days ?? null;
  const [data, setData] = useState<RuntimeData | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [edit, setEdit] = useState<{ window: string; cadence: string } | null>(null);
  const [saved, setSaved] = useState(false);
  const lifetime = useRef(new AbortController());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  useAssetDraftGuard(Boolean(edit), "追蹤條件尚未保存。離開將放棄本次修改，原有追蹤仍依已保存條件執行。確定離開？");
  useEffect(() => {
    const controller = new AbortController();
    getRuntime(brandId, campaignId, controller.signal).then(value => { if (!controller.signal.aborted) { setData(value); setError(""); } })
      .catch(() => { if (!controller.signal.aborted) setError("追蹤進度暫時讀取不到，請重新讀取；不代表背景工作已停止。"); });
    return () => controller.abort();
  }, [brandId, campaignId, refreshKey, reload]);
  const monitor = data?.monitors.find(row => row.entity_id === entityId);
  async function save(enabled: boolean) {
    if (!monitor || busy) return;
    const windowDays = Number(edit?.window ?? monitor.window_days), cadenceDays = Number(edit?.cadence ?? monitor.cadence_days);
    if (days && ![windowDays, cadenceDays].every(n => Number.isInteger(n) && n >= days.min && n <= days.max)) { setError(`觀察期與檢討間隔請填 ${days.min} 至 ${days.max} 天。`); return; }
    setBusy(true); setError(""); setSaved(false);
    const signal = lifetime.current.signal;
    try {
      await saveMonitor(brandId, campaignId, entityId, { expected_revision: monitor.revision, enabled, window_days: windowDays, cadence_days: cadenceDays, reset_window: false }, signal);
      const result = await getRuntime(brandId, campaignId, signal);
      if (!signal.aborted) { setData(result); setEdit(null); setSaved(true); }
    } catch (err) { if (!signal.aborted) setError(err instanceof Error ? err.message : "保存結果未確認，請先重新讀取。"); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  return <section className="surface" aria-label="持續追蹤">
    <div className="surface-header flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><Clock3 className="size-5 text-primary" /><h3 className="font-semibold">持續追蹤</h3>{monitor && <Badge variant="outline">{states[monitor.state] ?? "進度待確認"}</Badge>}</div><p className="mt-2 text-sm text-muted-foreground">{monitor?.reason ?? (monitor ? "依條件自動整理下一輪，你只需決定重要變更。" : "開始第一次檢討後，系統會沿用資料持續追蹤這則廣告。")}</p></div><Button variant="ghost" size="sm" disabled={busy || Boolean(edit)} onClick={() => { setSaved(false); setReload(n => n + 1); }}><RefreshCw className="size-4" />更新追蹤進度</Button></div>
    <div className="surface-body space-y-3">
      {error && <div role="alert" className="rounded-md bg-warning/10 p-3 text-sm"><p>{error}</p>{edit && <Button size="sm" variant="outline" className="mt-2" disabled={busy} onClick={() => setReload(n => n + 1)}>讀取已保存版本（保留輸入）</Button>}</div>}
      {!data && !error && <p role="status" className="text-sm text-muted-foreground">正在讀取已保存的追蹤條件…</p>}
      {saved && <p role="status" className="text-sm text-success">追蹤條件已保存並重新讀回。</p>}
      {monitor && <div className="grid gap-3 md:grid-cols-3"><div><p className="text-xs text-muted-foreground">本次觀察範圍</p><p className="mt-1 text-sm font-medium">{monitor.window ? `${monitor.window.start} — ${monitor.window.end}` : "待完整日期與資料"}</p></div><div><p className="text-xs text-muted-foreground">下次檢查時間</p><p className="mt-1 text-sm font-medium">{monitor.enabled ? monitor.next_check_at ? date(monitor.next_check_at, timezone) : "待本次決定或新證據" : "自動檢討暫停"}</p></div><div><p className="text-xs text-muted-foreground">背景最近回報</p><p className="mt-1 text-sm font-medium">{date(data?.last_checked_at ?? null, timezone)}</p></div></div>}
      {data?.health.length ? <div className="rounded-md border border-warning/25 bg-warning/5 p-3 text-sm"><p className="font-medium">最近檢查發現</p><ul className="mt-1 space-y-1">{data.health.map(item => <li key={item.code}>{item.message}</li>)}</ul><Link className="mt-2 inline-block font-medium text-primary" to={`/brands/${brandId}/ads`}>檢視月預算與來源 →</Link></div> : null}
      <p className="flex gap-2 text-xs text-muted-foreground"><ShieldCheck className="size-4 shrink-0" /><span>暫緩或完成本次檢討，都不會停止平台花費。來源同步與待辦核對持續進行；平台操作仍由你手動完成。</span></p>
      <Disclosure label="查看同步、恢復與追蹤設定">
        <div className="space-y-4 text-sm">
          <div className="space-y-2"><h4 className="font-medium">資料與服務</h4>{data?.sources.map(source => <div key={`${source.platform}:${source.source_account}`} className="rounded-md border border-border p-3"><p>{source.platform} · {source.source_account}</p><p className="mt-1 text-muted-foreground">{source.status === "pending" || source.status === "running" ? "同步排隊或進行中，保留原進度" : source.error ?? (source.status === "succeeded" ? "上次同步完成" : "同步狀態待確認")}</p><p className="mt-1 text-xs text-muted-foreground">最近成功：{date(source.last_success_at, timezone)}{source.coverage ? ` · 最近完成讀取範圍 ${source.coverage.start} — ${source.coverage.end}` : " · 涵蓋日期尚未確認"}</p></div>)}{!data?.sources.length && <p className="text-muted-foreground">尚無已對應的平台來源；先匯入或核對平台廣告。</p>}<p className="text-xs text-muted-foreground">最近背景啟動紀錄：{date(data?.last_bootstrap_at ?? null, timezone)}。這不能證明前次停機從何時開始。</p><p className="rounded-md bg-muted p-3">{data?.notice ?? "關閉網頁不影響背景工作；本機或服務停止時會中斷監測，平台仍可能花費。"}</p></div>
          {monitor && <div className="space-y-3 border-t border-border pt-3"><div className="flex flex-wrap items-center justify-between gap-3"><div><h4 className="font-medium">這則廣告的自動檢討</h4><p className="mt-1 text-xs text-muted-foreground">每 {monitor.cadence_days} 天檢查，觀察最近 {monitor.window_days} 個完整日期；缺資料時先補回，不反覆請 AI 產生相同報告。</p></div><Button variant="outline" size="sm" disabled={busy || Boolean(edit)} onClick={() => void save(!monitor.enabled)}>{monitor.enabled ? "暫停自動檢討" : "恢復自動檢討"}</Button></div>
            {edit ? <><div className="grid grid-cols-2 gap-3"><label>觀察天數<Input type="number" min={days?.min} max={days?.max} value={edit.window} onChange={e => setEdit({ ...edit, window: e.target.value })} disabled={busy} /></label><label>檢討間隔（天）<Input type="number" min={days?.min} max={days?.max} value={edit.cadence} onChange={e => setEdit({ ...edit, cadence: e.target.value })} disabled={busy} /></label></div><p className="text-xs text-muted-foreground">目前未完成的觀察範圍仍保留，新條件用於後續檢討。</p><div className="flex gap-2"><Button size="sm" disabled={busy} onClick={() => void save(monitor.enabled)}>保存追蹤條件</Button><Button variant="outline" size="sm" disabled={busy} onClick={() => setEdit(null)}>取消修改</Button></div></> : <Button variant="outline" size="sm" disabled={busy} onClick={() => { setSaved(false); setEdit({ window: String(monitor.window_days), cadence: String(monitor.cadence_days) }); }}>調整觀察與檢討天數</Button>}
          </div>}
        </div>
      </Disclosure>
    </div>
  </section>;
}
export function ReviewTracking(props: Parameters<typeof Tracking>[0]) { return <Tracking key={`${getOrgId()}:${props.brandId}:${props.campaignId}:${props.entityId}`} {...props} />; }
