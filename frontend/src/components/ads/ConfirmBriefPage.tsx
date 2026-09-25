import { useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import {
  generateStrategy, getCampaign, patchCampaign,
  type CampaignDetail, type CampaignFieldSources, type PatchCampaignInput,
} from "@/lib/adsApi";
import { fetchChannels } from "@/lib/adsLaunchApi";
import { getWizardOptions, patchAudienceHint } from "@/lib/adsWizardApi";
import { useApiRead } from "@/lib/useApiRead";
import { ActionBar, Disclosure, FlowHeader, MoneyInput, ReadFailed, formatAmount } from "./patterns";
import { UnderstoodField, UnderstoodSkeleton, newCampaignPath, wizardSteps, type UnderstoodKey } from "./wizard/WizardPieces";

interface CampaignContext {
  product_ids?: string[];
  audience_hint?: string | null;
  field_sources?: Partial<CampaignFieldSources>;
}
interface CampaignConstraints { platform?: unknown; budget?: unknown }

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

/** New-campaign wizard v10 step 2 (F30-I05, prototype `newStep2()` 「系統這樣理解」): six fields the create call
 * understood — 商品、結果、期間、預算上限、平台、受眾方向 (主打 and 素材 N 則 are strategy outputs, not shown before
 * the strategy). A field the system guessed (`field_sources === "system"`) is dashed with 「猜的，請確認」; pressing a
 * field edits it in place and `PATCH`es that one field (no re-parse). 「產生策略」 is the second and last model call
 * of the wizard (ARCHITECTURE.md §6.1 item 11) and lands on the strategy tab. */
export function ConfirmBriefPage({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  const navigate = useNavigate();
  const homeHref = `/brands/${brandId}/ads`;
  const read = useApiRead(() => getCampaign(brandId, campaignId), [brandId, campaignId]);
  const options = useApiRead(() => getWizardOptions(brandId), [brandId]);
  const channels = useApiRead(() => fetchChannels(brandId), [brandId]);
  const [saved, setSaved] = useState<CampaignDetail | null>(null);
  const [editing, setEditing] = useState<UnderstoodKey | null>(null);
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

  const context = (campaign.context_json ?? {}) as CampaignContext;
  const constraints = (campaign.constraints_json ?? {}) as CampaignConstraints;
  const sources = context.field_sources ?? {};
  const guessed = (key: keyof CampaignFieldSources) => (sources[key] ?? "system") === "system";
  const productId = context.product_ids?.[0] ?? null;
  const products = options.data?.products ?? [];
  const objectives = options.data?.objectives ?? [];
  const platform = typeof constraints.platform === "string" ? constraints.platform : null;
  const audience = context.audience_hint ?? "";

  const productName = !productId ? ""
    : products.find((p) => p.id === productId)?.name
      ?? (options.status === "ready" ? "（不在可選商品裡）" : options.status === "error" ? "（商品名稱讀不到）" : "…");
  const objectiveLabel = objectives.find((o) => o.key === campaign.objective)?.label ?? campaign.objective ?? "";
  const platformLabel = channels.data?.find((c) => c.key === platform)?.label ?? platform ?? "";

  async function save(key: UnderstoodKey, patch: PatchCampaignInput | { audience_hint: string }) {
    setSaving(true); setSaveError(null);
    try {
      const updated = "audience_hint" in patch
        ? await patchAudienceHint(brandId, campaignId, patch.audience_hint)
        : await patchCampaign(brandId, campaignId, patch);
      setSaved(updated); setEditing((now) => (now === key ? null : now));
    } catch (err) {
      setSaveError(message(err, "更新失敗，請稍後再試。"));
    } finally {
      setSaving(false);
    }
  }
  /** 完成 on an unchanged field the user already owns just closes it; on a guessed one it confirms it. */
  const done = (key: UnderstoodKey, source: keyof CampaignFieldSources, changed: boolean, patch: PatchCampaignInput | { audience_hint: string }) => {
    if (!changed && !guessed(source)) { setEditing(null); return; }
    void save(key, patch);
  };
  const cancel = () => { setEditing(null); setSaveError(null); };
  const edit = (key: UnderstoodKey) => () => { setSaveError(null); setEditing(key); };

  const fields: { key: UnderstoodKey; source: keyof CampaignFieldSources; label: string; value: string; editable: boolean; editor: ReactNode }[] = [
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
      key: "audience", source: "audience", label: "受眾方向", value: audience, editable: true,
      editor: <TextEditor label="受眾方向" initial={audience} busy={saving} onCancel={cancel}
        onDone={(v) => done("audience", "audience", v !== audience, { audience_hint: v })} />,
    },
  ];
  const guesses = fields.filter((f) => guessed(f.source)).length;

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
        {fields.map((f) => (
          <UnderstoodField key={f.key} field={f.key} label={f.label} value={f.value || "未設定"} guessed={guessed(f.source)}
            editing={editing === f.key} onEdit={f.editable && !generating ? edit(f.key) : undefined} editor={f.editor} />
        ))}
      </div>
      {saveError && <p role="alert" className="text-sm text-destructive">{saveError}</p>}
      {options.status === "error" && <ReadFailed what={`商品和目標清單讀不到（${options.error}）；這兩項先不能改，其他照常`} onRetry={options.reload} />}
      {channels.status === "error" && <ReadFailed what={`平台清單讀不到（${channels.error}）；平台先不能改，其他照常`} onRetry={channels.reload} />}
      {generateError && <p role="alert" className="text-sm text-destructive">{generateError}</p>}
      <Disclosure label="進階">
        <Link className="text-sm text-primary underline-offset-4 hover:underline" to={`/brands/${brandId}/ads/campaigns/${campaignId}?tab=assets`}>先處理自帶素材與手動交接</Link>
      </Disclosure>
    </>,
    <ActionBar back={{ label: "上一步", to: backHref }} hint={guesses ? `有 ${guesses} 項是猜的` : undefined}>
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

function TextEditor({ label, initial, busy, onDone, onCancel }: {
  label: string; initial: string; busy: boolean; onDone: (value: string) => void; onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const submit = () => onDone(value.trim());
  return (
    <>
      <Input autoFocus aria-label={label} value={value} maxLength={200} onChange={(e) => setValue(e.target.value)} className="min-w-0 flex-1"
        onKeyDown={(e) => { if (e.key === "Enter" && !busy) { e.preventDefault(); submit(); } else onEscape(onCancel)(e); }} />
      <DoneButton disabled={busy} onClick={submit} />
    </>
  );
}
