import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { getCampaign, patchCampaign, type CampaignDetail, type PatchCampaignInput } from "@/lib/adsApi";
import { attachUpload, type AssetUpload } from "@/lib/adsUserAssetsApi";
import { createCampaignFromPicks, getWizardOptions } from "@/lib/adsWizardApi";
import { useApiRead } from "@/lib/useApiRead";
import { UserAssetsLibrary } from "./UserAssetsLibrary";
import { clearDraft, readDraft, saveDraft } from "./campaignDraft";
import { ActionBar, Disclosure, FlowHeader, MoneyInput, PickCard, PickGroup, ReadFailed } from "./patterns";
import { ObjectiveIcon, ProductPickCard, UnderstandingView, wizardSteps } from "./wizard/WizardPieces";

const message = (err: unknown, fallback: string) => (err instanceof Error && err.message ? err.message : fallback);

/** The picks a created campaign already holds, for going back to step 1 without creating a second campaign.
 * Dates the system filled in are not shown as the user's (they stay empty here). */
function picksOf(c: CampaignDetail) {
  const ctx = (c.context_json ?? {}) as { product_ids?: string[]; field_sources?: { dates?: string } };
  const cons = (c.constraints_json ?? {}) as { budget?: unknown };
  const userDates = ctx.field_sources?.dates === "user";
  return {
    productId: ctx.product_ids?.[0] ?? null,
    objective: c.objective || null,
    startDate: userDates ? c.start_date ?? "" : "",
    endDate: userDates ? c.end_date ?? "" : "",
    budget: typeof cons.budget === "number" && Number.isFinite(cons.budget) && cons.budget > 0 ? cons.budget : null,
  };
}

/** New-campaign wizard v10 step 1 (F30-I05, prototype `newStep1()`): pick one product and one objective from the
 * catalog, the dates and 「這個活動最多花」, then `createCampaignFromPicks` understands them (one synchronous model
 * call) while step 2's wait line shows, and lands on step 2 (`ConfirmBriefPage`). `?created=<id>` is the campaign
 * this tab already created: its picks reload, a change is a `PATCH`, never a second campaign. The optional sentence
 * and the brand's own images／videos sit folded under 進階. */
export function NewCampaignPage({ brandId }: { brandId: string }) {
  const { scope } = useWorkspace();
  const draftKey = `campaign-draft:${scope}:${brandId}`;
  return <CampaignWizard key={draftKey} brandId={brandId} draftKey={draftKey} />;
}

function CampaignWizard({ brandId, draftKey }: { brandId: string; draftKey: string }) {
  const navigate = useNavigate();
  const homeHref = `/brands/${brandId}/ads`;
  const [search, setSearch] = useSearchParams();
  const createdId = search.get("created");
  const life = useRef(new AbortController());
  useEffect(() => { life.current = new AbortController(); return () => life.current.abort(); }, []);
  const options = useApiRead(() => getWizardOptions(brandId), [brandId]);

  const [initial] = useState(() => readDraft(draftKey));
  const [productId, setProductId] = useState(initial.productId);
  const [objective, setObjective] = useState(initial.objective);
  const [startDate, setStartDate] = useState(initial.startDate);
  const [endDate, setEndDate] = useState(initial.endDate);
  const [budget, setBudget] = useState(initial.budget);
  const [goalText, setGoalText] = useState(initial.goalText);
  const [uploads, setUploads] = useState<AssetUpload[]>([]);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [attached, setAttached] = useState<Set<string>>(new Set());
  const [created, setCreated] = useState<CampaignDetail | null>(null);
  const [restoring, setRestoring] = useState(!!createdId);
  const [restoreFailed, setRestoreFailed] = useState<string | null>(null);
  const [restoreKey, setRestoreKey] = useState(0);
  const [phase, setPhase] = useState<"pick" | "understanding" | "failed">("pick");
  const [failure, setFailure] = useState<string | null>(null);
  const [waited, setWaited] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!createdId || created?.id === createdId) { setRestoring(false); return; }
    let cancelled = false;
    setRestoring(true); setRestoreFailed(null);
    getCampaign(brandId, createdId)
      .then((c) => {
        if (cancelled) return;
        const p = picksOf(c);
        setCreated(c); setProductId(p.productId); setObjective(p.objective);
        setStartDate(p.startDate); setEndDate(p.endDate); setBudget(p.budget);
      })
      .catch((e) => { if (!cancelled) setRestoreFailed(message(e, "讀取已建立的活動失敗。")); })
      .finally(() => { if (!cancelled) setRestoring(false); });
    return () => { cancelled = true; };
  }, [brandId, createdId, created?.id, restoreKey]);
  useEffect(() => {
    saveDraft(draftKey, { productId, objective, startDate, endDate, budget, goalText });
  }, [draftKey, productId, objective, startDate, endDate, budget, goalText]);
  useEffect(() => {
    if (phase !== "understanding") return;
    setWaited(0);
    const started = Date.now();
    const timer = setInterval(() => setWaited(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [phase]);

  const data = options.data;
  const product = data?.products.find((p) => p.id === productId) ?? null;
  const goal = data?.objectives.find((o) => o.key === objective && o.available) ?? null;
  const oneDate = !!startDate !== !!endDate;
  const backwards = !!startDate && !!endDate && endDate < startDate;
  const budgetOk = budget !== null && budget > 0;
  const hint = !product || !goal ? "選好商品和結果"
    : !budgetOk ? "填這個活動最多花"
    : oneDate ? "開始和結束要一起填"
    : backwards ? "結束要在開始之後" : "";
  const blocked = !!hint || busy || uploadBusy || restoring || (!!createdId && !created);

  /** Attaches the picked uploads not yet attached; returns the failures (the campaign is never re-created). */
  async function attachAll(campaignId: string, signal: AbortSignal) {
    const done = new Set(attached);
    const errors: string[] = [];
    for (const upload of uploads) {
      if (signal.aborted) return errors;
      if (done.has(upload.id)) continue;
      try { await attachUpload(brandId, campaignId, upload.id); done.add(upload.id); }
      catch (e) { errors.push(`${upload.filename}：${message(e, "加入失敗")}`); }
    }
    setAttached(done);
    return errors;
  }

  function finish(campaignId: string) {
    clearDraft(draftKey);
    navigate(`/brands/${brandId}/ads/new/${campaignId}`);
  }

  async function submit() {
    if (blocked || !product || !goal || budget === null) return;
    if (uploads.some((u) => u.status !== "complete")) { setError("選取的原檔尚未保存，請重試上傳，或取消該檔選取後繼續。"); return; }
    const signal = life.current.signal;
    setError(null); setBusy(true);
    const dates = startDate && endDate ? { start_date: startDate, end_date: endDate } : {};
    try {
      let campaign = created;
      if (campaign) {
        const now = picksOf(campaign);
        const patch: PatchCampaignInput = {};
        if (product.id !== now.productId) patch.product_ids = [product.id];
        if (goal.key !== campaign.objective) patch.objective = goal.key;
        if (startDate && endDate && (startDate !== campaign.start_date || endDate !== campaign.end_date)) Object.assign(patch, dates);
        if (budget !== now.budget) patch.constraints_json = { ...(campaign.constraints_json ?? {}), budget };
        if (goalText.trim() && goalText.trim() !== campaign.goal_text) patch.goal_text = goalText.trim();
        if (Object.keys(patch).length > 0) campaign = await patchCampaign(brandId, campaign.id, patch);
      } else {
        setPhase("understanding");
        campaign = await createCampaignFromPicks(brandId, {
          product_ids: [product.id], objective: goal.key, budget, ...dates,
          ...(goalText.trim() ? { goal_text: goalText.trim() } : {}),
        });
      }
      if (signal.aborted) return;
      setCreated(campaign);
      const id = campaign.id;
      if (createdId !== id) setSearch((prev) => { const next = new URLSearchParams(prev); next.set("created", id); return next; }, { replace: true });
      const errors = await attachAll(id, signal);
      if (signal.aborted) return;
      if (errors.length) { setPhase("pick"); setError(`活動已建立，未完成素材仍可重試，不會重建活動。${errors.join("；")}`); setBusy(false); return; }
      finish(id);
    } catch (err) {
      if (signal.aborted) return;
      setBusy(false);
      if (created) { setError(message(err, "更新活動失敗，請稍後再試。")); return; }
      setFailure(message(err, "建立活動失敗")); setPhase("failed");
    }
  }

  if (phase !== "pick") {
    return (
      <Shell homeHref={homeHref} bar={
        <ActionBar
          back={<Button variant="ghost" disabled={phase === "understanding"} onClick={() => setPhase("pick")}>← 上一步</Button>}
          hint={phase === "failed" ? "讀取失敗，按上方重試" : undefined}
        >
          <Button disabled>產生策略 →</Button>
        </ActionBar>
      }>
        <UnderstandingView brandId={brandId} failed={phase === "failed" ? failure : null} waitedSeconds={waited} onRetry={() => void submit()} />
      </Shell>
    );
  }

  const locked = busy || restoring;
  return (
    <Shell homeHref={homeHref} bar={
      <ActionBar back={{ label: "投放中心", to: homeHref }} hint={hint || undefined}>
        <Button disabled={blocked} onClick={() => void submit()}>
          {created && error && uploads.some((u) => !attached.has(u.id)) ? "重試加入未完成素材並繼續" : "下一步：系統理解"} →
        </Button>
      </ActionBar>
    }>
      <FlowHeader steps={wizardSteps(brandId)} current={0} title="建立活動" purpose="選商品和目標" />
      {restoreFailed && <ReadFailed what={`已建立的活動讀不到（${restoreFailed}）；不會重建活動`} onRetry={() => setRestoreKey((k) => k + 1)} />}
      {options.status === "error" ? (
        <ReadFailed what={`商品和目標清單讀不到（${options.error}）`} onRetry={options.reload} />
      ) : !data ? (
        <>
          <Skeleton className="h-[170px] w-full rounded-xl" />
          <Skeleton className="h-[226px] w-full rounded-xl" />
        </>
      ) : (
        <>
          <section className="surface" aria-labelledby="new-product">
            <div className="surface-header"><h2 id="new-product">商品</h2></div>
            <div className="surface-body">
              {data.products.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  還沒有可以推的商品。<Link className="text-primary underline-offset-4 hover:underline" to={`/brands/${brandId}/products`}>去新增商品</Link>
                </p>
              ) : (
                <PickGroup label="商品" value={productId} onChange={(v) => !locked && setProductId(v)}>
                  {data.products.map((p) => <ProductPickCard key={p.id} product={p} />)}
                </PickGroup>
              )}
            </div>
          </section>
          <section className="surface" aria-labelledby="new-goal">
            <div className="surface-header"><h2 id="new-goal">想要的結果</h2></div>
            <div className="surface-body">
              <PickGroup label="目標" value={objective} onChange={(v) => !locked && setObjective(v)}>
                {data.objectives.map((o) => (
                  <PickCard key={o.key} value={o.key} title={o.label} note={o.description} icon={<ObjectiveIcon objective={o.key} />} disabled={!o.available} />
                ))}
              </PickGroup>
            </div>
          </section>
        </>
      )}
      <section className="surface" aria-labelledby="new-period">
        <div className="surface-header"><h2 id="new-period">期間與預算上限</h2></div>
        <div className="surface-body flex flex-wrap items-end gap-4">
          <Field id="new-start" label="開始">
            <Input id="new-start" type="date" value={startDate} disabled={locked} onChange={(e) => setStartDate(e.target.value)} className="h-[42px] w-[170px] rounded-lg" />
          </Field>
          <Field id="new-end" label="結束">
            <Input id="new-end" type="date" value={endDate} disabled={locked} onChange={(e) => setEndDate(e.target.value)} className="h-[42px] w-[170px] rounded-lg" />
          </Field>
          <Field id="new-cap" label="這個活動最多花">
            <MoneyInput id="new-cap" value={budget} onChange={setBudget} disabled={locked} onEnter={() => void submit()} />
          </Field>
        </div>
      </section>
      <Disclosure label="進階：補充說明、自帶圖片／影片">
        <div className="flex flex-col gap-4">
          <Field id="new-goal-text" label="補充說明（選填）">
            <Textarea id="new-goal-text" value={goalText} disabled={locked || !!created} maxLength={500} onChange={(e) => setGoalText(e.target.value)} className="min-h-20" />
          </Field>
          <UserAssetsLibrary brandId={brandId} readOnly={busy} onSelection={setUploads} onBusy={setUploadBusy} />
        </div>
      </Disclosure>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </Shell>
  );
}

function Shell({ homeHref, bar, children }: { homeHref: string; bar: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "建立活動" }]} />
      <div className="flex max-w-[1260px] flex-col gap-4 [&>[data-slot=flow-header]]:mb-1">{children}</div>
      <div className="flex-1" />
      {bar}
    </div>
  );
}

function Field({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}
