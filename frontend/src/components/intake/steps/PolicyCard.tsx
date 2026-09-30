import { useId, useState, type ComponentProps, type ReactNode } from "react";
import type { OfferKey, OnboardingSource, PolicyItem, PolicyParamValue, PolicyType } from "@/lib/intakeOnboardingApi";
import { cn } from "@/lib/utils";
import { AiTag } from "../shared/AiTag";
import { CustomEscape, CustomMark, type CustomOption } from "../shared/CustomEscape";

/** 「全店政策」 of brand onboarding `#/b4` (prototype `policyCard()` of
 * `.harness/scratch/prototype/f41-onboarding/index.html`): the fixed 7 天猶豫期 row, the registry's common
 * chips, 「更多政策」 with the rest grouped, the chosen policies (「你有的」) with their params and the offer they
 * become in ads, and 「自訂」. Controlled: `EvidenceStep` owns the lists and saves them on 下一步. Chip order,
 * groups, params and offer labels all come from the API registry (`policy_types`). */

/** A policy the user has: a registry type or a 自訂 one. `params` holds what the inputs show. */
export interface ChosenPolicy {
  key: string;
  label: string;
  params: Record<string, PolicyParamValue>;
  offer_key: OfferKey | null;
  offer_label: string;
  /** A 自訂 policy's own ad sentence (registry sentences are composed by the server). */
  sentence: string;
  /** `ai` = the scan found it (tag with `note`), `saved` / `picked` = 你選的, `custom` = 你自訂. */
  origin: Exclude<OnboardingSource, "none"> | "picked" | "custom";
  note: string;
}

export interface CoolingOff {
  applies: boolean;
  disclosure: string;
}

/** Server rule (`vocab.COOLING_OFF_DISCLOSURE_MIN_CHARS`): the disclosure is at least 10 characters. */
export const DISCLOSURE_MIN_CHARS = 10;

export function chosenFromItem(item: PolicyItem): ChosenPolicy {
  return {
    key: item.key,
    label: item.label,
    params: { ...item.params },
    offer_key: item.offer_key,
    offer_label: item.offer_label,
    sentence: item.sentence,
    origin: item.key === "custom" ? "custom" : item.source === "ai" ? "ai" : "saved",
    note: item.note,
  };
}

const isEmpty = (v: PolicyParamValue | undefined) => v === undefined || String(v).trim() === "";

/** Why 下一步 is blocked, or null: the first chosen policy with a required param left empty
 * (「滿額免運還沒填門檻」), then a 不適用 cooling-off without its disclosure text. */
export function blockingReason(chosen: ChosenPolicy[], types: PolicyType[], cooling: CoolingOff): string | null {
  const byKey = new Map(types.map((t) => [t.key, t]));
  for (const p of chosen) {
    const spec = byKey.get(p.key);
    const missing = spec?.params.find((param) => !param.optional && isEmpty(p.params[param.name]));
    if (spec && missing) return `${spec.label}還沒填${paramWord(missing.label)}`;
  }
  if (!cooling.applies && cooling.disclosure.trim().length < DISCLOSURE_MIN_CHARS) {
    return `不適用 7 天猶豫期，要填網頁上的告知文字（至少 ${DISCLOSURE_MIN_CHARS} 字）`;
  }
  return null;
}

/** 「門檻 NT$」 → 門檻; a label that is only a unit away from one character keeps its quotes (「滿 NT$」). */
function paramWord(label: string): string {
  const word = label.replace(/（.*?）/g, "").replace(/NT\$|%/g, "").replace(/\s*或\s*$/, "").trim();
  return word.length >= 2 ? word : `「${label}」`;
}

export function PolicyCard({ brandId, types, chosen, onChange, cooling, onCooling, prefilled }: {
  brandId: string;
  types: PolicyType[];
  chosen: ChosenPolicy[];
  onChange: (update: (prev: ChosenPolicy[]) => ChosenPolicy[]) => void;
  cooling: CoolingOff;
  onCooling: (next: CoolingOff) => void;
  /** What the step loaded, by key: re-picking a policy brings back its loaded params and tag. */
  prefilled: Map<string, ChosenPolicy>;
}) {
  const [more, setMore] = useState(false);
  const disclosureId = useId();
  const common = types.filter((t) => t.common);
  const rest = types.filter((t) => !t.common);
  const groups = [...new Set(rest.map((t) => t.group))];
  const has = new Set(chosen.map((p) => p.key));
  const order = new Map(types.map((t, i) => [t.key, i]));
  const rows = [...chosen].sort((a, b) => (order.get(a.key) ?? types.length) - (order.get(b.key) ?? types.length));

  function toggle(type: PolicyType) {
    onChange((prev) => {
      if (prev.some((p) => p.key === type.key)) return prev.filter((p) => p.key !== type.key);
      const again = prefilled.get(type.key);
      return [...prev, again ?? {
        key: type.key, label: type.label, params: {}, offer_key: type.offer_key, offer_label: type.offer_label,
        sentence: "", origin: "picked", note: "",
      }];
    });
  }

  function setParam(target: ChosenPolicy, name: string, value: string) {
    onChange((prev) => prev.map((p) => (p === target ? { ...p, params: { ...p.params, [name]: value } } : p)));
  }

  /** A 自訂 policy joins 「你有的」 checked and marked 「你自訂」; its row's × is the undo. */
  function addCustom(option: CustomOption<"policy">) {
    const item: ChosenPolicy = {
      key: "custom", label: option.label, params: option.params, offer_key: option.offer_key,
      offer_label: option.offer_label, sentence: option.sentence, origin: "custom", note: "",
    };
    onChange((prev) => [...prev.filter((p) => !(p.key === "custom" && p.label === item.label)), item]);
  }

  const chip = (type: PolicyType) => {
    const on = has.has(type.key);
    return (
      <button
        key={type.key}
        type="button"
        aria-pressed={on}
        onClick={() => toggle(type)}
        className={cn(
          "rounded-full border px-[13px] py-[5px] text-[13px] font-medium hover:border-primary",
          on ? "border-primary bg-accent/40 text-accent-foreground shadow-[0_0_0_1px_var(--color-primary)]" : "border-border bg-card",
        )}
      >
        {type.label}
      </button>
    );
  };

  return (
    <EvidenceCard title="全店政策" note="每個商品都適用；有勾的才會寫進廣告" slot="policy-card">
      <Item className="bg-muted">
        <Chip>7 天猶豫期</Chip>
        <div className="min-w-0 flex-1">
          <b className="font-medium">網購依法都有，顧客收到 7 天內可以退</b>
          <div className="text-[11.5px] text-muted-foreground">
            消保法 §19；固定顯示、不能取消。賣的是易腐敗食品等法定例外，才
            <button
              type="button"
              aria-expanded={!cooling.applies}
              aria-controls={cooling.applies ? undefined : disclosureId}
              className="text-[11.5px] font-medium whitespace-nowrap text-primary hover:underline"
              onClick={() => onCooling(cooling.applies ? { applies: false, disclosure: cooling.disclosure } : { applies: true, disclosure: "" })}
            >
              改成「不適用」並填網頁上的告知文字
            </button>
          </div>
          {!cooling.applies && (
            <textarea
              id={disclosureId}
              rows={2}
              aria-label="網頁上的告知文字"
              required
              className={cn(INPUT, "mt-2")}
              value={cooling.disclosure}
              autoFocus={!cooling.disclosure}
              onChange={(e) => onCooling({ applies: false, disclosure: e.target.value })}
            />
          )}
        </div>
      </Item>

      <SecLabel className="mt-3.5">常見的</SecLabel>
      <div role="group" aria-label="常見的" className="flex flex-wrap gap-2">{common.map(chip)}</div>
      {more && groups.map((group) => (
        <div key={group}>
          <SecLabel className="mt-3">{group}</SecLabel>
          <div role="group" aria-label={group} className="flex flex-wrap gap-2">
            {rest.filter((t) => t.group === group).map(chip)}
          </div>
        </div>
      ))}
      {rest.length > 0 && (
        <button type="button" aria-expanded={more} className="mt-2.5 block text-[13px] font-medium whitespace-nowrap text-primary hover:underline" onClick={() => setMore((v) => !v)}>
          {more ? "收起" : `更多政策（${rest.length} 種）`}
        </button>
      )}

      {rows.length > 0 && (
        <>
          <SecLabel className="mt-3.5">你有的（{rows.length}）</SecLabel>
          <div data-slot="chosen-policies">
            {rows.map((p) => (
              <ChosenRow key={p.key === "custom" ? `custom:${p.label}` : p.key} policy={p} spec={types.find((t) => t.key === p.key)} onParam={setParam} onRemove={() => onChange((prev) => prev.filter((x) => x !== p))} />
            ))}
          </div>
        </>
      )}

      <CustomEscape brandId={brandId} block="policy" placeholder="例如：買滿三個月的顧客，第四個月送一包隨身包" onOption={addCustom} />
    </EvidenceCard>
  );
}

function ChosenRow({ policy, spec, onParam, onRemove }: {
  policy: ChosenPolicy;
  spec: PolicyType | undefined;
  onParam: (target: ChosenPolicy, name: string, value: string) => void;
  onRemove: () => void;
}) {
  const baseId = useId();
  const params = spec?.params ?? [];
  return (
    <Item className="items-start" data-policy={policy.key}>
      <Chip tone={policy.offer_key && policy.offer_key !== "none" ? "ok" : "neutral"} className="mt-1.5">{policy.label}</Chip>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap gap-2">
          {params.length > 0 ? params.map((param) => (
            <div key={param.name} className="min-w-[150px] flex-1">
              <label htmlFor={`${baseId}-${param.name}`} className="mb-1 block text-xs text-muted-foreground">{param.label}</label>
              <input
                id={`${baseId}-${param.name}`}
                className={INPUT}
                inputMode={param.kind === "text" ? undefined : "decimal"}
                value={String(policy.params[param.name] ?? "")}
                onChange={(e) => onParam(policy, param.name, e.target.value)}
              />
            </div>
          )) : (
            <span className="pt-1.5 text-[12.5px] text-muted-foreground">{policy.key === "custom" ? policy.sentence : "不用填"}</span>
          )}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-0.5 text-[11.5px] text-muted-foreground">
          廣告裡會當成：<b className="font-semibold text-foreground">{policy.offer_label}</b>・
          {policy.origin === "ai" ? <AiTag source="ai" note={policy.note} /> : <CustomMark>{policy.origin === "custom" ? "你自訂" : "你選的"}</CustomMark>}
        </div>
      </div>
      <RemoveButton label={policy.label} onClick={onRemove} />
    </Item>
  );
}

// ---- the step's shared pieces (prototype `.card` + `.hd`, `.it`, `.chip`, `.sec`, `.mine`, `.x`, `.in`) ----

export const INPUT =
  "w-full rounded-lg border border-input bg-card px-3 py-[9px] text-sm focus:border-primary focus:shadow-[0_0_0_3px_var(--color-accent)] focus:outline-none focus-visible:outline-none";

export function EvidenceCard({ title, note, aside, slot, children }: {
  title: string;
  note?: string;
  aside?: ReactNode;
  slot: string;
  children: ReactNode;
}) {
  return (
    <section data-slot={slot} aria-label={title} className="rounded-xl border border-border bg-card px-[22px] py-5">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {note && <span className="text-[12.5px] text-muted-foreground">{note}</span>}
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Item({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("mt-2 flex items-center gap-2.5 rounded-[10px] border border-border bg-card px-3 py-2.5", className)} {...props} />;
}

const CHIP_TONE = { neutral: "bg-muted text-muted-foreground", ok: "bg-zone-ok text-success" } as const;

export function Chip({ tone = "neutral", className, ...props }: ComponentProps<"span"> & { tone?: keyof typeof CHIP_TONE }) {
  return (
    <span
      data-slot="chip"
      data-tone={tone}
      className={cn("inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap", CHIP_TONE[tone], className)}
      {...props}
    />
  );
}

export function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" aria-label={`拿掉「${label}」`} className="rounded p-1 text-lg leading-none text-muted-foreground hover:text-foreground" onClick={onClick}>
      ×
    </button>
  );
}

function SecLabel({ className, children }: { className?: string; children: ReactNode }) {
  return <p className={cn("mb-2 text-xs font-semibold text-muted-foreground", className)}>{children}</p>;
}
