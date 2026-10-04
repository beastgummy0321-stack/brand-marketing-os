import { useEffect, useRef, useState } from "react";
import { ManualHandoffPanel } from "./ManualHandoffPanel";
import { getMaterialTask } from "@/lib/adsMaterialApi";
import { useSearchParams } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { getOrgId } from "@/lib/auth";
import { getReview } from "@/lib/adsReviewApi";
import { ChangeRequestRejected, actOnChangeItem, approveChangeSet, createChangeSet, decideChangeSet, getChangeControl, type ChangeControlData, type ChangeDraft, type ChangeSet } from "@/lib/adsChangeApi";
import { ChangeComposer } from "./ChangeComposer";
import { ChangeSetView } from "./ChangeSetView";
import { currentBudgetMonth, MonthlyBudgetPanel } from "./MonthlyBudgetPanel";
import { useOrgClock } from "@/lib/orgClock";
import { Disclosure } from "./patterns/Disclosure";
import type { TimelineRow } from "@/lib/adsWorkspaceApi";
import { isAbSet } from "./flow/changeFlow";
import { ChangesTab } from "./workspace/ChangesTab";

/** A set the step pages (`changes/:id/confirm|handoff|verify`) render: a cleanup, an A/B pause, or one item of a kind
 * they draw — the same rule their own 「這份清單有多項變更」 fallback uses. Anything else (a launch, a multi-item set
 * from the composer) is shown here, in the advanced fold. */
function flowRenders(set: ChangeSet): boolean {
  return set.source === "cleanup" || isAbSet(set)
    || (set.items.length === 1 && ["pause", "copy", "budget", "new_ad"].includes(set.items[0].kind));
}

/** The fold renders its content a frame after it opens; wait for the anchor for a few frames, then scroll to it. */
function scrollWhenShown(id: string, frames = 10) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView?.({ block: "start", behavior: "smooth" });
  else if (frames > 0) requestAnimationFrame(() => scrollWhenShown(id, frames - 1));
}

/** F47-I06 (V8): 「建立變更清單」 opens the composer below the month budget; bring it into view and put the cursor in its
 * first field, so the click visibly does something. */
function revealComposer(frames = 10) {
  const el = document.querySelector<HTMLElement>("[data-slot=change-composer]");
  if (!el) { if (frames > 0) requestAnimationFrame(() => revealComposer(frames - 1)); return; }
  el.scrollIntoView?.({ block: "start", behavior: "smooth" });
  el.querySelector<HTMLInputElement>("input:not(:disabled)")?.focus({ preventScroll: true });
}

function Control({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  const [search, setSearch] = useSearchParams();
  const { timezone } = useOrgClock();
  // v10 (F30-I09): the timeline is the tab; the composer, month budget and manual handoff live in the fold
  // 「進階：自己建一份變更」. A link that lands on something inside it (a set, a recommendation or material copy to
  // compose from, an unsent save) opens it.
  const [advancedOpen, setAdvancedOpen] = useState(() => ["change", "review", "material_copy"].some(key => search.has(key)));
  const storageKey = `ads-change-operation:${getOrgId()}:${brandId}:${campaignId}`;
  const [pending, setPending] = useState<ChangeDraft | null>(() => {
    try { const raw = sessionStorage.getItem(storageKey); return raw ? JSON.parse(raw) as ChangeDraft : null; } catch { return null; }
  });
  const [data, setData] = useState<ChangeControlData | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(search.get("change"));
  const [composing, setComposing] = useState(Boolean(pending));
  const [supersedesId, setSupersedesId] = useState<string | undefined>(pending?.supersedes_id);
  const [initialDraft, setInitialDraft] = useState<Omit<ChangeDraft, "operation_id">>();
  const loadedRecommendation = useRef<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [budgetRefresh, setBudgetRefresh] = useState(0);
  // The handoff below may list launch items even when this campaign has no change targets yet; the empty
  // state speaks only when neither has anything to verify.
  const [handoffWork, setHandoffWork] = useState(false);
  // F49-I14 (Contract D): why there is no platform object to change yet, from the handoff read (origin-aware: a draft
  // not on a platform says so; otherwise the structure was not read yet). Null when destinations exist.
  const [destinationsNote, setDestinationsNote] = useState<string | null>(null);
  const noTargetsReason = destinationsNote ?? "這個活動在平台上還沒有讀到可改的廣告或投放組";
  const lifetime = useRef(new AbortController());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  useEffect(() => {
    const controller = new AbortController(); setError("");
    getChangeControl(brandId, campaignId, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      setData(value); setSelectedId(previous => value.change_sets.some(set => set.id === previous) ? previous : value.change_sets[0]?.id ?? null);
    }).catch(() => { if (!controller.signal.aborted) setError("變更清單暫時讀取不到。請重新讀取，先不要重做平台操作。"); });
    return () => controller.abort();
  }, [brandId, campaignId, reload]);
  const reviewId = search.get("review"), recommendationId = search.get("recommendation");
  const materialParam = search.get("material_copy"), changeParam = search.get("change");
  useEffect(() => { if (composing || pending || (reviewId && recommendationId) || materialParam || changeParam) setAdvancedOpen(true); }, [composing, pending, reviewId, recommendationId, materialParam, changeParam]);
  useEffect(() => {
    const recommendationKey = `${reviewId}:${recommendationId}`;
    if (!reviewId || !recommendationId || pending || loadedRecommendation.current === recommendationKey) return;
    const controller = new AbortController();
    getReview(brandId, campaignId, reviewId, controller.signal).then(review => {
      if (controller.signal.aborted) return;
      const item = review.result_json.recommendations?.find(row => row.id === recommendationId);
      if (item?.recommendation !== "adjust" || !item.suggested_copy || !(item.suggested_copy.body || item.suggested_copy.title) || !["ready", "completed"].includes(review.status)) { setError("這份建議目前不能建立文案變更，請回到成效檢討確認最新結果。"); return; }
      loadedRecommendation.current = recommendationKey;
      setInitialDraft({ title: `${review.evidence_json.target.name ?? "廣告"}文案測試`, month: currentBudgetMonth(timezone), review_id: review.id, recommendation_id: item.id, items: [{ kind: "copy", target_id: item.target_id, after: item.suggested_copy, reason: item.hypothesis }] });
      setSupersedesId(undefined); setComposing(true);
    }).catch(() => { if (!controller.signal.aborted) setError("檢討建議尚未讀取完成，請回到成效頁重新查看。"); });
    return () => controller.abort();
  }, [brandId, campaignId, reviewId, recommendationId, pending, timezone]);
  const materialId = materialParam;
  useEffect(() => {
    if (!materialId || pending || !data || loadedRecommendation.current === `material:${materialId}`) return;
    const controller = new AbortController();
    getMaterialTask(brandId, campaignId, materialId, controller.signal).then(({ task }) => {
      if (controller.signal.aborted) return;
      const after = { ...(task.copy_fields.headline ? { title: task.copy_fields.headline } : {}), ...(task.copy_fields.body ? { body: task.copy_fields.body } : {}) };
      if (task.mode !== "copy" || !Object.keys(after).length) { setError("這份素材需求尚未保存可用文案，請回到素材頁選定版本。"); return; }
      loadedRecommendation.current = `material:${materialId}`;
      const sourceTarget = task.review_context?.entity_id;
      setInitialDraft({ title: `${task.title}（原廣告文案）`, month: currentBudgetMonth(timezone), material_task_id: task.id, material_revision: task.revision, items: [{ kind: "copy", target_id: typeof sourceTarget === "string" ? sourceTarget : data.targets.find(row => row.native_kind === "ad")?.id ?? "", after, reason: task.instruction || "測試這份已保存的文案方向，圖片保持不變。" }] });
      setSupersedesId(undefined); setComposing(true);
    }).catch(() => { if (!controller.signal.aborted) setError("素材版本尚未讀取完成，請回素材頁核對已保存的內容。"); });
    return () => controller.abort();
  }, [brandId, campaignId, materialId, pending, data, timezone]);
  function update(set: ChangeSet) {
    setData(previous => previous ? { ...previous, change_sets: [set, ...previous.change_sets.filter(row => row.id !== set.id)] } : previous);
    select(set.id); setBudgetRefresh(value => value + 1);
  }
  function select(id: string) {
    setSelectedId(id);
    setSearch(previous => { const next = new URLSearchParams(previous); next.set("change", id); next.delete("review"); next.delete("recommendation"); next.delete("material_copy"); return next; }, { replace: true });
  }
  async function mutate(task: (signal: AbortSignal) => Promise<ChangeSet>) {
    if (busy) return;
    const signal = lifetime.current.signal; setBusy(true); setError("");
    try { const result = await task(signal); if (!signal.aborted) update(result); }
    catch (err) { if (!signal.aborted) setError(err instanceof Error ? err.message : "結果尚未確認。請重試核對，不要重做平台操作。"); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  async function save(value: Omit<ChangeDraft, "operation_id">) {
    const source = initialDraft ?? (supersedesId ? data?.change_sets.find(row => row.id === supersedesId) : undefined);
    const request = pending ?? { ...value, operation_id: crypto.randomUUID(), ...(supersedesId ? { supersedes_id: supersedesId } : {}), ...(source?.material_task_id && source?.material_revision ? { material_task_id: source.material_task_id, material_revision: source.material_revision } : {}), ...(source?.review_id && source?.recommendation_id ? { review_id: source.review_id, recommendation_id: source.recommendation_id } : {}) };
    setPending(request); sessionStorage.setItem(storageKey, JSON.stringify(request));
    await mutate(async signal => {
      let result;
      try { result = await createChangeSet(brandId, campaignId, request, signal); }
      catch (err) {
        if (!signal.aborted && err instanceof ChangeRequestRejected) { sessionStorage.removeItem(storageKey); setPending(null); }
        throw err;
      }
      if (!signal.aborted) { sessionStorage.removeItem(storageKey); setPending(null); setInitialDraft(undefined); setComposing(false); }
      return result;
    });
  }
  const selected = data?.change_sets.find(set => set.id === selectedId);
  async function reconsider() {
    if (!selected || busy) return;
    const signal = lifetime.current.signal; setBusy(true); setError("");
    try {
      const fresh = await getChangeControl(brandId, campaignId, signal);
      if (signal.aborted) return;
      setData(fresh);
      const original = fresh.change_sets.find(set => set.id === selected.id);
      if (!original || original.can_revise !== true) {
        setError("原清單仍有操作尚未核對，或相關證據已過期。請先逐項讀回，再修改未完成項目。"); return;
      }
      setInitialDraft(undefined); setSupersedesId(original.id); setComposing(true);
    } catch (err) { if (!signal.aborted) setError(err instanceof Error ? err.message : "目前設定尚未讀取完成，請稍後再試。"); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  function openInFold(row: TimelineRow) {
    if (data?.change_sets.some(set => set.id === row.change_set_id)) { select(row.change_set_id); setComposing(false); }
    setAdvancedOpen(true);
    // A launch is checked item by item in the manual handoff; any other set is its own view at the top of the fold.
    const anchor = row.version !== null ? "manual-handoff" : "changes-advanced";
    scrollWhenShown(anchor);
  }
  const inFold = (row: TimelineRow) => {
    if (row.version !== null) return true;
    const set = data?.change_sets.find(item => item.id === row.change_set_id);
    return set ? !flowRenders(set) : false;
  };
  return <div className="space-y-4">
    <ChangesTab brandId={brandId} campaignId={campaignId} refreshKey={budgetRefresh} inFold={inFold} onOpenInFold={openInFold} />
    <Disclosure label="進階：自己建一份變更" open={advancedOpen} onOpenChange={setAdvancedOpen}><div id="changes-advanced" className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><p className="text-sm text-muted-foreground">確認清單 → 手動操作平台 → 逐項讀回。每一步都保留證據。</p>{data && !composing && <div className="flex flex-col items-end gap-1"><Button variant="outline" disabled={busy || data.targets.length === 0} disabledReason={!busy && data.targets.length === 0 ? noTargetsReason : undefined} onClick={() => { setInitialDraft(undefined); setSupersedesId(undefined); setComposing(true); revealComposer(); }}>建立變更清單</Button></div>}</div>
    <MonthlyBudgetPanel brandId={brandId} month={selected?.month ?? currentBudgetMonth(timezone)} refresh={budgetRefresh} compact />
    {error && <div role="alert" className="rounded-md bg-destructive/5 p-3 text-sm space-y-2"><p className="text-destructive">{error}</p><Button variant="outline" size="sm" disabled={busy} onClick={() => setReload(value => value + 1)}>重新讀取清單</Button></div>}
    {!data && !error && <p role="status" className="surface p-6 text-sm text-muted-foreground">正在讀取清單與平台對象…</p>}
    {data && composing && <><p className="text-sm text-muted-foreground">{initialDraft?.review_id ? "已承接上一輪判讀；文案仍是待驗假設，可調整後再核准。" : ""}</p><ChangeComposer key={initialDraft?.material_task_id ?? initialDraft?.review_id ?? supersedesId ?? "new"} targets={data.targets} month={currentBudgetMonth(timezone)} pending={pending} initialDraft={initialDraft} initial={supersedesId ? data.change_sets.find(set => set.id === supersedesId) : undefined} busy={busy} onSave={value => void save(value)} onClose={() => setComposing(false)} /></>}
    {data && !composing && selected && <ChangeSetView key={selected.id + selected.status} set={selected} busy={busy}
      onApprove={() => void mutate(signal => approveChangeSet(brandId, campaignId, selected, signal))}
      onDecision={value => void mutate(signal => decideChangeSet(brandId, campaignId, selected.id, value, signal))}
      onItem={(item, action) => void mutate(signal => actOnChangeItem(brandId, campaignId, selected.id, item.id, action, signal))}
      onReconsider={() => void reconsider()} />}
    {data && !composing && !selected && !handoffWork && <EmptyState title={data.targets.length ? "先整理這次需要調整的內容" : "還沒有可核對的廣告對象"} description={data.targets.length ? "可只修改文案、調整預算或暫停指定對象。保存清單後再一次核准。" : noTargetsReason} {...(data.targets.length ? { actionLabel: "建立變更清單", onAction: () => { setComposing(true); revealComposer(); } } : {})} />}
    {!composing && <div id="manual-handoff"><ManualHandoffPanel brandId={brandId} campaignId={campaignId} mode="items" refreshKey={budgetRefresh} onHandoffWork={setHandoffWork} onDestinationsNote={setDestinationsNote} /></div>}
    {data && data.change_sets.length > 1 && <Disclosure label={`其他清單與歷史紀錄（${data.change_sets.length - 1}）`}><div className="space-y-2">{data.change_sets.filter(set => set.id !== selectedId).map(set => <button key={set.id} className="flex w-full items-center justify-between rounded-md border border-border p-3 text-left text-sm hover:bg-muted" disabled={busy || Boolean(pending)} onClick={() => { select(set.id); setComposing(false); }}><span>{set.title}</span><span className="text-xs text-muted-foreground">{new Date(set.created_at).toLocaleDateString("zh-TW")}</span></button>)}</div></Disclosure>}
    </div></Disclosure>
  </div>;
}
export function ChangeControl(props: Parameters<typeof Control>[0]) {
  return <Control key={`${getOrgId()}:${props.brandId}:${props.campaignId}`} {...props} />;
}
