import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { createCampaign, getCampaign, listCampaigns, patchCampaign, type CampaignDetail, type PatchCampaignInput } from "@/lib/adsApi";
import type { CampaignCreateExtras } from "@/lib/adsCampaignTypes";
import { fetchChannels } from "@/lib/adsLaunchApi";
import { putTarget } from "@/lib/adsTriageApi";
import { attachUpload, type AssetUpload } from "@/lib/adsUserAssetsApi";
import { createCampaignFromPicks, getWizardOptions, type CampaignPicks, type WizardProduct } from "@/lib/adsWizardApi";
import { useApiRead } from "@/lib/useApiRead";
import { UserAssetsLibrary } from "./UserAssetsLibrary";
import { clearDraft, readDraft, saveDraft } from "./campaignDraft";
import { ActionBar, Chip, Disclosure, FlowHeader, MoneyInput, PickCard, PickGroup, ReadFailed, formatAmount } from "./patterns";
import { SellWayPickCard, UnderstandingView, wizardSteps } from "./wizard/WizardPieces";

/** The one-sentence create's 「請 AI 依品牌資料建議」 request (the free-text create path, kept under 進階). */
const BRAND_SUGGESTION_REQUEST = "請依這個品牌已保存的商品、成效目標與資料，建議第一份投放計畫。沿用已知資訊，缺少或未確認的條件請標示待確認，不要假設已有投放成效。";
/** What a create sends: the picks (the wizard's structured create) or one sentence (the free-text create). */
type CreateRequest = { kind: "picks" } | { kind: "sentence"; text: string };

const message = (err: unknown, fallback: string) => (err instanceof Error && err.message ? err.message : fallback);
const fmt = (v: number | null | undefined) => formatAmount(v) ?? "未知";
const md = (d: string) => d.slice(5).replace("-", "/");
const SELECT = "h-[42px] w-full rounded-lg border border-input bg-card px-3 text-sm focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none disabled:bg-muted";
/** `app/ads/brief.py::_draft_name`: only the base is shortened (30 characters + 「…」), the date tail never. */
const NAME_BASE_LIMIT = 30;
const nameBase = (name: string) => { const t = name.trim(); return t.length > NAME_BASE_LIMIT ? `${t.slice(0, NAME_BASE_LIMIT)}…` : t; };

/** The picks a created campaign already holds, for going back to step 1 without creating a second campaign.
 * Dates the system filled in are not shown as the user's (they stay empty here); the fold's audience／cap／landing
 * are the user's only when `field_sources` says so (otherwise they follow the sell-way, `undefined`). */
function picksOf(c: CampaignDetail) {
  const ctx = c.context_json ?? {};
  const cons = (c.constraints_json ?? {}) as { budget?: unknown; platform?: unknown };
  const sources = ctx.field_sources ?? {};
  const groups = ctx.customer_group_ids ?? [];
  return {
    productId: ctx.product_ids?.[0] ?? null,
    objective: c.objective || null,
    startDate: sources.dates === "user" ? c.start_date ?? "" : "",
    endDate: sources.dates === "user" ? c.end_date ?? "" : "",
    budget: typeof cons.budget === "number" && Number.isFinite(cons.budget) && cons.budget > 0 ? cons.budget : null,
    platform: typeof cons.platform === "string" ? cons.platform : null,
    groupPick: sources.audience === "user" && groups.length === 1 ? groups[0] : "",
    cap: sources.cap === "user" ? c.cap?.own_value ?? undefined : undefined,
    landing: sources.landing_url === "user" ? ctx.landing_url ?? "" : undefined,
  };
}

/** F40's period default (kept by F43): the day after the brand's latest non-draft campaign ends, same length. */
async function readPreviousPeriod(brandId: string) {
  const cards = await listCampaigns(brandId);
  const latest = cards.filter((c) => c.status !== "draft").sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  if (!latest?.start_date || !latest.end_date) return null;
  const s = Date.parse(`${latest.start_date}T00:00:00Z`);
  const e = Date.parse(`${latest.end_date}T00:00:00Z`);
  if (!Number.isFinite(s) || !Number.isFinite(e) || e < s) return null;
  const day = 86_400_000;
  const iso = (t: number) => new Date(t).toISOString().slice(0, 10);
  return { start: iso(e + day), end: iso(e + day + (e - s)), prevStart: latest.start_date, prevEnd: latest.end_date };
}

/** Sell-ways in `#/new` order: one section per knowledge product (single sell-ways), then 組合 (bundles). */
function sections(ways: WizardProduct[]) {
  const out: { key: string; title: string; ways: WizardProduct[] }[] = [];
  for (const way of ways) {
    const key = way.kind === "bundle" ? "bundle" : way.knowledge_product_id;
    const section = out.find((s) => s.key === key);
    if (section) section.ways.push(way);
    else out.push({ key, title: way.kind === "bundle" ? "組合" : way.knowledge_product_name, ways: [way] });
  }
  return [...out.filter((s) => s.key !== "bundle"), ...out.filter((s) => s.key === "bundle")];
}

/** New-campaign step 1, slimmed by F43 (prototype f41-onboarding `#/new`): pick what to sell (a sell-way), the
 * result (the brand's conversion goal preselected), the dates and 「這個活動最多花」; platform／audience／cap／landing
 * come from the brand and the sell-way and only change in 「進階：這期不一樣」, which sends a value only when it differs
 * from that default. `createCampaignFromPicks` understands the picks (one synchronous model call) while step 2's
 * wait line shows. `?sell_way=<id>` (from 商品建檔 ⑤) preselects a sell-way; `?created=<id>` is the campaign this
 * tab already created: its picks reload, a change is a `PATCH`, never a second campaign. The optional sentence and
 * the brand's own images／videos stay folded under 「進階：一句話建立、自帶圖片／影片」. */
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
  const sellWayParam = search.get("sell_way");
  const life = useRef(new AbortController());
  useEffect(() => { life.current = new AbortController(); return () => life.current.abort(); }, []);
  const options = useApiRead(() => getWizardOptions(brandId), [brandId]);
  const channels = useApiRead(() => fetchChannels(brandId), [brandId]);

  const [initial] = useState(() => readDraft(draftKey));
  const [productId, setProductId] = useState(initial.productId);
  const [objective, setObjective] = useState(initial.objective);
  const [startDate, setStartDate] = useState(initial.startDate);
  const [endDate, setEndDate] = useState(initial.endDate);
  const [budget, setBudget] = useState(initial.budget);
  const [goalText, setGoalText] = useState(initial.goalText);
  /** 「進階：這期不一樣」: `null`／`""`／`undefined` = not changed (the brand's and the sell-way's value shows and
   * nothing is sent). A cleared cap is `null` and a cleared landing `""` — shown empty, still not sent. */
  const [platform, setPlatform] = useState<string | null>(null);
  const [groupPick, setGroupPick] = useState("");
  const [cap, setCap] = useState<number | null | undefined>(undefined);
  const [landing, setLanding] = useState<string | undefined>(undefined);
  const [previous, setPrevious] = useState<{ start: string; end: string } | null>(null);
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
  const [lastRequest, setLastRequest] = useState<CreateRequest>({ kind: "picks" });
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
        setPlatform(p.platform); setGroupPick(p.groupPick); setCap(p.cap); setLanding(p.landing);
      })
      .catch((e) => { if (!cancelled) setRestoreFailed(message(e, "讀取已建立的活動失敗。")); })
      .finally(() => { if (!cancelled) setRestoring(false); });
    return () => { cancelled = true; };
  }, [brandId, createdId, created?.id, restoreKey]);
  // The period default (F40, kept): only when the draft holds no dates; a read that fails leaves them empty.
  useEffect(() => {
    if (createdId || initial.startDate || initial.endDate) return;
    let cancelled = false;
    readPreviousPeriod(brandId)
      .then((period) => {
        if (cancelled || !period) return;
        setPrevious({ start: period.prevStart, end: period.prevEnd });
        setStartDate((now) => now || period.start); setEndDate((now) => now || period.end);
      })
      .catch(() => { /* No period to follow: the dates stay empty. */ });
    return () => { cancelled = true; };
  }, [brandId, createdId, initial]);
  // Once the options are in: `?sell_way=` picks that sell-way (when it is pickable), and an empty result takes the
  // brand's conversion goal (`default_objective`; null = no preselection). A created campaign keeps its own picks.
  const data = options.data;
  const preset = useRef(false);
  useEffect(() => {
    if (!data || preset.current || createdId) return;
    preset.current = true;
    if (sellWayParam && data.products.some((p) => p.id === sellWayParam)) setProductId(sellWayParam);
    const goalKey = data.default_objective;
    if (goalKey && data.objectives.some((o) => o.key === goalKey && o.available)) setObjective((now) => now ?? goalKey);
  }, [data, createdId, sellWayParam]);
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

  const way = data?.products.find((p) => p.id === productId) ?? null;
  const goal = data?.objectives.find((o) => o.key === objective && o.available) ?? null;
  const oneDate = !!startDate !== !!endDate;
  const backwards = !!startDate && !!endDate && endDate < startDate;
  const budgetOk = budget !== null && budget > 0;
  const hint = !way || !goal ? "選好要推什麼和想要的結果"
    : !budgetOk ? "填這個活動最多花"
    : oneDate ? "開始和結束要一起填"
    : backwards ? "結束要在開始之後" : "";
  const blocked = !!hint || busy || uploadBusy || restoring || (!!createdId && !created);

  // The fold's defaults and what differs from them.
  const defaultPlatform = channels.data?.find((c) => c.connected)?.key ?? null;
  const platformShown = platform ?? defaultPlatform;
  const platformChanged = platform !== null && platform !== defaultPlatform;
  const groups = way?.customer_groups ?? [];
  /** One group of several; anything else (all groups, or a sell-way with one group) is 「都投」, sent as nothing. */
  const groupShown = groups.length > 1 && groups.some((g) => g.id === groupPick) ? groupPick : "";
  const capShown = cap === undefined ? way?.cap_per_sale ?? null : cap;
  const capChanged = cap != null && cap > 0 && cap !== way?.cap_per_sale;
  const landingShown = landing ?? way?.landing_url ?? "";
  const landingChanged = landing !== undefined && !!landing.trim() && landing.trim() !== (way?.landing_url ?? "");
  const breakEven = way?.break_even ?? null;
  const capHint = capShown === null
    ? (way && way.cap_per_sale === null ? "這個賣法還算不出打平；可以自己填" : "")
    : breakEven === null ? ""
      : capShown === breakEven ? `等於打平 ${fmt(breakEven)}`
      : capShown > breakEven ? `比打平 ${fmt(breakEven)} 高 ${fmt(capShown - breakEven)}` : `比打平 ${fmt(breakEven)} 低 ${fmt(breakEven - capShown)}`;
  /** Only the changed fold values go out; the server takes the rest from the brand and the sell-way (F43-I04). */
  const extras: CampaignCreateExtras & Pick<CampaignPicks, "customer_group_ids"> = {
    ...(platformChanged && platform ? { platform } : {}),
    ...(groupShown ? { customer_group_ids: [groupShown] } : {}),
    ...(capChanged && cap != null ? { cap } : {}),
    ...(landingChanged && landing ? { landing_url: landing.trim() } : {}),
  };
  /** Another sell-way brings its own audience, cap and landing: the fold's changes to those go back to its values. */
  function pickWay(id: string) {
    if (id === productId) return;
    setProductId(id); setGroupPick(""); setCap(undefined); setLanding(undefined);
  }

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

  /** A created campaign's `PATCH` (and the cap through the target writer): only what differs from the campaign. */
  async function update(campaign: CampaignDetail, picked: WizardProduct, objectiveKey: string, budgetValue: number) {
    const now = picksOf(campaign);
    const ctx = campaign.context_json ?? {};
    const patch: PatchCampaignInput = {};
    const wayChanged = picked.id !== now.productId;
    if (wayChanged) patch.product_ids = [picked.id];
    if (objectiveKey !== campaign.objective) patch.objective = objectiveKey;
    if (startDate && endDate && (startDate !== campaign.start_date || endDate !== campaign.end_date)) Object.assign(patch, { start_date: startDate, end_date: endDate });
    const platformPatch = platform !== null && platform !== now.platform;
    if (budgetValue !== now.budget || platformPatch) {
      patch.constraints_json = { ...(campaign.constraints_json ?? {}), budget: budgetValue, ...(platformPatch ? { platform } : {}) };
    }
    // A sell-way change without groups resets them on the server; otherwise send the pick when it changed.
    if (wayChanged ? !!groupShown : groupShown !== now.groupPick) patch.customer_group_ids = groupShown ? [groupShown] : [];
    // Landing and cap are written when the user changed them here, or the sell-way changed (its own values then);
    // an untouched field keeps whatever the campaign holds.
    const landingNow = landing?.trim() ? landing.trim() : wayChanged ? picked.landing_url ?? "" : null;
    if (landingNow !== null && landingNow !== (ctx.landing_url ?? "")) patch.landing_url = landingNow || null;
    let out = Object.keys(patch).length > 0 ? await patchCampaign(brandId, campaign.id, patch) : campaign;
    // The cap is not a campaign field: it goes through the target writer (revision-guarded), like step 2.
    const capNow = cap != null && cap > 0 ? cap : wayChanged ? picked.cap_per_sale : null;
    if (capNow !== null && capNow !== out.cap.own_value) {
      await putTarget(brandId, out.id, { basis: "own", value: capNow, expected_revision: out.cap.revision });
      out = await getCampaign(brandId, out.id);
    }
    return out;
  }

  async function submit(request: CreateRequest = { kind: "picks" }) {
    if (request.kind === "picks" && (blocked || !way || !goal || budget === null)) return;
    if (request.kind === "sentence" && (!request.text.trim() || busy || uploadBusy || restoring || !!created || !!createdId || oneDate || backwards)) return;
    if (uploads.some((u) => u.status !== "complete")) { setError("選取的原檔尚未保存，請重試上傳，或取消該檔選取後繼續。"); return; }
    const signal = life.current.signal;
    setError(null); setBusy(true);
    const dates = startDate && endDate ? { start_date: startDate, end_date: endDate } : {};
    setLastRequest(request);
    if (request.kind === "sentence") setGoalText(request.text);
    try {
      let campaign = created;
      if (campaign && way && goal && budget !== null) {
        campaign = await update(campaign, way, goal.key, budget);
      } else if (request.kind === "sentence") {
        setPhase("understanding");
        campaign = await createCampaign(brandId, {
          goal_text: request.text.trim(), ...dates,
          ...(budgetOk ? { constraints: { budget } } : {}), ...(platformChanged && platform ? { platform } : {}),
        });
      } else if (way && goal && budget !== null) {
        setPhase("understanding");
        campaign = await createCampaignFromPicks(brandId, {
          product_ids: [way.id], objective: goal.key, budget, ...dates,
          ...(goalText.trim() ? { goal_text: goalText.trim() } : {}), ...extras,
        });
      }
      if (signal.aborted || !campaign) return;
      setCreated(campaign);
      const id = campaign.id;
      if (createdId !== id) setSearch((prev) => { const next = new URLSearchParams(prev); next.set("created", id); next.delete("sell_way"); return next; }, { replace: true });
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

  const picking = phase === "pick";
  const locked = busy || restoring;
  const nameLine = way && (startDate && endDate && !backwards
    ? <>活動名稱會叫「<b>{nameBase(way.name)}・{md(startDate)}～{md(endDate)}</b>」</>
    : <>活動名稱會叫「<b>{nameBase(way.name)}</b>」加上期間（沒填日期就從今天起算 30 天）</>);
  // The pick view stays mounted (hidden) while the create runs, so the upload library keeps its selection for
  // an attach retry.
  return (
    <Shell homeHref={homeHref} bar={picking ? (
      <ActionBar back={{ label: "投放中心", to: homeHref }} hint={hint || undefined}>
        <Button disabled={blocked} onClick={() => void submit()}>
          {created && error && uploads.some((u) => !attached.has(u.id)) ? "重試加入未完成素材並繼續" : "下一步：系統理解"} →
        </Button>
      </ActionBar>
    ) : (
      <ActionBar
        back={<Button variant="ghost" disabled={phase === "understanding"} onClick={() => setPhase("pick")}>← 上一步</Button>}
        hint={phase === "failed" ? "讀取失敗，按上方重試" : undefined}
      >
        <Button disabled>產生策略 →</Button>
      </ActionBar>
    )}>
      {!picking && <UnderstandingView brandId={brandId} failed={phase === "failed" ? failure : null} waitedSeconds={waited} onRetry={() => void submit(lastRequest)} />}
      <div className={picking ? "contents" : "hidden"}>
      <FlowHeader steps={wizardSteps(brandId)} current={0} title="建立活動" purpose="選要推什麼、推多久、花多少；其他照品牌和商品建檔帶入" />
      {restoreFailed && <ReadFailed what={`已建立的活動讀不到（${restoreFailed}）；不會重建活動`} onRetry={() => setRestoreKey((k) => k + 1)} />}
      {options.status === "error" ? (
        <ReadFailed what={`賣法和目標清單讀不到（${options.error}）`} onRetry={options.reload} />
      ) : !data ? (
        <>
          <Skeleton className="h-[170px] w-full rounded-xl" />
          <Skeleton className="h-[140px] w-full rounded-xl" />
        </>
      ) : (
        <>
          <section className="surface" aria-labelledby="new-product">
            <div className="surface-header"><h2 id="new-product">要推什麼</h2></div>
            <div className="surface-body">
              {data.products.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  還沒有可以推的賣法：商品建完、定好賣法與價格，就能拿來投放。{" "}
                  <Link className="text-primary underline-offset-4 hover:underline" to={`/brands/${brandId}/products/new`}>建第一個商品</Link>
                </p>
              ) : (
                <PickGroup label="要推什麼" value={productId} onChange={(v) => !locked && pickWay(v)} className="flex flex-wrap gap-3">
                  {sections(data.products).map((s, i) => (
                    <div key={s.key} role="presentation" className="contents">
                      <p data-slot="pick-section" className={`basis-full text-xs font-semibold text-muted-foreground ${i > 0 ? "mt-1" : ""}`}>{s.title}</p>
                      {s.ways.map((w) => <SellWayPickCard key={w.id} way={w} />)}
                    </div>
                  ))}
                </PickGroup>
              )}
            </div>
          </section>
          <section className="surface" aria-labelledby="new-goal">
            <div className="surface-header">
              <h2 id="new-goal">想要的結果</h2>
              {data.default_objective && <span className="text-xs text-muted-foreground">預設＝品牌的成效目標</span>}
            </div>
            <div className="surface-body">
              <PickGroup label="想要的結果" value={objective} onChange={(v) => !locked && setObjective(v)} className="flex flex-wrap gap-3 [&>*]:w-[170px]">
                {data.objectives.filter((o) => o.available).map((o) => <PickCard key={o.key} value={o.key} title={o.label} note={o.description} />)}
              </PickGroup>
              {data.objectives.some((o) => !o.available) && (
                <ul aria-label="尚未開放的目標" className="mt-3 flex flex-wrap gap-2">
                  {data.objectives.filter((o) => !o.available).map((o) => (
                    <li key={o.key}><Chip tone="neutral" aria-disabled="true" className="opacity-80">{o.label}・尚未開放</Chip></li>
                  ))}
                </ul>
              )}
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
        {(nameLine || previous) && (
          <div className="surface-body flex flex-col gap-1 pt-0">
            {nameLine && <p data-slot="name-line" className="text-sm">{nameLine}</p>}
            {previous && startDate && <p className="text-xs text-muted-foreground">日期接在上一期後面（上一期 {md(previous.start)}～{md(previous.end)}）</p>}
          </div>
        )}
      </section>
      <Disclosure label="進階：這期不一樣（平台、受眾、每筆上限、落地頁）">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field id="new-platform" label="平台" tag={<Source changed={platformChanged}>{defaultPlatform ? "來自品牌：已接上的帳戶" : "品牌還沒接上帳戶"}</Source>}>
            <select id="new-platform" className={SELECT} value={platformShown ?? ""} disabled={locked || !channels.data} onChange={(e) => setPlatform(e.target.value || null)}>
              {!platformShown && <option value="" disabled>請選擇</option>}
              {(channels.data ?? []).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </Field>
          <Field id="new-audience" label="受眾" tag={way && <Source changed={!!groupShown}>{groups.length ? `來自商品：${groups.length} 群顧客` : "這個商品還沒有顧客群"}</Source>}>
            <select id="new-audience" className={SELECT} value={groupShown} disabled={locked || groups.length <= 1} onChange={(e) => setGroupPick(e.target.value)}>
              <option value="">{!way ? "先選要推什麼" : groups.length ? `${groups.length} 群都投（${groups.map((g) => g.who).join("、")}）` : "還沒有顧客群"}</option>
              {groups.length > 1 && groups.map((g) => <option key={g.id} value={g.id}>只投：{g.who}</option>)}
            </select>
          </Field>
          <Field id="new-sale-cap" label="每筆上限" hint={capHint} tag={way && <Source changed={capChanged}>{`來自賣法「${way.display_name}」`}</Source>}>
            <MoneyInput id="new-sale-cap" value={capShown} onChange={setCap} disabled={locked || !way} placeholder={way ? "例如 450" : "先選要推什麼"} onEnter={() => void submit()} />
          </Field>
          <Field id="new-landing" label="落地頁" hint={landing !== undefined && !landing.trim() && way?.landing_url ? "留空＝用賣法的落地頁" : undefined}
            tag={way && <Source changed={landingChanged}>{`來自賣法「${way.display_name}」`}</Source>}>
            <Input id="new-landing" type="url" value={landingShown} disabled={locked || !way} onChange={(e) => setLanding(e.target.value)}
              placeholder="https://" className="h-[42px] rounded-lg" />
          </Field>
        </div>
        {channels.status === "error" && <div className="pt-3"><ReadFailed what={`平台清單讀不到（${channels.error}）；平台先照品牌已接上的帳戶，其他照常`} onRetry={channels.reload} /></div>}
      </Disclosure>
      <Disclosure label="進階：一句話建立、自帶圖片／影片">
        <div className="flex flex-col gap-4">
          <Field id="new-goal-text" label="你這次想做到什麼？">
            <Textarea id="new-goal-text" value={goalText} disabled={locked || !!created} maxLength={500} onChange={(e) => setGoalText(e.target.value)}
              placeholder="例如：下個月想推主力商品，希望增加購買。" className="min-h-20" />
          </Field>
          {!created && !createdId && (
            <div className="flex flex-wrap gap-2">
              {goalText.trim()
                ? <Button variant="outline" disabled={locked || uploadBusy || oneDate || backwards} onClick={() => void submit({ kind: "sentence", text: goalText })}>產生建議</Button>
                : <Button variant="outline" disabled={locked || uploadBusy || oneDate || backwards} onClick={() => void submit({ kind: "sentence", text: BRAND_SUGGESTION_REQUEST })}>請 AI 依品牌資料建議</Button>}
            </div>
          )}
          <UserAssetsLibrary brandId={brandId} readOnly={busy} onSelection={setUploads} onBusy={setUploadBusy} />
        </div>
      </Disclosure>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      </div>
    </Shell>
  );
}

function Shell({ homeHref, bar, children }: { homeHref: string; bar: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "建立活動" }]} />
      <div className="flex max-w-[1260px] flex-col gap-4 [&_[data-slot=flow-header]]:mb-1">{children}</div>
      <div className="flex-1" />
      {bar}
    </div>
  );
}

/** The fold's source label beside a field (prototype `.src`): where the value comes from, or 「你改的」 once changed. */
function Source({ changed, children }: { changed: boolean; children: ReactNode }) {
  return <span data-slot="field-source" className="text-[11.5px] text-muted-foreground">{changed ? "你改的" : children}</span>;
}

/** A labelled control; `tag` sits beside the label (outside it, so the label text stays the accessible name),
 * `hint` is the small line under the control (the cap's 打平 comparison). */
function Field({ id, label, tag, hint, children }: { id: string; label: string; tag?: ReactNode; hint?: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <label htmlFor={id} className="block text-xs text-muted-foreground">{label}</label>
        {tag}
      </div>
      {children}
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
