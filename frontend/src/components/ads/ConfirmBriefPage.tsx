import { useState, type KeyboardEvent, type ReactNode } from "react";
import { Link2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { generateStrategy, getCampaign, patchCampaign, type CampaignDetail, type PatchCampaignInput } from "@/lib/adsApi";
import type { CampaignFieldSources, FieldSource } from "@/lib/adsCampaignTypes";
import { fetchChannels } from "@/lib/adsLaunchApi";
import { putTarget } from "@/lib/adsTriageApi";
import { getWizardOptions } from "@/lib/adsWizardApi";
import { useApiRead } from "@/lib/useApiRead";
import { cn } from "@/lib/utils";
import { ActionBar, Chip, Disclosure, FlowHeader, MoneyInput, ReadFailed, formatAmount } from "./patterns";
import { SourceTag, UnderstoodField, UnderstoodSkeleton, newCampaignPath, wizardSteps, type SourceTagKind, type UnderstoodKey } from "./wizard/WizardPieces";

interface CampaignConstraints { platform?: unknown; budget?: unknown }
/** The seven `UnderstoodField`s plus the campaign-level landing URL (F40-I12, its own piece below). */
type EditKey = UnderstoodKey | "landing_url";

const message = (err: unknown, fallback: string) => (err instanceof Error && err.message ? err.message : fallback);
const md = (d: string) => d.slice(5).replace("-", "/");
function periodText(start: string | null, end: string | null) {
  if (!start || !end) return "";
  return start.slice(0, 4) === end.slice(0, 4) ? `${md(start)} – ${md(end)}` : `${start.replaceAll("-", "/")} – ${end.replaceAll("-", "/")}`;
}
/** A number cap prints as money; an older free-text cap prints as typed; anything else is unset (never NaN). */
function budgetText(budget: unknown) {
  if (typeof budget === "number") return formatAmount(budget) === null ? "" : `NT$${formatAmount(budget)}`;
  return typeof budget === "string" ? budget.trim() : "";
}
const numericBudget = (budget: unknown) => (typeof budget === "number" && Number.isFinite(budget) && budget > 0 ? budget : null);

/** F36-I04 cap chip helpers (wording copied from `strategy/CapBlock.tsx`, ROAS at one decimal per the F36 prototype). */
const fmt = (v: number | null | undefined) => formatAmount(v) ?? "未知";
const roas = (price: number, cap: number) => (price / cap).toFixed(1);
/** 「比打平 N 高/低 M・ROAS 參考 R」 — each part only when its inputs are known; "" when neither is. */
function capCompareText(value: number, breakEven: number | null, price: number | null) {
  return [
    breakEven !== null && (value >= breakEven ? `比打平 ${fmt(breakEven)} 高 ${fmt(value - breakEven)}` : `比打平 ${fmt(breakEven)} 低 ${fmt(breakEven - value)}`),
    price !== null && `ROAS 參考 ${roas(price, value)}`,
  ].filter(Boolean).join("・");
}

const CAP_LABEL = "每賣一筆最多花";
/** The audience editor's 「N 群都投」 option (sent as `customer_group_ids: []`). */
const ALL_GROUPS = "all";
/** The landing row's source tag (F43-I15): from the sell-way／product, the user's own, or copied by F40. */
const LANDING_SOURCE: Partial<Record<FieldSource, string>> = { sell_way: "來自賣法", user: "你填的", copied: "照上一期" };
/** F46-I08: the field sources tagged instead of 「猜的，請確認」 (the create filled them by rule, not a guess). */
const TAGGED_SOURCES: readonly FieldSource[] = ["copied", "break_even", "brand"];

/** New-campaign wizard v10 step 2 (F30-I05, prototype `newStep2()` 「系統這樣理解」): six fields the create call
 * understood — 商品、結果、期間、預算上限、平台、受眾方向 (主打 and 素材 N 則 are strategy outputs, not shown before
 * the strategy). A field the system guessed (`field_sources === "system"`) is dashed with 「猜的，請確認」; pressing a
 * field edits it in place and `PATCH`es that one field (no re-parse). 「產生策略」 is the second and last model call
 * of the wizard (ARCHITECTURE.md §6.1 item 11) and lands on the strategy tab.
 *
 * F36-I04 (drill-6 #4, ruling A): a seventh chip 「每賣一筆最多花」, saved through `PUT …/target {basis:"own"}`. F46-I08
 * (Contract D): a structured create now stores the cap (沿用上一期, the sell-way's cap, else its break-even), so the
 * chip shows that stored value; an older campaign without one still reads empty with break-even as a hint. A value
 * the create filled by rule (`field_sources` `copied`／`break_even`／`brand`) shows its tag instead of 「猜的，請確認」;
 * `system` keeps 「猜的，請確認」. */
export function ConfirmBriefPage({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  const navigate = useNavigate();
  const homeHref = `/brands/${brandId}/ads`;
  const read = useApiRead(() => getCampaign(brandId, campaignId), [brandId, campaignId]);
  const options = useApiRead(() => getWizardOptions(brandId), [brandId]);
  const channels = useApiRead(() => fetchChannels(brandId), [brandId]);
  const [saved, setSaved] = useState<CampaignDetail | null>(null);
  const [editing, setEditing] = useState<EditKey | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const campaign = saved?.id === campaignId ? saved : read.data;
  const backHref = newCampaignPath(brandId, campaignId);
  const steps = wizardSteps(brandId, campaignId);
  const shell = (body: ReactNode, bar: ReactNode) => (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "建立活動", href: backHref }, { label: "系統理解" }]} />
      <div className="flex max-w-[1260px] flex-col gap-4 [&>[data-slot=flow-header]]:mb-1">{body}</div>
      <div className="flex-1" />
      {bar}
    </div>
  );

  if (!campaign) {
    return shell(
      <>
        <FlowHeader steps={steps} current={1} title="系統這樣理解" purpose="不對就點一下改" />
        {read.status === "error" ? <ReadFailed what={`這個活動讀不到（${read.error}）`} onRetry={read.reload} /> : <UnderstoodSkeleton />}
      </>,
      <ActionBar back={{ label: "上一步", to: backHref }}><Button disabled>產生策略 →</Button></ActionBar>,
    );
  }

  const context = campaign.context_json ?? {};
  const constraints = (campaign.constraints_json ?? {}) as CampaignConstraints;
  const sources = context.field_sources ?? {};
  const guessed = (key: keyof CampaignFieldSources) => (sources[key] ?? "system") === "system";
  const productId = context.product_ids?.[0] ?? null;
  const products = options.data?.products ?? [];
  const previousName = products.find((p) => p.id === productId)?.previous?.campaign_name;
  /** The tag of a value the create filled by rule; none for the user's own, the sell-way's, or a guess. */
  const ruleTag = (key: keyof CampaignFieldSources) => {
    const source = sources[key];
    return source && TAGGED_SOURCES.includes(source)
      ? <SourceTag kind={source as SourceTagKind} title={source === "copied" && previousName ? `上一期：${previousName}` : undefined} />
      : undefined;
  };
  const objectives = options.data?.objectives ?? [];
  const platform = typeof constraints.platform === "string" ? constraints.platform : null;
  const landingUrl = context.landing_url ?? "";
  // F43-I15: the audience is the sell-way's customer groups (`context_json.customer_group_ids`, named from the
  // options); an older campaign without them still reads its free-text `audience_hint`.
  const groups = products.find((p) => p.id === productId)?.customer_groups ?? [];
  const groupIds = context.customer_group_ids;
  const pickedGroups = groups.filter((g) => groupIds?.includes(g.id));
  const audience = !groupIds ? context.audience_hint ?? ""
    : pickedGroups.length === 0 ? (groupIds.length === 0 || options.status !== "loading" ? "" : "…")
    : pickedGroups.length === groups.length && groups.length > 1 ? `${groups.length} 群都投（${pickedGroups.map((g) => g.who).join("、")}）`
    : pickedGroups.map((g) => g.who).join("、");
  const groupPick = sources.audience === "user" && groupIds?.length === 1 ? groupIds[0] : ALL_GROUPS;

  const productName = !productId ? ""
    : products.find((p) => p.id === productId)?.name
      ?? (options.status === "ready" ? "（不在可選商品裡）" : options.status === "error" ? "（商品名稱讀不到）" : "…");
  const objectiveLabel = objectives.find((o) => o.key === campaign.objective)?.label ?? campaign.objective ?? "";
  const platformLabel = channels.data?.find((c) => c.key === platform)?.label ?? platform ?? "";

  async function save(key: EditKey, patch: PatchCampaignInput) {
    setSaving(true); setSaveError(null);
    try {
      const updated = await patchCampaign(brandId, campaignId, patch);
      setSaved(updated); setEditing((now) => (now === key ? null : now));
    } catch (err) {
      setSaveError(message(err, "更新失敗，請稍後再試。"));
    } finally {
      setSaving(false);
    }
  }
  /** 完成 on an unchanged field the user already owns just closes it; on a guessed one it confirms it. */
  const done = (key: UnderstoodKey, source: keyof CampaignFieldSources, changed: boolean, patch: PatchCampaignInput) => {
    if (!changed && !guessed(source)) { setEditing(null); return; }
    void save(key, patch);
  };
  const cancel = () => { setEditing(null); setSaveError(null); };
  const edit = (key: EditKey) => () => { setSaveError(null); setEditing(key); };

  /** The cap is not a campaign field: it goes through the target writer (revision-guarded) and the campaign is
   * re-read so the chip and the strategy call both see the saved value. */
  const cap = campaign.cap;
  async function saveCap(value: number) {
    setSaving(true); setSaveError(null);
    try {
      await putTarget(brandId, campaignId, { basis: "own", value, expected_revision: cap.revision });
      setSaved(await getCampaign(brandId, campaignId)); setEditing((now) => (now === "cap" ? null : now));
    } catch (err) {
      setSaveError(message(err, "儲存上限失敗，請稍後再試。"));
    } finally {
      setSaving(false);
    }
  }

  /** `source: null` = the cap: not a campaign field, never a guess; `hint` is its line under the value. */
  const fields: { key: UnderstoodKey; source: keyof CampaignFieldSources | null; label: string; value: string; editable: boolean; editor: ReactNode; hint?: string }[] = [
    {
      key: "product", source: "product", label: "商品", value: productName, editable: products.length > 0,
      editor: <SelectEditor label="商品" initial={productId ?? ""} busy={saving} onCancel={cancel}
        options={products.map((p) => ({ key: p.id, label: p.name }))}
        onDone={(v) => done("product", "product", v !== productId, { product_ids: [v] })} />,
    },
    {
      key: "objective", source: "objective", label: "結果", value: objectiveLabel, editable: objectives.some((o) => o.available),
      editor: <SelectEditor label="結果" initial={campaign.objective ?? ""} busy={saving} onCancel={cancel}
        options={objectives.filter((o) => o.available).map((o) => ({ key: o.key, label: o.label }))}
        onDone={(v) => done("objective", "objective", v !== campaign.objective, { objective: v })} />,
    },
    {
      key: "dates", source: "dates", label: "期間", value: periodText(campaign.start_date, campaign.end_date), editable: true,
      editor: <DatesEditor start={campaign.start_date ?? ""} end={campaign.end_date ?? ""} busy={saving} onCancel={cancel}
        onDone={(s, e) => done("dates", "dates", s !== campaign.start_date || e !== campaign.end_date, { start_date: s, end_date: e })} />,
    },
    {
      key: "budget", source: "budget", label: "預算上限", value: budgetText(constraints.budget), editable: true,
      editor: <BudgetEditor initial={numericBudget(constraints.budget)} busy={saving} onCancel={cancel}
        onDone={(v) => done("budget", "budget", v !== constraints.budget, { constraints_json: { ...(campaign.constraints_json ?? {}), budget: v } })} />,
    },
    {
      key: "platform", source: "platform", label: "平台", value: platformLabel, editable: (channels.data?.length ?? 0) > 0,
      editor: <SelectEditor label="平台" initial={platform ?? channels.data?.[0]?.key ?? ""} busy={saving} onCancel={cancel}
        options={(channels.data ?? []).map((c) => ({ key: c.key, label: c.label }))}
        onDone={(v) => done("platform", "platform", v !== platform, { constraints_json: { ...(campaign.constraints_json ?? {}), platform: v } })} />,
    },
    {
      key: "audience", source: "audience", label: "受眾", value: audience, editable: groups.length > 1,
      editor: <SelectEditor label="受眾" initial={groupPick} busy={saving} onCancel={cancel}
        options={[{ key: ALL_GROUPS, label: `${groups.length} 群都投` }, ...groups.map((g) => ({ key: g.id, label: `只投：${g.who}` }))]}
        onDone={(v) => done("audience", "audience", v !== groupPick, { customer_group_ids: v === ALL_GROUPS ? [] : [v] })} />,
    },
    {
      key: "cap", source: null, label: CAP_LABEL, value: cap.own_value === null ? "" : `NT$${fmt(cap.own_value)}`, editable: true,
      hint: cap.own_value === null
        ? (cap.break_even !== null ? `先不填就用打平 NT$${fmt(cap.break_even)}：售價 ${fmt(cap.price)} 扣成本、運費後的一筆利潤` : "")
        : capCompareText(cap.own_value, cap.break_even, cap.price),
      // An empty 完成 keeps whatever was there (no clear action here); an unchanged value just closes.
      editor: <CapEditor initial={cap.own_value} breakEven={cap.break_even} price={cap.price} busy={saving} onCancel={cancel}
        onDone={(v) => { if (v === null || v === cap.own_value) cancel(); else void saveCap(v); }} />,
    },
  ];
  // The target writer does not touch `field_sources.cap`: the cap's tag is shown only while the value is still the
  // one its source gave (the previous campaign's cap／the whole break-even).
  const previousCap = products.find((p) => p.id === productId)?.previous?.cap ?? null;
  const capTagHolds = cap.own_value !== null && (
    sources.cap === "copied" ? cap.own_value === previousCap
      : sources.cap === "break_even" ? cap.break_even !== null && cap.own_value === Math.round(cap.break_even) : false);
  const guesses = fields.filter((f) => f.source !== null && guessed(f.source)).length;
  const capUnfilled = cap.own_value === null && cap.break_even !== null;
  const barHint = [guesses ? `有 ${guesses} 項是猜的` : null, capUnfilled ? "上限沒填會先用打平" : null].filter(Boolean).join("・") || undefined;

  async function handleGenerate() {
    setGenerating(true); setGenerateError(null);
    try {
      await generateStrategy(brandId, campaignId);
      navigate(`/brands/${brandId}/ads/campaigns/${campaignId}?tab=strategy`);
    } catch (err) {
      setGenerateError(message(err, "產生策略失敗，請稍後再試。"));
      setGenerating(false);
    }
  }

  return shell(
    <>
      <FlowHeader steps={steps} current={1} title="系統這樣理解" purpose="不對就點一下改" />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {fields.map((f) => (f.source === null
          ? <UnderstoodField key={f.key} field={f.key} label={f.label} value={f.value || "還沒填（選填）"} empty={!f.value} hint={f.hint} wide
              guessed={false} tag={capTagHolds ? ruleTag("cap") : undefined} editing={editing === f.key} onEdit={!generating ? edit(f.key) : undefined} editor={f.editor} />
          : <UnderstoodField key={f.key} field={f.key} label={f.label} value={f.value || "未設定"} guessed={guessed(f.source)} tag={ruleTag(f.source)}
              editing={editing === f.key} onEdit={f.editable && !generating ? edit(f.key) : undefined} editor={f.editor} />
        ))}
        <LandingUrlField value={landingUrl} source={sources.landing_url} editing={editing === "landing_url"} onEdit={!generating ? edit("landing_url") : undefined}
          editor={<UrlEditor initial={landingUrl} busy={saving} onCancel={cancel}
            onDone={(v) => { if (v === landingUrl) cancel(); else void save("landing_url", { landing_url: v || null }); }} />} />
      </div>
      {saveError && <p role="alert" className="text-sm text-destructive">{saveError}</p>}
      {options.status === "error" && <ReadFailed what={`商品和目標清單讀不到（${options.error}）；這兩項先不能改，其他照常`} onRetry={options.reload} />}
      {channels.status === "error" && <ReadFailed what={`平台清單讀不到（${channels.error}）；平台先不能改，其他照常`} onRetry={channels.reload} />}
      {generateError && <p role="alert" className="text-sm text-destructive">{generateError}</p>}
      <Disclosure label="進階">
        <Link className="text-sm text-primary underline-offset-4 hover:underline" to={`/brands/${brandId}/ads/campaigns/${campaignId}?tab=assets`}>先處理自帶素材與手動交接</Link>
      </Disclosure>
    </>,
    <ActionBar back={{ label: "上一步", to: backHref }} hint={barHint}>
      <Button onClick={() => void handleGenerate()} disabled={generating || saving || editing !== null}>
        {generating ? "產生中…" : "產生策略 →"}
      </Button>
    </ActionBar>,
  );
}

const onEscape = (cancel: () => void) => (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); cancel(); } };
const SELECT = "h-9 min-w-0 flex-1 rounded-md border border-input bg-card px-3 text-sm focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none";

function DoneButton({ disabled, onClick }: { disabled?: boolean; onClick: () => void }) {
  return <Button size="sm" variant="outline" disabled={disabled} onClick={onClick}>完成</Button>;
}

function SelectEditor({ label, options, initial, busy, onDone, onCancel }: {
  label: string; options: { key: string; label: string }[]; initial: string; busy: boolean; onDone: (value: string) => void; onCancel: () => void;
}) {
  const [value, setValue] = useState(options.some((o) => o.key === initial) ? initial : options[0]?.key ?? "");
  return (
    <>
      <select autoFocus aria-label={label} className={SELECT} value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={onEscape(onCancel)}>
        {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
      </select>
      <DoneButton disabled={busy || !value} onClick={() => onDone(value)} />
    </>
  );
}

function DatesEditor({ start, end, busy, onDone, onCancel }: {
  start: string; end: string; busy: boolean; onDone: (start: string, end: string) => void; onCancel: () => void;
}) {
  const [s, setS] = useState(start);
  const [e, setE] = useState(end);
  return (
    <>
      <Input aria-label="開始日期" type="date" value={s} onChange={(ev) => setS(ev.target.value)} onKeyDown={onEscape(onCancel)} className="w-[150px]" />
      <Input aria-label="結束日期" type="date" value={e} onChange={(ev) => setE(ev.target.value)} onKeyDown={onEscape(onCancel)} className="w-[150px]" />
      <DoneButton disabled={busy || !s || !e || e < s} onClick={() => onDone(s, e)} />
    </>
  );
}

function BudgetEditor({ initial, busy, onDone, onCancel }: {
  initial: number | null; busy: boolean; onDone: (value: number) => void; onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const ok = value !== null && value > 0;
  return (
    <>
      <div onKeyDown={onEscape(onCancel)} className="min-w-0 flex-1">
        <MoneyInput label="預算上限" value={value} onChange={setValue} invalid={value === 0} className="w-full" onEnter={() => { if (ok && !busy) onDone(value); }} />
      </div>
      <DoneButton disabled={busy || !ok} onClick={() => { if (ok) onDone(value); }} />
    </>
  );
}

/** The cap editor (prototype: `.money` input, 「用打平 N」, the live preview line, 完成／取消). Enter saves, Escape
 * cancels. `onDone(null)` = the input was left empty (the caller keeps the previous value; nothing is cleared). */
function CapEditor({ initial, breakEven, price, busy, onDone, onCancel }: {
  initial: number | null; breakEven: number | null; price: number | null; busy: boolean;
  onDone: (value: number | null) => void; onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const invalid = value !== null && value < 1;
  const preview = value === null
    ? <span className="text-muted-foreground">{breakEven !== null ? `填一個整數金額；留空＝先用打平 ${fmt(breakEven)}` : "填一個整數金額"}</span>
    : invalid
      ? <span className="text-danger">請填大於 0 的整數金額</span>
      : <span className="text-muted-foreground">{capCompareText(value, breakEven, price)}</span>;
  const beFill = breakEven !== null ? Math.round(breakEven) : null;
  const submit = () => { if (!invalid && !busy) onDone(value); };
  return (
    <>
      <div onKeyDown={onEscape(onCancel)} className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <MoneyInput label={CAP_LABEL} value={value} onChange={setValue} invalid={invalid} onEnter={submit} />
          {beFill !== null && <Button size="sm" variant="outline" disabled={busy} onClick={() => setValue(beFill)}>用打平 {fmt(beFill)}</Button>}
        </div>
        <div className="min-h-4 text-xs" aria-live="polite">{preview}</div>
      </div>
      <DoneButton disabled={busy || invalid} onClick={submit} />
      <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}>取消</Button>
    </>
  );
}

/** F40-I12 (drill-7 #10): the campaign-level landing URL (`context_json.landing_url`), shown in the main block with
 * its source tag (F43-I15: `field_sources.landing_url` — 「來自賣法」 for the sell-way's effective landing (its own URL, else the product page); none when unknown) — the same `.uchip` box as the seven understood fields (`UnderstoodField` keys are the
 * six campaign fields plus the cap; this one has its own piece). Optional: blank reads 「還沒填（選填）」 on a neutral
 * dashed border, never a guess. Saved through the campaign PATCH (`landing_url`; blank clears). */
function LandingUrlField({ value, source, editing, onEdit, editor }: { value: string; source?: FieldSource; editing: boolean; onEdit?: () => void; editor: ReactNode }) {
  const tag = source ? LANDING_SOURCE[source] : undefined;
  const box = "flex w-full items-center gap-3 rounded-xl border bg-card px-3.5 py-3 text-left";
  const tile = <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-accent text-accent-foreground"><Link2 className="size-4" strokeWidth={1.75} /></span>;
  const name = <span className="flex shrink-0 items-center gap-2"><span className="text-xs text-muted-foreground">落地頁</span>{tag && <Chip tone="accent">{tag}</Chip>}</span>;
  if (editing) {
    return (
      <div data-field="landing_url" className={cn(box, "flex-wrap border-primary md:col-span-2")}>
        {tile}{name}
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{editor}</div>
      </div>
    );
  }
  const body = (
    <>
      {tile}{name}
      <b className={cn("min-w-0 flex-1 text-[15px] [overflow-wrap:anywhere]", value ? "font-semibold" : "font-medium text-muted-foreground")}>{value || "還沒填（選填）"}</b>
      {onEdit && <span aria-hidden="true" className="text-muted-foreground">✎</span>}
    </>
  );
  const border = value ? "border-border" : "border-dashed border-border";
  return onEdit
    ? <button type="button" data-field="landing_url" aria-label="改落地頁" onClick={onEdit} className={cn(box, border, "md:col-span-2 hover:border-primary")}>{body}</button>
    : <div data-field="landing_url" className={cn(box, border, "md:col-span-2")}>{body}</div>;
}

function UrlEditor({ initial, busy, onDone, onCancel }: {
  initial: string; busy: boolean; onDone: (value: string) => void; onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const submit = () => onDone(value.trim());
  return (
    <>
      <Input autoFocus aria-label="落地頁" type="url" value={value} placeholder="https://" onChange={(e) => setValue(e.target.value)} className="min-w-0 flex-1"
        onKeyDown={(e) => { if (e.key === "Enter" && !busy) { e.preventDefault(); submit(); } else onEscape(onCancel)(e); }} />
      <DoneButton disabled={busy} onClick={submit} />
      <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}>取消</Button>
    </>
  );
}
