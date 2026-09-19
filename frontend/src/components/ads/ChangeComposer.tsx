import { Link } from "react-router-dom";
import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import type { NativeEntity } from "@/lib/adsExternalApi";
import type { ChangeDraft, ChangeInput, ChangeKind, ChangeSet } from "@/lib/adsChangeApi";
import { formatSyncTime } from "@/lib/format";

export const kindLabel = { copy: "修改文案，保留圖片", budget: "調整每日預算", pause: "暫停投放" };
export function targetLabel(target: Pick<NativeEntity, "native_kind" | "name" | "native_id">) {
  const layer: Record<string, string> = { ad: "廣告", adset: "廣告組（Ad Set）", campaign: "活動（Campaign）" };
  return `${target.name || "未命名"} · ${layer[target.native_kind] ?? target.native_kind}`;
}
function originalCopy(target?: NativeEntity) {
  const fields = target?.creative.fields ?? {};
  const story = fields.object_story_spec as { link_data?: { message?: string; name?: string } } | undefined;
  return { title: String(fields.title ?? story?.link_data?.name ?? ""), body: String(fields.body ?? story?.link_data?.message ?? "") };
}
function blank(targets: NativeEntity[], kind: ChangeKind = "copy"): ChangeInput {
  const target = targets.find(t => kind === "copy" ? t.native_kind === "ad" : kind === "budget" ? t.native_kind !== "ad" : true);
  return { kind, target_id: target?.id ?? "", reason: "", after: kind === "copy" ? originalCopy(target) : kind === "pause" ? { status: "PAUSED" } : {} };
}

export function ChangeComposer({ targets, month, pending, initial, initialDraft, busy, onSave, onClose }: {
  targets: NativeEntity[]; month: string; pending: ChangeDraft | null; initial?: ChangeSet; initialDraft?: Omit<ChangeDraft, "operation_id">; busy: boolean;
  onSave: (value: Omit<ChangeDraft, "operation_id">) => void; onClose: () => void;
}) {
  const [title, setTitle] = useState(pending?.title ?? initialDraft?.title ?? (initial ? `${initial.title}（修訂）` : "本次廣告調整"));
  const [items, setItems] = useState<ChangeInput[]>(pending?.items ?? initialDraft?.items ?? initial?.items.filter(item => item.verification_state !== "confirmed" && item.kind !== "new_ad" && item.kind !== "launch").map(({ kind, target_id, after, reason }) => ({ kind: kind as ChangeKind, target_id, after, reason })) ?? [blank(targets)]);
  const [validation, setValidation] = useState("");
  const locked = busy || Boolean(pending);
  const materialId = pending?.material_task_id ?? initialDraft?.material_task_id ?? initial?.material_task_id;
  function update(index: number, value: Partial<ChangeInput>) { setItems(rows => rows.map((item, i) => i === index ? { ...item, ...value } : item)); }
  function save() {
    if (!title.trim() || items.some(item => !item.target_id || !item.reason.trim() ||
      (item.kind === "copy" && !item.after.body?.trim() && !item.after.title?.trim()) ||
      (item.kind === "budget" && !(Number.isFinite(item.after.daily_amount) && Number(item.after.daily_amount) > 0)))) {
      setValidation("請選擇每項變更的對象，填寫新內容與原因；每日預算需大於 0。若要停止花費，請選擇暫停投放。"); return;
    }
    setValidation(""); onSave({ title: title.trim(), month, items: items.map(item => item.kind === "copy" ? { ...item, after: Object.fromEntries(Object.entries(item.after).filter(([, value]) => typeof value === "string" && value.trim())) } : item) });
  }
  return <section className="surface" aria-label="建立變更清單">
    <div className="surface-header"><div><h2>這次要調整什麼</h2><p className="text-xs text-muted-foreground">先整理清單，保存後再核准。此處不會修改平台。</p></div></div>
    <div className="surface-body space-y-4">
      {pending && <p role="status" className="rounded-md bg-warning/10 p-3 text-sm">上次保存的回應尚未確認。重試會沿用同一次操作，不會另外建立一份清單。</p>}
      <label className="block text-sm">清單名稱<Input value={title} disabled={locked} onChange={e => setTitle(e.target.value)} /></label>
      {materialId && <p className="rounded-md bg-accent p-3 text-sm">已承接保存的文案版本。如需改字，請先<Link className="text-primary" to={`?tab=assets&material=${encodeURIComponent(materialId)}`}>回到素材需求修訂</Link>，再建立這份清單。</p>}
      {items.map((item, index) => {
        const target = targets.find(t => t.id === item.target_id);
        const choices = targets.filter(t => item.kind === "copy" ? t.native_kind === "ad" : item.kind === "budget" ? t.native_kind !== "ad" : true);
        const previous = originalCopy(target);
        return <div key={index} className="rounded-lg border border-border p-4 space-y-3">
          <div className="flex items-center justify-between"><h3 className="text-sm font-semibold">變更 {index + 1}</h3>{items.length > 1 && <Button aria-label={`移除變更 ${index + 1}`} size="icon-sm" variant="ghost" disabled={locked} onClick={() => setItems(rows => rows.filter((_, i) => i !== index))}><Trash2 /></Button>}</div>
          <div className="grid gap-3 xl:grid-cols-2">
            <label className="text-sm">變更內容<select aria-label={`變更 ${index + 1} 類型`} className="mt-1 w-full" value={item.kind} disabled={locked || Boolean(materialId)} onChange={e => update(index, blank(targets, e.target.value as ChangeKind))}>{Object.entries(kindLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label className="text-sm">操作對象<select aria-label={`變更 ${index + 1} 對象`} className="mt-1 w-full" value={item.target_id} disabled={locked} onChange={e => { const selected = targets.find(t => t.id === e.target.value); update(index, { target_id: e.target.value, ...(item.kind === "copy" && !materialId ? { after: originalCopy(selected) } : {}) }); }}><option value="">請選擇</option>{choices.map(t => <option key={t.id} value={t.id}>{targetLabel(t)}</option>)}</select></label>
          </div>
          {target && <p className="text-xs text-muted-foreground">{target.platform} · 帳戶 {target.source_account} · 平台識別 {target.native_id}</p>}
          {item.kind === "copy" && <div className="grid gap-3 xl:grid-cols-2">
            <div className="rounded-md bg-muted p-3 text-sm"><p className="mb-2 font-medium">最近讀取的文案</p><p className="mb-2 text-xs text-muted-foreground">{target?.last_success_at ? `讀取時間：${formatSyncTime(target.last_success_at)}` : "尚未取得讀取時間"}</p><p className="whitespace-pre-wrap break-words">{previous.title || "標題未取得"}</p><p className="mt-2 whitespace-pre-wrap break-words text-muted-foreground">{previous.body || "內文未取得"}</p><p className="mt-3 text-xs">修改原廣告，圖片保持不變；不建立另一則廣告。</p></div>
            <div className="space-y-3"><label className="block text-sm">新標題<Input aria-label={`變更 ${index + 1} 新標題`} value={item.after.title ?? ""} disabled={locked || Boolean(materialId)} onChange={e => update(index, { after: { ...item.after, title: e.target.value } })} /></label><label className="block text-sm">新內文<Textarea aria-label={`變更 ${index + 1} 新內文`} rows={4} value={item.after.body ?? ""} disabled={locked || Boolean(materialId)} onChange={e => update(index, { after: { ...item.after, body: e.target.value } })} /></label></div>
          </div>}
          {item.kind === "budget" && <div className="space-y-2"><p className="text-sm text-muted-foreground">目前每日預算：{target?.budget_type === "daily" && target.budget_amount !== null ? `${target.currency ?? ""} ${target.budget_amount.toLocaleString()}` : "尚未取得可核對金額"}。變更作用在上述對象，不代表單則廣告有獨立預算。</p><label className="block text-sm">調整後每日預算<Input aria-label={`變更 ${index + 1} 每日預算`} type="number" min="0.01" step="0.01" disabled={locked} value={item.after.daily_amount ?? ""} onChange={e => update(index, { after: { daily_amount: e.target.value === "" ? undefined : Number(e.target.value) } })} /></label></div>}
          {item.kind === "pause" && <p className="rounded-md bg-warning/10 p-3 text-sm">核准後仍需由你到平台暫停指定對象。系統讀回前，不會認定已停止投遞或釋放額度。</p>}
          <label className="block text-sm">調整原因<Textarea aria-label={`變更 ${index + 1} 原因`} rows={2} disabled={locked} placeholder="這項調整要處理什麼問題？" value={item.reason} onChange={e => update(index, { reason: e.target.value })} /></label>
        </div>;
      })}
      {validation && <p role="alert" className="text-sm text-destructive">{validation}</p>}
      <div className="flex flex-wrap items-center justify-between gap-3"><Button variant="outline" disabled={locked || Boolean(materialId) || items.length >= 10} onClick={() => setItems(rows => [...rows, blank(targets)])}><Plus />新增一項變更</Button><div className="flex gap-2"><Button variant="outline" disabled={busy || Boolean(pending)} onClick={onClose}>取消</Button><Button disabled={busy} onClick={save}>{busy ? "保存中…" : pending ? "重試同一份清單" : "保存清單，檢視並核准"}</Button></div></div>
    </div>
  </section>;
}
