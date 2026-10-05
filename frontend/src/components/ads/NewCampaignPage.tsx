import { newCampaignPath } from "@/lib/adsRoutes";
import { formatMoney } from "@/lib/format";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { addDays, daysBetween } from "@/lib/orgClock";
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
import { cn } from "@/lib/utils";
import { UserAssetsLibrary } from "./UserAssetsLibrary";
import { clearDraft, readDraft, saveDraft } from "./campaignDraft";
import { ActionBar, Chip, Disclosure, FlowHeader, MoneyInput, PickCard, PickGroup, ReadFailed, formatAmount, useAdsRules } from "./patterns";
import { SellWayPickCard, SourceTag, UnderstandingView, breakEvenDerivedMark, wizardSteps, type SourceTagKind } from "./wizard/WizardPieces";

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
  const length = daysBetween(latest.start_date, latest.end_date);
  if (length === null || length <= 0) return null;
  const end = latest.end_date;
  return { start: addDays(end, 1), end: addDays(end, length), prevStart: latest.start_date, prevEnd: latest.end_date };
}

/** F46-I08 (Contract D, `app/ads/brief.py`): the cap a create stores when none is sent — the same sell-way's previous
 * campaign's (沿用上一期), else the sell-way's own cap, else its break-even as a whole amount (打平線). */
function capDefault(way: WizardProduct | null): { value: number | null; source: SourceTagKind | null } {
  if (!way) return { value: null, source: null };
  if (way.previous?.cap != null) return { value: way.previous.cap, source: "copied" };
  const ownIsBreakEven = way.cap_per_sale === null || way.cap_per_sale === way.break_even;
  if (!ownIsBreakEven) return { value: way.cap_per_sale, source: "sell_way" };
  const whole = way.break_even === null ? null : Math.round(way.break_even);
  return whole !== null && whole > 0 ? { value: whole, source: "break_even" } : { value: null, source: null };
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
 * the brand's own images／videos stay folded under 「進階：一句話建立、自帶圖片／影片」.
 * F46-I08 (prototype f46-learnings `#/new?from=B`／`?way=single`): platform, 這個活動最多花 and 每筆上限 move into
 * 「期間、預算與平台」, each with its source tag (沿用上一期／打平線／已接上的帳戶／你改的); they start from the same
 * sell-way's previous campaign, else the brand's connected account and the break-even — the values the server stores
 * when they are not sent, so only changed values go out (shown = stored). A learn strip under 要推什麼 names the
 * closed campaigns this period builds on. The fold keeps 受眾 and 落地頁. */
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
  // F50 Contract I (decision 11): the brief's default period is served (`limits.campaign_default_days`); while the
  // rules load the sentence prints without the number.
  const defaultDays = useAdsRules()?.limits.campaign_default_days ?? null;

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
    const started = Date.now(); // ELAPSED_OK: the 「已等 N 秒」 counter measures elapsed seconds, not a date
    const timer = setInterval(() => setWaited(Math.round((Date.now() - started) / 1000)), 1000); // ELAPSED_OK: same counter
    return () => clearInterval(timer);
  }, [phase]);

  const way = data?.products.find((p) => p.id === productId) ?? null;
  const goal = data?.objectives.find((o) => o.key === objective && o.available) ?? null;
  const oneDate = !!startDate !== !!endDate;
  const backwards = !!startDate && !!endDate && endDate < startDate;
  const budgetOk = budget !== null && budget > 0;
  const prev = way?.previous ?? null;

  // F46-I08: each value's default (the same sell-way's previous campaign first) and what differs from it.
  const brandPlatform = data?.default_platform ?? null;
  const defaultPlatform = prev?.platform ?? brandPlatform;
  const platformShown = platform ?? defaultPlatform;
  const platformChanged = platform !== null && platform !== defaultPlatform;
  const platformTag: SourceTagKind | null = platformChanged ? "user" : prev?.platform ? "copied" : brandPlatform ? "brand" : null;
  const groups = way?.customer_groups ?? [];
  /** One group of several; anything else (all groups, or a sell-way with one group) is 「都投」, sent as nothing. */
  const groupShown = groups.length > 1 && groups.some((g) => g.id === groupPick) ? groupPick : "";
  const capBase = capDefault(way);
  const capShown = cap === undefined ? capBase.value : cap;
  const capChanged = cap != null && cap > 0 && cap !== capBase.value;
  /** A default cap cleared by hand would not be stored as shown: it has to be filled again. */
  const capCleared = cap === null && capBase.value !== null;
  const capTag: SourceTagKind | null = capChanged ? "user" : capShown === null ? null : capBase.source;
  const prevBudget = prev?.budget ?? null;
  const budgetTag: SourceTagKind | null = !budgetOk ? null : prevBudget !== null && budget === prevBudget ? "copied" : "user";
  const landingShown = landing ?? way?.landing_url ?? "";
  const landingChanged = landing !== undefined && !!landing.trim() && landing.trim() !== (way?.landing_url ?? "");
  const breakEven = way?.break_even ?? null;
  const beText = breakEven === null || !way ? "" : `打平 ${fmt(breakEven)}${breakEvenDerivedMark(way)}`;
  const capHint = capShown === null
    ? (way && way.cap_per_sale === null ? "這個賣法還算不出打平；可以自己填" : "")
    : breakEven === null ? ""
      : capShown === breakEven || capShown === Math.round(breakEven) ? `等於${beText}`
      : capShown > breakEven ? `比${beText} 高 ${fmt(capShown - breakEven)}` : `比${beText} 低 ${fmt(breakEven - capShown)}`;
  const prevPeriod = prev ? prev.campaign_name.split("・")[1] ?? prev.campaign_name : "";
  const budgetHint = budgetOk
    ? (budgetTag === "copied" && prev?.spend != null ? `上一期 ${prevPeriod} 花了 ${formatMoney(prev.spend, "TWD")}` : "")
    : way && !prev ? "第一次推，要自己填" : "";

  const hint = !way || !goal ? "選好要推什麼和想要的結果"
    : !budgetOk ? "填這個活動最多花"
    : capCleared ? "填每筆上限"
    : oneDate ? "開始和結束要一起填"
    : backwards ? "結束要在開始之後" : "";
  const pendingRead = restoring || (!!createdId && !created);
  const blocked = !!hint || busy || uploadBusy || pendingRead;

  // The budget starts from the same sell-way's previous campaign while the form holds none (a restored draft keeps
  // its own value); another sell-way swaps a prefilled budget for its own previous one.
  const wayId = way?.id ?? null;
  const prefilled = useRef<number | null>(null);
  useEffect(() => {
    if (createdId || !wayId) return;
    const before = prefilled.current;
    setBudget((now) => (now === null || now === before ? prevBudget : now));
    prefilled.current = prevBudget;
  }, [createdId, wayId, prevBudget]);
  /** Only the changed fold values go out; the server takes the rest from the brand and the sell-way (F43-I04). */
  const extras: CampaignCreateExtras & Pick<CampaignPicks, "customer_group_ids"> = {
    ...(platformChanged && platform ? { platform } : {}),
    ...(groupShown ? { customer_group_ids: [groupShown] } : {}),
    ...(capChanged && cap != null ? { cap } : {}),
    ...(landingChanged && landing ? { landing_url: landing.trim() } : {}),
  };
  /** Another sell-way brings its own platform, cap, audience and landing: changes to those go back to its values. */
  function pickWay(id: string) {
    if (id === productId) return;
    setProductId(id); setGroupPick(""); setCap(undefined); setLanding(undefined);
    if (!created) setPlatform(null);
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
    navigate(`${newCampaignPath(brandId)}/${encodeURIComponent(campaignId)}`);
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
    // The platform shown is the one kept (shown = stored), also after a sell-way change.
    const platformPatch = platformShown !== null && platformShown !== now.platform;
    if (budgetValue !== now.budget || platformPatch) {
      patch.constraints_json = { ...(campaign.constraints_json ?? {}), budget: budgetValue, ...(platformPatch ? { platform: platformShown } : {}) };
    }
    // A sell-way change without groups resets them on the server; otherwise send the pick when it changed.
    if (wayChanged ? !!groupShown : groupShown !== now.groupPick) patch.customer_group_ids = groupShown ? [groupShown] : [];
    // Landing and cap are written when the user changed them here, or the sell-way changed (its own values then);
    // an untouched field keeps whatever the campaign holds.
    const landingNow = landing?.trim() ? landing.trim() : wayChanged ? picked.landing_url ?? "" : null;
    if (landingNow !== null && landingNow !== (ctx.landing_url ?? "")) patch.landing_url = landingNow || null;
    let out = Object.keys(patch).length > 0 ? await patchCampaign(brandId, campaign.id, patch) : campaign;
    // The cap is not a campaign field: it goes through the target writer (revision-guarded), like step 2.
    const capNow = cap != null && cap > 0 ? cap : wayChanged ? capDefault(picked).value : null;
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
    : <>活動名稱會叫「<b>{nameBase(way.name)}</b>」加上期間（沒填日期就{defaultDays === null ? "用預設期間" : `從今天起算 ${defaultDays} 天`}）</>);
  // The pick view stays mounted (hidden) while the create runs, so the upload library keeps its selection for
  // an attach retry.
  return (
    <Shell homeHref={homeHref} bar={picking ? (
      <ActionBar back={{ label: "投放中心", to: homeHref }}>
        <Button busy={busy || uploadBusy} disabledReason={hint || (pendingRead ? "正在讀取已建立的活動，請稍候" : undefined)} onClick={() => void submit()}>
          {created && error && uploads.some((u) => !attached.has(u.id)) ? "重試加入未完成素材並繼續" : "下一步：系統理解"} →
        </Button>
      </ActionBar>
    ) : (
      <ActionBar
        back={<Button variant="ghost" busy={phase === "understanding"} onClick={() => setPhase("pick")}>← 上一步</Button>}
        hint={phase === "failed" ? "讀取失敗，按上方重試" : undefined}
      >
        <Button disabledReason={phase === "failed" ? "先重試並完成系統理解" : "系統理解完成後才能產生策略"}>產生策略 →</Button>
      </ActionBar>
    )}>
      {!picking && <UnderstandingView brandId={brandId} failed={phase === "failed" ? failure : null} waitedSeconds={waited} onRetry={() => void submit(lastRequest)} />}
      <div className={picking ? "contents" : "hidden"}>
      <FlowHeader steps={wizardSteps(brandId)} current={0} title="建立活動" purpose="選要推什麼、推多久、花多少；其他照上一期或商品建檔帶入" />
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
          {way && <LearnStrip brandId={brandId} way={way} breakEvenCap={capBase.source === "break_even"} />}
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
        <div className="surface-header">
          <h2 id="new-period">期間、預算與平台</h2>
          {prev && <span className="text-xs text-muted-foreground">標「沿用上一期」的照 {prev.campaign_name}</span>}
        </div>
        <div className="surface-body grid grid-cols-1 gap-x-5 gap-y-[18px] md:grid-cols-[repeat(3,minmax(0,220px))]">
          <Field id="new-start" label="開始">
            <Input id="new-start" type="date" value={startDate} disabled={locked} onChange={(e) => setStartDate(e.target.value)} className="h-[42px] w-full rounded-lg" />
          </Field>
          <Field id="new-end" label="結束">
            <Input id="new-end" type="date" value={endDate} disabled={locked} onChange={(e) => setEndDate(e.target.value)} className="h-[42px] w-full rounded-lg" />
          </Field>
          <Field id="new-platform" label="平台" tag={platformTag && <SourceTag kind={platformTag} title={platformTag === "copied" && prev ? `上一期：${prev.campaign_name}` : undefined} />}
            hint={platformShown ? undefined : "品牌還沒接上帳戶"}>
            <select id="new-platform" className={SELECT} value={platformShown ?? ""} disabled={locked || !channels.data} onChange={(e) => setPlatform(e.target.value || null)}>
              {!platformShown && <option value="" disabled>請選擇</option>}
              {(channels.data ?? []).map((c) => <option key={c.key} value={c.key}>{c.label}（{c.connected ? "已接上" : "還沒接上"}）</option>)}
            </select>
          </Field>
          <Field id="new-cap" label="這個活動最多花" tag={budgetTag && <SourceTag kind={budgetTag} title={budgetTag === "copied" && prev ? `上一期：${prev.campaign_name}` : undefined} />}
            hint={budgetHint} need={!budgetOk && !!budgetHint}>
            <MoneyInput id="new-cap" value={budget} onChange={setBudget} disabled={locked} onEnter={() => void submit()} placeholder="例如 10,000"
              className={cn("w-full", !budgetOk && "border-dashed border-grade-watch/55")} />
          </Field>
          <Field id="new-sale-cap" label="每筆上限" hint={capHint} tag={capTag && <SourceTag kind={capTag} title={capTag === "copied" && prev ? `上一期：${prev.campaign_name}` : undefined} />}>
            <MoneyInput id="new-sale-cap" value={capShown} onChange={setCap} disabled={locked || !way} placeholder={way ? "例如 450" : "先選要推什麼"} onEnter={() => void submit()}
              className={cn("w-full", way && capShown === null && "border-dashed border-grade-watch/55")} />
          </Field>
        </div>
        {(nameLine || previous) && (
          <div className="surface-body flex flex-col gap-1 pt-0">
            {nameLine && <p data-slot="name-line" className="text-sm">{nameLine}</p>}
            {previous && startDate && <p className="text-xs text-muted-foreground">日期接在上一期後面（上一期 {md(previous.start)}～{md(previous.end)}）</p>}
          </div>
        )}
        {channels.status === "error" && <div className="surface-body pt-0"><ReadFailed what={`平台清單讀不到（${channels.error}）；平台先照品牌已接上的帳戶，其他照常`} onRetry={channels.reload} /></div>}
      </section>
      <Disclosure label="進階：這期不一樣（受眾、落地頁）">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field id="new-audience" label="受眾" tag={way && <Source changed={!!groupShown}>{groups.length ? `來自商品：${groups.length} 群顧客` : "這個商品還沒有顧客群"}</Source>}>
            <select id="new-audience" className={SELECT} value={groupShown} disabled={locked || groups.length <= 1} onChange={(e) => setGroupPick(e.target.value)}>
              <option value="">{!way ? "先選要推什麼" : groups.length ? `${groups.length} 群都投（${groups.map((g) => g.who).join("、")}）` : "還沒有顧客群"}</option>
              {groups.length > 1 && groups.map((g) => <option key={g.id} value={g.id}>只投：{g.who}</option>)}
            </select>
          </Field>
          <Field id="new-landing" label="落地頁" hint={landing !== undefined && !landing.trim() && way?.landing_url ? "留空＝用賣法的落地頁" : undefined}
            tag={way && <Source changed={landingChanged}>{`來自賣法「${way.display_name}」`}</Source>}>
            <Input id="new-landing" type="url" value={landingShown} disabled={locked || !way} onChange={(e) => setLanding(e.target.value)}
              placeholder="https://" className="h-[42px] rounded-lg" />
          </Field>
        </div>
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
                ? <Button variant="outline" busy={busy || uploadBusy} disabledReason={locked ? "目前活動資料尚未就緒" : oneDate ? "開始和結束日期要一起填" : backwards ? "結束日不能早於開始日" : undefined} onClick={() => void submit({ kind: "sentence", text: goalText })}>產生建議</Button>
                : <Button variant="outline" busy={busy || uploadBusy} disabledReason={locked ? "目前活動資料尚未就緒" : oneDate ? "開始和結束日期要一起填" : backwards ? "結束日不能早於開始日" : undefined} onClick={() => void submit({ kind: "sentence", text: BRAND_SUGGESTION_REQUEST })}>請 AI 依品牌資料建議</Button>}
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
 * `hint` is the small line under the control (the cap's 打平 comparison); `need` colours it as a missing value. */
function Field({ id, label, tag, hint, need, children }: { id: string; label: string; tag?: ReactNode; hint?: string; need?: boolean; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-[5px]">
      <div className="flex flex-wrap items-center gap-1.5">
        <label htmlFor={id} className="block text-xs text-muted-foreground">{label}</label>
        {tag}
      </div>
      {children}
      {hint && <p className={cn("text-xs", need ? "font-medium text-warning" : "text-muted-foreground")}>{hint}</p>}
    </div>
  );
}

/** Prototype `.learn`: what this period builds on — the sell-way's closed campaigns with their 留下／換掉 counts and a
 * link to 品牌智庫 「投放學到的」, or that it has never closed (the cap then starts at 打平線). */
function LearnStrip({ brandId, way, breakEvenCap }: { brandId: string; way: WizardProduct; breakEvenCap: boolean }) {
  const learned = way.learned;
  return (
    <div data-slot="learn-strip" className={cn("flex flex-wrap items-center gap-3 rounded-[10px] border border-l-[3px] bg-card px-4 py-3",
      learned ? "border-l-primary" : "border-l-border")}>
      {learned ? (
        <>
          <p className="min-w-0 flex-1"><b>這期會用 {learned.campaigns.length} 期的學習</b>
            <span className="text-[13px] text-muted-foreground">・{learned.campaigns.map((c) => c.name).join("、")}</span></p>
          <Chip tone="ok">留下 {learned.keep}</Chip>
          <Chip tone="bad">換掉 {learned.replace}</Chip>
          <Link className="text-[13px] font-medium whitespace-nowrap text-primary underline-offset-4 hover:underline" to={`/brands/${brandId}/library?tab=ads-learnings`}>看學到什麼 →</Link>
        </>
      ) : (
        <p className="min-w-0 flex-1"><b>「{way.display_name}」還沒結案過</b>
          <span className="text-[13px] text-muted-foreground">・沒有學習可用{breakEvenCap ? "，每筆上限先用打平線" : ""}</span></p>
      )}
    </div>
  );
}
