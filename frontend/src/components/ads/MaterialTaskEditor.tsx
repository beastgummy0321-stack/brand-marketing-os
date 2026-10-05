import { useEffect, useState } from "react";
import { formatInstant, useOrgClock } from "@/lib/orgClock";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { CopyIconButton } from "@/components/layout/CopyIconButton";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/layout/ui/dialog";
import { materialOptions, promptInput, type MaterialMode, type MaterialOption, type MaterialPrompt, type MaterialTask } from "@/lib/adsMaterialApi";
import type { CopyFields } from "@/lib/adsUserAssetsApi";
import { CopyEditor, UserAssetsLibrary } from "./UserAssetsLibrary";
import { AuthAssetMedia } from "./AuthAssetMedia";
import { Disclosure } from "./patterns";
import { useAssetDraftGuard } from "./useAssetDraftGuard";

export const materialModes: Record<MaterialMode, { title: string; description: string }> = {
  existing: { title: "使用已有成品", description: "上傳圖片或影片，直接安排使用。" },
  external_image: { title: "回收外部生圖", description: "保存提示詞與參考圖，再挑選外部工具產出的成品。" },
  workbench_image: { title: "請工作台準備新圖", description: "承接這次需求，準備圖片提示詞，再帶到外部工具生圖。" },
  copy: { title: "只準備新文案", description: "圖片保持不變；在工作台整理新的文字方向。" },
};
type Save = (suffix: string, body: Record<string, unknown>, method?: "POST" | "PATCH") => Promise<void>;
export function MaterialTaskEditor({ brandId, campaignId, task, mode, busy, save, onCancel, reviewId, recommendationId, onDirtyChange }: {
  brandId: string; campaignId: string; task?: MaterialTask; mode: MaterialMode; busy: boolean; save: Save; onCancel: () => void;
  reviewId?: string; recommendationId?: string; onDirtyChange: (dirty: boolean) => void;
}) {
  const { timezone } = useOrgClock();
  const [title, setTitle] = useState(task?.title ?? materialModes[mode].title);
  const [instruction, setInstruction] = useState(task?.instruction ?? "");
  const [copy, setCopy] = useState<CopyFields>(task?.copy_fields ?? {});
  const [prompt, setPrompt] = useState<MaterialPrompt>(task?.prompt ?? { source: "none" });
  const [refs, setRefs] = useState<string[]>(task?.reference_asset_ids ?? []);
  const [picker, setPicker] = useState<"reference" | "candidate" | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [options, setOptions] = useState<MaterialOption[]>([]);
  const [notice, setNotice] = useState("");
  const [stage, setStage] = useState<"source" | "results">(task && (task.mode === "existing" || task.candidates.length) ? "results" : "source");
  const [visible, setVisible] = useState(10);
  const [selected, setSelected] = useState(task?.selected_candidate_id ?? "");
  const dirty = title !== (task?.title ?? materialModes[mode].title) || instruction !== (task?.instruction ?? "") || JSON.stringify(copy) !== JSON.stringify(task?.copy_fields ?? {}) || JSON.stringify(prompt) !== JSON.stringify(task?.prompt ?? { source: "none" }) || JSON.stringify(refs) !== JSON.stringify(task?.reference_asset_ids ?? []);
  useAssetDraftGuard(dirty);
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false); }, [dirty, onDirtyChange]);
  const taskId = task?.id;
  const packId = task?.pack_id;
  useEffect(() => {
    if (!taskId) return;
    const controller = new AbortController();
    materialOptions(brandId, campaignId, taskId, controller.signal).then(value => setOptions(value.options)).catch(() => { if (!controller.signal.aborted) setNotice("工作台內容暫時讀取不到。可以前往工作台確認進度，再回來重新讀取。"); });
    return () => controller.abort();
  }, [brandId, campaignId, taskId, packId]);
  const patch = { title, instruction, copy_fields: copy, prompt: promptInput(prompt), reference_asset_ids: refs };
  async function saveDraft() { await save(task ? `/${task.id}` : "", task ? { ...patch, expected_revision: task.revision } : { ...patch, mode, ...(reviewId ? { review_id: reviewId, recommendation_id: recommendationId } : {}) }, task ? "PATCH" : "POST"); }
  async function applyPicked() {
    if (picker === "reference") { if (new Set([...refs, ...picked]).size > 10) { setNotice("參考圖最多保留十張，請先移除不需要的來源。"); setPicker(null); return; } setRefs([...new Set([...refs, ...picked])]); setPicker(null); return; }
    if (task && picked.length) { await save(`/${task.id}/candidates`, { expected_revision: task.revision, asset_ids: picked, prompt: promptInput(task.prompt), reference_asset_ids: task.reference_asset_ids }); setPicker(null); }
  }
  return <section className="surface" aria-label="素材任務">
    <div className="surface-header flex items-start justify-between gap-3"><div><h3 className="font-semibold">{materialModes[mode].title}</h3><p className="mt-1 text-sm text-muted-foreground">{materialModes[mode].description}</p></div><Button variant="ghost" disabled={busy} onClick={() => { if (!dirty || window.confirm("放棄尚未保存的編輯？已保存的任務仍會保留。")) onCancel(); }}>返回任務</Button></div>
    <div className="surface-body space-y-4">
      {(task?.review_id || reviewId) && <div className="rounded-md bg-accent p-3 text-sm"><p className="font-medium">承接上一次檢討的新測試</p><p className="mt-1">這份需求會保留建議來源與待驗假設，供下一輪比對。</p>{typeof task?.review_context?.hypothesis === "string" && <p className="mt-2">待驗假設：{task.review_context.hypothesis}</p>}<Link className="mt-2 inline-block text-primary" to={`?tab=performance&review=${encodeURIComponent(task?.review_id ?? reviewId!)}`}>查看來源檢討</Link></div>}
      {notice && <p role="status" className="text-sm text-warning">{notice}</p>}
      {task && mode !== "copy" && <div className="flex flex-wrap gap-2" aria-label="素材準備步驟"><Button variant={stage === "source" ? "default" : "outline"} disabled={busy} onClick={() => setStage("source")}>1. 需求與來源</Button><Button variant={stage === "results" ? "default" : "outline"} disabled={busy || dirty} onClick={() => setStage("results")}>2. 選擇成品</Button></div>}
      <div hidden={stage !== "source"} inert={stage !== "source"} className="space-y-4">
      <label className="block text-sm">任務名稱<Input value={title} maxLength={200} disabled={busy} onChange={event => setTitle(event.target.value)} /></label>
      <label className="block text-sm">這次想傳達什麼<Textarea value={instruction} disabled={busy} onChange={event => setInstruction(event.target.value)} placeholder="例如：想測試通勤情境，保留原本商品特色。" /></label>
      {mode !== "copy" && <Disclosure label={mode === "existing" ? "生成來源與參考圖（選填）" : "提示詞與參考圖"} defaultOpen={mode !== "existing"}><div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border p-4 space-y-3"><h4 className="font-medium">參考圖（選填）</h4><p className="text-xs text-muted-foreground">保存你提供的來源；不代表平台或外部工具已證實使用。</p>{refs.length ? refs.map((id, index) => <div key={id} className="space-y-2"><p className="text-sm">參考圖 R{index + 1}</p><AuthAssetMedia autoPreview brandId={brandId} assetId={id} filename={`參考圖 R${index + 1}`} mime="image/*" /><Button size="sm" variant="ghost" disabled={busy} onClick={() => setRefs(refs.filter(value => value !== id))}>移除此參考關係</Button></div>) : <p className="text-sm text-muted-foreground">來源尚未提供，保留未知。</p>}<Button variant="outline" disabled={busy} onClick={() => { setPicked([]); setPicker("reference"); }}>選擇或上傳參考圖</Button></div>
        <div className="rounded-lg border border-border p-4 space-y-3"><h4 className="font-medium">提示詞（選填）</h4>{options.filter(option => option.part === "image_prompt").length > 0 && <label className="block text-sm">工作台提示詞<select className="mt-1 w-full" aria-label="選擇工作台提示詞" value="" disabled={busy} onChange={event => { const option = options[Number(event.target.value)]; if (option) setPrompt({ source: "workbench", set_id: option.set_id, version_id: option.version_id, card_index: option.card_index, text: option.text }); }}><option value="">選擇版本與提示詞</option>{options.map((option, index) => option.part === "image_prompt" && <option key={index} value={index}>{option.label}</option>)}</select></label>}<Textarea aria-label="素材提示詞" value={prompt.text ?? ""} disabled={busy} onChange={event => setPrompt(event.target.value ? { source: "manual", text: event.target.value } : { source: "none" })} placeholder="貼上實際使用的提示詞；不清楚時留空。" /><p className="text-xs text-muted-foreground">{prompt.source === "workbench" ? "已選工作台版本，修改文字會另記為手動提示詞。" : prompt.source === "manual" ? "來源為使用者提供，尚非平台證實。" : "提示詞來源未知。"}</p><CopyIconButton label="複製提示詞" ariaLabel="複製提示詞" className="h-9 px-4 text-sm" disabled={!prompt.text} getText={() => prompt.text ?? ""} onResult={copied => { if (copied) setNotice("提示詞已複製。請連同參考圖帶到外部工具，完成後回來上傳。"); }} /></div>
      </div></Disclosure>}
      <Disclosure label={copy.headline || copy.body ? "搭配文案（已有內容）" : "搭配文案（尚未提供）"}><CopyEditor value={copy} onChange={value => { setCopy(value); if (mode === "copy") setPrompt(Object.values(value).some(Boolean) ? { source: "manual", text: Object.values(value).filter(Boolean).join("\n"), ...(prompt.source === "workbench" ? { origin: `依工作台版本 ${prompt.version_id} 手動修訂` } : prompt.origin ? { origin: prompt.origin } : {}) } : { source: "none" }); }} prefix="素材" disabled={busy} />{options.filter(option => option.part === "copy").map((option, index) => <Button key={index} variant="outline" className="mt-2" disabled={busy} onClick={() => { setCopy(option.copy_fields ?? {}); setPrompt({ source: "workbench", set_id: option.set_id, version_id: option.version_id, card_index: option.card_index, text: option.text }); }}>使用{option.label}</Button>)}</Disclosure>
      <div className="flex flex-wrap items-center gap-3"><Button disabled={busy || !title.trim() || Boolean(task && !dirty)} onClick={() => void saveDraft()}>{busy ? "保存中…" : task ? "保存本次修訂" : "保存素材需求"}</Button>{dirty && <span className="text-sm text-warning">尚未保存</span>}</div>
      </div>
      {task && !dirty && <>
        {stage === "source" && (mode === "workbench_image" || mode === "copy") && <div className="rounded-md bg-accent p-4 space-y-3"><p className="text-sm">工作台會使用這份已保存的需求準備{mode === "copy" ? "文案" : "圖片提示詞"}。圖片仍由你到外部工具生成後回收。</p>{task.state_label && <p data-slot="material-task-state" className={`text-sm ${task.dispatch_status === "unknown" ? "text-warning" : "text-muted-foreground"}`}>目前：{task.state_label}</p>}{/* F49 Contract T: a hand-off left `unknown` (its pack's enqueue failed) is retried by the same dispatch call — the server reuses the stored pack, never a second one. */}{task.dispatch_status !== "unknown" && task.pack_id ? <Button asChild><Link to={`/brands/${brandId}/workbench/packs/${task.pack_id}`}>前往本次工作台任務</Link></Button> : <Button disabled={busy} onClick={() => void save(`/${task.id}/dispatch`, { expected_revision: task.revision, content_hash: task.content_hash })}>{task.dispatch_status === "unknown" ? "重新交給工作台" : "確認需求，交給工作台"}</Button>}</div>}
        {mode === "copy" && (task.copy_fields.headline || task.copy_fields.body) && <Button asChild><Link to={`?tab=changes&material_copy=${encodeURIComponent(task.id)}`}>使用這版文案，修改原廣告</Link></Button>}
        {mode !== "copy" && stage === "source" && <Button variant="outline" disabled={busy} onClick={() => setStage("results")}>來源已保存，接著選擇成品</Button>}
        {mode !== "copy" && stage === "results" && <div className="space-y-3"><p className="rounded-md bg-muted p-3 text-sm">本批來源：{task.prompt.source === "none" ? "提示詞未知" : task.prompt.source === "workbench" ? "工作台所選版本" : "使用者提供提示詞"} · 參考圖 {task.reference_asset_ids.length} 張。這是來源紀錄，並非平台證實。</p><div className="flex flex-wrap justify-between gap-3"><div><h4 className="font-semibold">{mode === "existing" ? "選擇要使用的成品" : "回收成品，再挑選一張"}</h4><p className="mt-1 text-xs text-muted-foreground">每批最多 10 張；保存當批提示詞與參考圖，舊批次仍保留。</p></div><Button variant="outline" disabled={busy} onClick={() => { setPicked([]); setPicker("candidate"); }}>上傳或選擇成品</Button></div><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{task.candidates.slice(-visible).map((candidate, index) => <article key={candidate.id} className={`min-w-0 rounded-lg border p-3 space-y-3 ${candidate.id === selected ? "border-primary bg-accent" : "border-border"}`}><label className="flex gap-2 text-sm"><input type="radio" name="material-candidate" disabled={busy} checked={selected === candidate.id} onChange={() => setSelected(candidate.id)} />成品 {Math.max(0, task.candidates.length - visible) + index + 1}</label><p className="truncate text-xs" title={candidate.filename}>{candidate.filename}</p><AuthAssetMedia autoPreview brandId={brandId} assetId={candidate.asset_id} filename={candidate.filename} mime={candidate.mime_type} /><p className="text-xs text-muted-foreground">{candidate.prompt.source === "none" ? "提示詞未知" : "已保存提示詞來源"} · 參考圖 {candidate.reference_asset_ids.length} 張</p></article>)}</div>{task.candidates.length > visible && <Button variant="outline" onClick={() => setVisible(value => value + 10)}>顯示較早回收的成品</Button>}{selected && <Button disabled={busy || task.selected_candidate_id === selected} onClick={() => void save(`/${task.id}/select`, { expected_revision: task.revision, content_hash: task.content_hash, candidate_id: selected })}>採用這份成品</Button>}</div>}
        {task.placement_id && <div className="rounded-md bg-accent p-4 text-sm space-y-2"><p className="font-medium">成品已加入素材安排，尚未上架平台</p><p>{task.placement_current === false ? "安排已有更新；本任務仍保留當時採用的版本。請檢視目前安排再交接。" : "下一步確認文案、用途及投放對象，再建立變更清單。"}</p><a className="inline-block text-primary" href="#material-placements">檢視素材安排與人工交接</a></div>}
        {(task.limitations.length > 0 || task.history.length > 1) && <Disclosure label="來源限制與版本紀錄"><div className="space-y-2 text-sm">{task.limitations.map((value, index) => <p key={index}>{value}</p>)}{task.history.map(row => <p key={row.revision}>需求版本 {row.revision} · {formatInstant(row.created_at, timezone, "md_hm")}</p>)}</div></Disclosure>}
      </>}
    </div>
    <Dialog open={picker !== null} onOpenChange={open => { if (!open && !busy) setPicker(null); }}><DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-4xl"><DialogTitle>{picker === "reference" ? "選擇參考圖" : "回收本批成品"}</DialogTitle><DialogDescription>已保存的品牌原檔可直接使用；也可以在這裡上傳新檔案。</DialogDescription><UserAssetsLibrary key={picker} brandId={brandId} onSelection={uploads => setPicked(uploads.filter(row => row.status === "complete" && row.asset_id).map(row => row.asset_id!))} onAttach={async upload => { if (upload.asset_id) setPicked(current => [...new Set([...current, upload.asset_id!])]); }} onAttachAsset={async id => setPicked(current => [...new Set([...current, id])])} readOnly={busy} /><div className="sticky bottom-0 flex items-center justify-between gap-2 bg-card pt-3"><p className="text-sm">已選 {picked.length} 份原檔</p><Button disabled={busy || !picked.length || (picked.length > 10)} onClick={() => void applyPicked()}>{picker === "reference" ? "加入參考圖" : "保存這批成品"}</Button></div></DialogContent></Dialog>
  </section>;
}
