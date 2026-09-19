import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { getOrgId } from "@/lib/auth";
import { getMaterialTask, listMaterialTasks, materialPath, MaterialRequestError, saveMaterialOperation, type MaterialMode, type MaterialOperation, type MaterialTask } from "@/lib/adsMaterialApi";
import { MaterialTaskEditor, materialModes } from "./MaterialTaskEditor";

function Panel({ brandId, campaignId, onSaved }: { brandId: string; campaignId: string; onSaved?: () => void }) {
  const [params, setParams] = useSearchParams();
  const linkedTask = params.get("material");
  const key = `material-operation:${getOrgId()}:${brandId}:${campaignId}`;
  const [tasks, setTasks] = useState<MaterialTask[] | null>(null);
  const [selected, setSelected] = useState(params.get("material"));
  const [mode, setMode] = useState<MaterialMode | null>(null);
  const [error, setError] = useState("");
  const [truncated, setTruncated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [reload, setReload] = useState(0);
  const [pending, setPending] = useState<MaterialOperation | null>(() => { try { return JSON.parse(sessionStorage.getItem(key) ?? "null") as MaterialOperation | null; } catch { return null; } });
  const controller = useRef(new AbortController());
  useEffect(() => { controller.current = new AbortController(); return () => controller.current.abort(); }, []);
  useEffect(() => {
    const request = new AbortController();
    listMaterialTasks(brandId, campaignId, request.signal).then(async value => {
      const linked = linkedTask;
      const extra = linked && !value.tasks.some(row => row.id === linked) ? await getMaterialTask(brandId, campaignId, linked, request.signal) : null;
      if (!request.signal.aborted) { setTasks(extra ? [extra.task, ...value.tasks] : value.tasks); setTruncated(Boolean(value.truncated)); setError(""); }
    }).catch(() => { if (!request.signal.aborted) setError("素材任務暫時讀取不到，請重新讀取。原檔與已保存的版本仍會保留。"); });
    return () => request.abort();
  }, [brandId, campaignId, reload, linkedTask]);
  const task = tasks?.find(row => row.id === selected);
  async function perform(operation: MaterialOperation) {
    if (busy) return;
    const signal = controller.current.signal; setBusy(true); setError("");
    try {
      sessionStorage.setItem(key, JSON.stringify(operation)); setPending(operation);
      const result = await saveMaterialOperation(operation, signal);
      if (signal.aborted) return;
      sessionStorage.removeItem(key); setPending(null); setTasks(current => [result.task, ...(current ?? []).filter(row => row.id !== result.task.id)]); setSelected(result.task.id); setMode(null);
      onSaved?.();
      setParams(previous => { const next = new URLSearchParams(previous); next.set("material", result.task.id); next.delete("material_new"); return next; }, { replace: true });
    } catch (err) {
      if (signal.aborted) return;
      if (err instanceof MaterialRequestError && err.status >= 400 && err.status < 500) { sessionStorage.removeItem(key); setPending(null); }
      setError(err instanceof Error ? err.message : "未收到保存結果。請沿用同一次操作核對，不要再建立另一份需求。");
    } finally { if (!signal.aborted) setBusy(false); }
  }
  async function save(suffix: string, body: Record<string, unknown>, method: "POST" | "PATCH" = "POST") {
    if (pending) { setError("上一筆保存結果尚未確認，請先重試同一次操作。"); return; }
    await perform({ path: `${materialPath(brandId, campaignId)}${suffix}`, method, body: { ...body, operation_id: crypto.randomUUID() } });
  }
  return <div className="space-y-4">
    <div className="flex flex-wrap justify-between gap-3"><div><h2 className="text-xl font-semibold">準備這次需要的素材</h2><p className="mt-1 text-sm text-muted-foreground">已有成品直接使用；只改文案可以獨立處理。每份需求保留版本與來源。</p></div><Button variant="outline" disabled={busy || dirty} onClick={() => { setSelected(null); setMode(null); }}><Plus className="mr-2 size-4" />新增素材需求</Button></div>
    {error && <p role="alert" className="rounded-md bg-destructive/5 p-3 text-sm">{error}</p>}
    {pending && <div className="rounded-md bg-warning/10 p-3 space-y-2"><p className="text-sm">有一筆操作的結果尚未確認。原內容與操作識別已保留，重試不會另建一份。</p><Button disabled={busy} variant="outline" onClick={() => void perform(pending)}>核對同一次保存</Button></div>}
    {truncated && <p className="text-sm text-muted-foreground">目前顯示最近 100 份需求；較早的版本仍保留，可由原任務連結讀取。</p>}
    {tasks === null ? <p role="status">正在讀取素材任務…</p> : task || mode ? <MaterialTaskEditor key={task ? `${task.id}:${task.revision}:${reload}` : `new:${mode}`} brandId={brandId} campaignId={campaignId} task={task} mode={task?.mode ?? mode!} busy={busy || Boolean(pending)} onDirtyChange={setDirty} save={save} onCancel={() => { setSelected(null); setMode(null); }} reviewId={params.get("review") ?? undefined} recommendationId={params.get("recommendation") ?? undefined} /> : <>
      {params.get("material_new") && <p className="rounded-md bg-accent p-3 text-sm">從上次檢討交棒的新需求：請選擇素材來源，保存時會連回原建議。</p>}
      <div className="grid gap-3 lg:grid-cols-2">{(Object.entries(materialModes) as [MaterialMode, typeof materialModes[MaterialMode]][]).map(([value, item]) => <button key={value} disabled={busy || Boolean(pending)} className="surface p-4 text-left transition-colors hover:border-primary focus-visible:outline-primary" onClick={() => setMode(value)}><h3 className="font-semibold">{item.title}</h3><p className="mt-1 text-sm text-muted-foreground">{item.description}</p></button>)}</div>
      {tasks.length > 0 && <section className="surface"><div className="surface-header"><h3 className="font-semibold">已保存的需求</h3></div><div className="divide-y divide-border">{tasks.map(row => <button className="flex w-full items-center justify-between gap-4 p-4 text-left hover:bg-muted" key={row.id} disabled={busy} onClick={() => { setSelected(row.id); setMode(null); }}><div><p className="font-medium">{row.title}</p><p className="mt-1 text-xs text-muted-foreground">{materialModes[row.mode].title} · 版本 {row.revision}{row.review_id ? " · 承接檢討" : ""}</p></div><Badge variant="outline">{row.placement_id ? "成品已採用" : row.pack_id ? "工作台已交接" : row.candidates.length ? "待挑選成品" : "待準備"}</Badge></button>)}</div></section>}
    </>}
    <Button variant="ghost" size="sm" disabled={busy || dirty} onClick={() => setReload(value => value + 1)}><RefreshCw className="mr-2 size-4" />重新讀取素材任務</Button>
  </div>;
}
export function MaterialTasksPanel(props: Parameters<typeof Panel>[0]) { return <Panel key={`${getOrgId()}:${props.brandId}:${props.campaignId}`} {...props} />; }
