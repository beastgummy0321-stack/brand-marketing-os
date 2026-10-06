import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, Clock, RefreshCw, Sparkles } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { EmptyState } from "@/components/layout/EmptyState";
import { getOrgId } from "@/lib/auth";
import { createReview, decideReview, getReview, getReviews, type ReviewRound, type ReviewsData, type ReviewStatus } from "@/lib/adsReviewApi";
import { formatInstant, useOrgClock, type OrgClock } from "@/lib/orgClock";
import { ReviewEvidence } from "./ReviewEvidence";
import { ReviewTracking } from "./ReviewTracking";
import { Disclosure, useAdsRules } from "./patterns";

const labels: Record<ReviewStatus, string> = { waiting: "資料不足，等待補齊", queued: "已安排檢討", running: "正在整理建議", ready: "建議已備妥", completed: "本次檢討完成", deferred: "本次檢討暫緩", unjudgeable: "本次無法判定", failed: "本次未完成", unknown: "結果尚未確認" };
const directions = { retain: "保留現有投放", observe: "先觀察，再決定", adjust: "調整後繼續觀察", new_test: "準備下一個測試" };
const evidenceLabels: Record<string, string> = { current: "本期單則廣告資料", previous: "前期單則廣告資料", conditions: "投放條件與素材歷史", campaign: "活動目標", "commerce.current": "本期商城與通路證據", "commerce.previous": "前期商城與通路證據", previous_review: "上一輪判讀與操作結果", source_review: "新測試承接的原廣告判讀" };
// F36-I09 (ruling G): the observation window ends on the org's yesterday, not the browser's.
function defaults(clock: OrgClock) {
  return { start: clock.shift(-7), end: clock.shift(-1) };
}
function Panel({ brandId, campaignId, onGoal }: { brandId: string; campaignId: string; onGoal: () => void }) {
  const [params, setParams] = useSearchParams();
  const clock = useOrgClock();
  // F50 Contract I (decision 11): the observation range and the cadence default are served; while the rules load the
  // sentences print without the number.
  const limits = useAdsRules()?.limits ?? null;
  const requestedReview = params.get("review");
  const [data, setData] = useState<ReviewsData | null>(null);
  const [selected, setSelected] = useState<string | null>(params.get("review"));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [form, setForm] = useState(false);
  const [target, setTarget] = useState("");
  const [period, setPeriod] = useState(() => defaults(clock));
  const [previousId, setPreviousId] = useState<string>();
  const [decision, setDecision] = useState<"completed" | "deferred" | "unjudgeable" | null>(null);
  const [reason, setReason] = useState("");
  const [revisit, setRevisit] = useState("");
  const lifetime = useRef(new AbortController());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  useEffect(() => {
    const controller = new AbortController();
    getReviews(brandId, campaignId, controller.signal).then(async value => {
      if (requestedReview && !value.reviews.some(row => row.id === requestedReview)) {
        const linked = await getReview(brandId, campaignId, requestedReview, controller.signal);
        value = { ...value, reviews: [linked, ...value.reviews] };
      }
      if (controller.signal.aborted) return;
      setData(value); setSelected(current => requestedReview ?? (value.reviews.some(row => row.id === current) ? current : value.reviews[0]?.id ?? null));
      setTarget(current => value.targets.some(row => row.id === current) ? current : value.targets[0]?.id ?? "");
      setError("");
    }).catch(() => { if (!controller.signal.aborted) setError("本次檢討暫時讀取不到，請重新讀取。不要重做平台操作。"); });
    return () => controller.abort();
  }, [brandId, campaignId, reload, requestedReview]);
  const review = data?.reviews.find(row => row.id === selected);
  const pollingId = review?.id, pollingStatus = review?.status;
  useEffect(() => {
    if (!pollingId || !pollingStatus || !["queued", "running"].includes(pollingStatus)) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await getReview(brandId, campaignId, pollingId!, controller.signal);
        if (controller.signal.aborted) return;
        setData(current => current ? { ...current, reviews: current.reviews.map(row => row.id === result.id ? result : row) } : current);
        if (["queued", "running"].includes(result.status)) timer = setTimeout(() => void poll(), 2500);
      } catch { if (!controller.signal.aborted) setError("尚未讀到最新進度。背景工作可能仍在進行，請重新讀取，無需再次產生建議。"); }
    }
    timer = setTimeout(() => void poll(), 1500);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [brandId, campaignId, pollingId, pollingStatus]);
  function show(id: string) {
    setSelected(id); setForm(false); setDecision(null);
    setParams(previous => { const next = new URLSearchParams(previous); next.set("review", id); return next; }, { replace: true });
  }
  async function mutate(task: (signal: AbortSignal) => Promise<ReviewRound>) {
    if (busy) return;
    const signal = lifetime.current.signal; setBusy(true); setError("");
    try {
      const result = await task(signal);
      if (signal.aborted) return;
      setData(current => current ? { ...current, reviews: [result, ...current.reviews.filter(row => row.id !== result.id)] } : current);
      show(result.id);
    } catch (err) { if (!signal.aborted) setError(err instanceof Error ? err.message : "結果尚未確認，請先重新讀取。"); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  function next() {
    const range = defaults(clock);
    if (review && review.window_end >= range.end) {
      setError("目前還沒有晚於本次觀察期的完整日期。請待新的資料到齊後準備下一輪；補齊原期間資料可使用「重新檢查本期資料」。"); return;
    }
    setPreviousId(review?.id); setTarget(review?.entity_id ?? target); setPeriod(range); setForm(true);
  }
  function another() {
    const reviewed = new Set(data?.reviews.map(row => row.entity_id));
    setPreviousId(undefined); setTarget(data?.targets.find(row => !reviewed.has(row.id))?.id ?? target); setPeriod(defaults(clock)); setError(""); setForm(true);
  }
  function refreshCurrent() {
    if (!review) return;
    void mutate(signal => createReview(brandId, campaignId, { entity_id: review.entity_id, start: review.window_start, end: review.window_end, ...(review.previous_id ? { previous_id: review.previous_id } : {}) }, signal));
  }
  async function saveDecision() {
    if (!review || !decision || !reason.trim()) return;
    // F50 Contract K: a deferral is an org calendar date after the org's today (string compare on `YYYY-MM-DD`).
    if (decision === "deferred" && !(revisit > clock.today)) { setError("暫緩請選明天或之後的日期。"); return; }
    await mutate(signal => decideReview(brandId, campaignId, review.id, { decision, reason: reason.trim(), ...(decision === "deferred" ? { revisit_on: revisit } : {}) }, signal));
  }
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-semibold">{review ? "本次廣告檢討" : "開始第一次檢討"}</h2><p className="mt-1 text-sm text-muted-foreground">先看證據，再決定保留、觀察或調整。活動與檢討分開持續追蹤。</p></div>{review && !form && <div className="flex flex-wrap gap-2">{data && data.targets.length > 1 && <Button variant="outline" busy={busy} onClick={another}>檢討另一則廣告</Button>}<Button variant="outline" busy={busy} onClick={next}>準備下一次檢討</Button></div>}</div>
    {error && <div role="alert" className="rounded-md bg-destructive/5 p-3 text-sm"><p>{error}</p><Button className="mt-2" variant="outline" size="sm" busy={busy} onClick={() => setReload(value => value + 1)}>重新讀取檢討</Button></div>}
    {!data && !error && <p role="status" className="surface p-6 text-sm text-muted-foreground">正在讀取廣告與檢討紀錄…</p>}
    {data && !data.targets.length && <EmptyState title="先帶入正在投放的廣告" description="需要已讀回的平台廣告與成效，才能開始判讀。已有成品可以直接使用，不必重新生圖。" />}
    {data && data.targets.length > 0 && (form || !review) && <section className="surface" aria-label="檢討範圍">
      <div className="surface-header"><h3 className="font-semibold">這次先看哪則廣告</h3><p className="mt-1 text-sm text-muted-foreground">沿用已讀取的設定與報表；你只需要選擇觀察對象。</p></div>
      <div className="surface-body space-y-4"><label className="block text-sm">廣告<select aria-label="檢討廣告" className="mt-1 w-full" value={target} disabled={busy || Boolean(previousId)} onChange={event => setTarget(event.target.value)}>{data.targets.map(row => <option key={row.id} value={row.id}>{row.name ?? row.native_id} · {row.platform} · {row.source_account}</option>)}</select></label>
        <p className="text-sm">觀察期間：{period.start} — {period.end}{previousId ? " · 承接上一輪判讀與操作紀錄" : ""}</p>
        <Disclosure label="調整觀察期間"><div className="grid grid-cols-2 gap-3"><label className="text-sm">開始日期<Input type="date" value={period.start} disabled={busy} onChange={event => setPeriod(value => ({ ...value, start: event.target.value }))} /></label><label className="text-sm">結束日期<Input type="date" value={period.end} disabled={busy} onChange={event => setPeriod(value => ({ ...value, end: event.target.value }))} /></label></div><p className="mt-2 text-xs text-muted-foreground">{limits ? `一次最多 ${limits.review_days.max} 天；` : ""}後端依組織日期確認範圍，成效仍標示來源帳戶的時區。</p></Disclosure>
        {data.targets_truncated && <p className="text-sm text-warning">目前只載入部分廣告；未顯示的廣告尚未納入這次檢討。</p>}
        <div className="flex flex-wrap gap-2"><Button busy={busy} disabledReason={!target ? "先選擇要檢討的廣告" : !period.start || !period.end ? "先填寫觀察期間的開始日與結束日" : undefined} onClick={() => void mutate(signal => createReview(brandId, campaignId, { entity_id: target, ...period, ...(previousId ? { previous_id: previousId } : {}) }, signal))}>{busy ? "保存中…" : "開始本次檢討"}</Button>{review && <Button variant="outline" onClick={() => setForm(false)} busy={busy}>返回本次檢討</Button>}</div>
        <p className="text-xs text-muted-foreground">開始後預設{limits ? `每 ${limits.review_cadence_default} 天` : "定期"}自動檢查這則廣告，可在追蹤設定暫停或調整。資料不足先等待補齊，相同證據不重複請 AI 分析；已存在的設定沿用。</p>
      </div>
    </section>}
    {review && !form && <>
      <section className="surface"><div className="surface-body pt-4 flex flex-wrap items-start justify-between gap-3"><div><Badge variant="outline">{labels[review.status] ?? "狀態待確認"}</Badge><p className="mt-2 text-sm">{review.reason ?? "檢討結論與每項平台操作分開記錄；完成檢討不會停止投放。"}</p>{review.revisit_at && <p className="mt-1 text-sm text-muted-foreground">重看日期：{formatInstant(review.revisit_at, clock.timezone, "ymd")}</p>}</div>{["queued", "running"].includes(review.status) && <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><RefreshCw className="size-4 animate-spin" />背景工作已保存，可稍後回來查看。</p>}</div></section>
      {review.evidence_json.waiting_reasons.length > 0 && <section className="rounded-lg border border-warning/30 bg-warning/10 p-4"><h3 className="font-semibold">先補齊判讀依據</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{review.evidence_json.waiting_reasons.map((value, index) => <li key={index}>{value}</li>)}</ul><div className="mt-3 flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={onGoal}>檢視活動目標</Button><Link className="inline-flex items-center text-sm text-primary" to={`/brands/${brandId}/orders`}>補齊商城報表</Link><Button variant="outline" size="sm" busy={busy} onClick={refreshCurrent}>重新檢查本期資料</Button></div></section>}
      {review.error && <p role="alert" className="rounded-md bg-warning/10 p-3 text-sm">{review.error} 本次未自動重新呼叫 AI，原證據仍保留。</p>}
      {review.result_json.recommendations && review.result_json.recommendations.length > 0 && <section className="surface" aria-label="本次建議"><div className="surface-header"><div className="flex items-center gap-2"><Sparkles className="size-5 text-primary" /><h3 className="font-semibold">本次建議</h3></div></div><div className="surface-body space-y-4">{review.result_json.recommendations?.map(item => <article key={item.id} className="rounded-lg border border-border p-4 space-y-3"><div><Badge variant="secondary">{directions[item.recommendation]}</Badge><h4 className="mt-2 font-medium">{item.hypothesis}</h4><p className="mt-2 text-sm text-muted-foreground">{item.next_step}</p></div>{item.recommendation === "adjust" && (item.suggested_copy?.body || item.suggested_copy?.title) && ["ready", "completed"].includes(review.status) && <Link className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground" to={`?tab=changes&review=${encodeURIComponent(review.id)}&recommendation=${encodeURIComponent(item.id)}`}>只改文案，保留圖片<ArrowRight className="size-4" /></Link>}{item.recommendation === "new_test" && ["ready", "completed"].includes(review.status) && <Link className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground" to={`?tab=assets&material_new=1&review=${encodeURIComponent(review.id)}&recommendation=${encodeURIComponent(item.id)}`}>準備下一輪素材<ArrowRight className="size-4" /></Link>}<Disclosure label="查看建議依據與風險"><div className="space-y-2 text-sm">{item.evidence_refs.map(ref => <p key={ref}>{evidenceLabels[ref] ?? review.evidence_json.sources.find(source => `source:${source.id}` === ref)?.text ?? "來源待核對"}</p>)}{item.risks.map((risk, index) => <p className="text-warning" key={index}>{risk}</p>)}</div></Disclosure></article>)}</div></section>}
      <ReviewEvidence key={review.id} review={review} brandId={brandId} campaignId={campaignId} />
      {!["queued", "running", "completed"].includes(review.status) && <section className="surface p-4 space-y-3"><div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-semibold">決定本次檢討的下一步</h3><p className="mt-1 text-xs text-muted-foreground">暫緩或無法判定，都不會停止平台花費。</p></div><div className="flex flex-wrap gap-2">{review.status === "ready" && <Button busy={busy} onClick={() => { setDecision("completed"); setReason("已檢視本次證據與建議；平台操作依變更清單另外核對。"); }}>完成本次檢討</Button>}<Button variant="outline" busy={busy} onClick={() => { setDecision("deferred"); setReason(""); }}>暫緩本次檢討</Button><Button variant="outline" busy={busy} onClick={() => { setDecision("unjudgeable"); setReason(""); }}>記錄無法判定</Button></div></div>
        {decision && <div className="rounded-md bg-muted p-3 space-y-3"><label className="block text-sm">原因與後續處理<Textarea value={reason} onChange={event => setReason(event.target.value)} /></label>{decision === "deferred" && <label className="block text-sm">下次重看日期<Input type="date" min={clock.shift(1)} value={revisit} onChange={event => setRevisit(event.target.value)} /></label>}<div className="flex gap-2"><Button busy={busy} disabledReason={!reason.trim() ? "請填寫檢討決定的原因" : undefined} onClick={() => void saveDecision()}>保存檢討決定</Button><Button variant="outline" busy={busy} onClick={() => setDecision(null)}>取消</Button></div></div>}
      </section>}
    </>}
    {data && data.targets.length > 0 && <ReviewTracking brandId={brandId} campaignId={campaignId} entityId={review?.entity_id ?? target} refreshKey={`${review?.id}:${review?.status}:${reload}`} />}
    {data && data.reviews.length > 1 && <Disclosure label="其他檢討與歷史紀錄"><div className="space-y-2">{data.reviews.filter(row => row.id !== selected).map(row => <Button variant="ghost" key={row.id} className="flex h-auto w-full items-center justify-between gap-3 whitespace-normal rounded-md border border-border p-3 text-left text-sm hover:bg-muted" busy={busy} onClick={() => show(row.id)}><span>{row.evidence_json.target.name ?? "平台廣告"} · {row.window_start} — {row.window_end}</span><span className="flex items-center gap-1 text-xs text-muted-foreground"><Clock className="size-3" />{labels[row.status]}</span></Button>)}</div>{data.reviews_truncated && <p className="mt-2 text-xs text-muted-foreground">目前顯示最近的檢討紀錄。</p>}</Disclosure>}
  </div>;
}
export function ReviewPanel(props: Parameters<typeof Panel>[0]) { return <Panel key={`${getOrgId()}:${props.brandId}:${props.campaignId}`} {...props} />; }
