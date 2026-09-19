import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { assignPlannedMaterial, getPlannedMaterials, type PlannedMaterialWorkspace } from "@/lib/adsHandoffApi";

type Props = { brandId: string; campaignId: string; refreshKey?: number; onSaved?: () => void };
const statusLabel = { unassigned: "尚未指派", confirmed: "已指派確認版本", stale: "素材已更新，需重新指派" };
export function PlannedMaterialAssignments(props: Props) {
  const { scope } = useWorkspace();
  return <Assignments key={`${scope}:${props.brandId}:${props.campaignId}`} {...props} />;
}
function Assignments({ brandId, campaignId, refreshKey = 0, onSaved }: Props) {
  const [data, setData] = useState<PlannedMaterialWorkspace | null>(null);
  const [adId, setAdId] = useState("");
  const [placementId, setPlacementId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const controller = useRef(new AbortController());
  useEffect(() => {
    const active = new AbortController(); controller.current = active;
    setBusy(true); setError("");
    getPlannedMaterials(brandId, campaignId, active.signal).then(value => {
      if (!active.signal.aborted) { setData(value); setAdId(""); setPlacementId(""); }
    }).catch(err => { if (!active.signal.aborted) setError(err instanceof Error ? err.message : "暫時無法讀取素材指派。"); })
      .finally(() => { if (!active.signal.aborted) setBusy(false); });
    return () => active.abort();
  }, [brandId, campaignId, refreshKey, reload]);
  const ad = data?.planned_ads.find(row => row.id === adId);
  const placement = data?.ready_placements.find(row => row.id === placementId);
  async function save(clear = false) {
    if (busy || !ad || (!clear && !placement)) return;
    const active = controller.current;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await assignPlannedMaterial(brandId, campaignId, ad.id, { placement_id: clear ? null : placement!.id, revision: clear ? null : placement!.revision }, active.signal);
      if (active.signal.aborted) return;
      setData(result); setPlacementId("");
      setNotice(clear ? "已解除這則廣告的素材指派。" : "素材版本已指派，首次上架清單會核對這份對應。");
      onSaved?.();
    } catch (err) { if (!active.signal.aborted) setError(err instanceof Error ? err.message : "保存結果尚未確認，請重新讀取核對指派，勿重做平台操作。"); }
    finally { if (!active.signal.aborted) setBusy(false); }
  }
  return <section className="surface" aria-label="指派首次投放素材">
    <div className="surface-header flex flex-wrap items-center justify-between gap-3"><div><h2>將成品指派給計畫中的廣告</h2><p className="mt-1 text-sm text-muted-foreground">選擇已確認的素材版本與對應廣告。保存後才會納入首次上架清單，不會在平台建立或更改廣告。</p></div><Button variant="outline" disabled={busy} onClick={() => { setNotice(""); setReload(value => value + 1); }}>重新讀取素材指派</Button></div>
    <div className="surface-body space-y-4">
      {busy && !data && <p role="status">讀取計畫廣告與已確認成品…</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {notice && <p role="status" className="text-sm text-primary">{notice}</p>}
      {data && <>
        {!data.planned_ads.length ? <p className="text-sm text-muted-foreground">計畫尚未有廣告，先到<Link className="text-primary underline" to="?tab=structure">投放結構</Link>確認計畫中的投放組與廣告，再回來指派成品。</p> : <>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">計畫中的廣告<select className="mt-1 block w-full" value={adId} disabled={busy} onChange={event => { setAdId(event.target.value); setPlacementId(""); setNotice(""); }}><option value="">請選擇</option>{data.planned_ads.map(row => <option key={row.id} value={row.id}>{row.group_name} · {row.name}</option>)}</select></label>
            <label className="text-sm">已確認成品版本<select className="mt-1 block w-full" value={placementId} disabled={busy || !adId} onChange={event => setPlacementId(event.target.value)}><option value="">請選擇</option>{data.ready_placements.map(row => <option key={`${row.id}:${row.revision}`} value={row.id}>{row.filename} · 版本 {row.revision}</option>)}</select></label>
          </div>
          {!data.ready_placements.length && <p className="text-sm text-warning">尚無可用的已確認成品。請先在素材安排確認文案與版本，再重新讀取。</p>}
          {placement && <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm"><p className="font-medium">{placement.filename} · 版本 {placement.revision}</p><p className="mt-2 whitespace-pre-wrap break-words">{placement.copy_fields.headline || "尚未提供標題"}</p><p className="mt-1 whitespace-pre-wrap break-words text-muted-foreground">{placement.copy_fields.body || "尚未提供內文"}</p></div>}
          <div className="flex flex-wrap gap-2"><Button disabled={busy || !ad || !placement} onClick={() => void save()}>保存素材指派</Button>{ad?.placement_id && <Button variant="outline" disabled={busy} onClick={() => void save(true)}>解除此廣告的素材指派</Button>}</div>
          <div className="divide-y divide-border rounded-lg border border-border">{data.planned_ads.map(row => <div key={row.id} className="space-y-1 p-3 text-sm"><p className="font-medium">{row.group_name} · {row.name}</p><p className={row.assignment_status === "stale" ? "text-warning" : "text-muted-foreground"}>{statusLabel[row.assignment_status]}{row.filename ? ` · ${row.filename} · 版本 ${row.placement_revision}` : ""}</p>{row.reason && <p className="text-muted-foreground">{row.reason}</p>}</div>)}</div>
          <p className="text-xs text-muted-foreground">更換素材或版本後，原上架清單需要重新確認；未指派的廣告不會自動套用其他成品。</p>
        </>}
      </>}
    </div>
  </section>;
}
