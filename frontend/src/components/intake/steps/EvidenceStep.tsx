import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { brandDraftKey, clearStepDraft, readStepDraft, useStepDraft } from "../shared/stepDraft";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import type { OnboardingEvidence, OnboardingEvidenceInput, OnboardingSource, PolicyParamValue, ProofKind } from "@/lib/intakeOnboardingApi";
import { fetchOnboardingEvidence, saveOnboardingEvidence } from "@/lib/intakeOnboardingApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";
import { AiTag } from "../shared/AiTag";
import { CustomEscape, CustomMark } from "../shared/CustomEscape";
import {
  blockingReason, Chip, chosenFromItem, EvidenceCard, INPUT, Item, PolicyCard, RemoveButton,
  type ChosenPolicy, type CoolingOff,
} from "./PolicyCard";

/** Brand-level proof kinds the prototype always offers as empty inputs when nothing of that kind is listed. */
const PROOF_SLOTS: { kind: ProofKind; placeholder: string }[] = [
  { kind: "media_coverage", placeholder: "哪個媒體、哪一天報導；沒有就留空" },
  { kind: "sales_numbers", placeholder: "例如：累積賣出 12,000 盒（後台可查）；沒有就留空" },
];

interface ProofRow {
  uid: number;
  id: string | null;
  fact_key: ProofKind;
  text: string;
  /** The text as loaded: the scan's tag stays only while the text is unchanged. */
  loadedText: string;
  origin: Exclude<OnboardingSource, "none"> | "custom";
  note: string;
  editing: boolean;
}

interface ForbiddenRow {
  uid: number;
  text: string;
  /** Added through 「自訂」 on this visit (marked 「你自訂」 instead of 「你自己加的」). */
  custom: boolean;
}

interface EvidenceDraft {
  proof: ProofRow[];
  slots: Partial<Record<ProofKind, string>>;
  policies: ChosenPolicy[];
  cooling: CoolingOff;
  forbidden: ForbiddenRow[];
}
function isEvidenceDraft(value: unknown): value is EvidenceDraft {
  if (!value || typeof value !== "object") return false;
  const d = value as EvidenceDraft;
  return Array.isArray(d.proof) && d.proof.every((p) => p && typeof p.uid === "number" && typeof p.text === "string" && typeof p.fact_key === "string")
    && !!d.slots && typeof d.slots === "object" && Object.values(d.slots).every((v) => typeof v === "string")
    && Array.isArray(d.policies) && d.policies.every((p) => p && typeof p.key === "string" && !!p.params && typeof p.params === "object")
    && !!d.cooling && typeof d.cooling.applies === "boolean" && typeof d.cooling.disclosure === "string"
    && Array.isArray(d.forbidden) && d.forbidden.every((f) => f && typeof f.uid === "number" && typeof f.text === "string");
}

/** Brand onboarding `#/b4` 品牌的證據與政策 (prototype `R.b4` of `.harness/scratch/prototype/f41-onboarding/index.html`):
 * brand-level proof (AI-found rows + empty 媒體報導／銷售數據 inputs), 全店政策 (`PolicyCard`) and the brand's own
 * 不能講的話, each block ending with 「自訂」. 下一步 sends every list in full through `PUT …/onboarding/evidence`
 * and moves on only after the server confirmed; a chosen policy with an empty required param (or a 不適用
 * cooling-off without its text) blocks it with the reason in the bar. */
export function EvidenceStep({ nav, back, onNext }: { nav: StepNav; back?: BarBack; onNext: () => void }) {
  const { brandId = "" } = useParams<{ brandId: string }>();
  const { scope } = useWorkspace();
  const draftKey = brandDraftKey(scope, brandId, "evidence");
  const [baseline, setBaseline] = useState<EvidenceDraft | null>(null);
  const [loaded, setLoaded] = useState<OnboardingEvidence | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [proof, setProof] = useState<ProofRow[]>([]);
  const [slots, setSlots] = useState<Partial<Record<ProofKind, string>>>({});
  const [policies, setPolicies] = useState<ChosenPolicy[]>([]);
  const [cooling, setCooling] = useState<CoolingOff>({ applies: true, disclosure: "" });
  const [forbidden, setForbidden] = useState<ForbiddenRow[]>([]);
  const uid = useRef(0);

  useEffect(() => {
    let cancelled = false;
    fetchOnboardingEvidence(brandId)
      .then((evidence) => {
        if (cancelled) return;
        setLoaded(evidence);
        const saved: EvidenceDraft = {
          proof: evidence.proof.map((p) => ({
            uid: uid.current++, id: p.id, fact_key: p.fact_key, text: p.text, loadedText: p.text,
            origin: p.source === "ai" ? "ai" : "saved", note: p.note, editing: false,
          })),
          slots: {}, policies: evidence.policies.map(chosenFromItem),
          cooling: { applies: evidence.cooling_off.applies, disclosure: evidence.cooling_off.disclosure },
          forbidden: evidence.forbidden.map((f) => ({ uid: uid.current++, text: f.text, custom: false })),
        };
        setBaseline(saved);
        const draft = readStepDraft(draftKey, isEvidenceDraft) ?? saved;
        setProof(draft.proof); setSlots(draft.slots); setPolicies(draft.policies);
        setCooling(draft.cooling); setForbidden(draft.forbidden);
        uid.current = Math.max(uid.current, ...draft.proof.map((p) => p.uid + 1), ...draft.forbidden.map((f) => f.uid + 1));
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。");
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  useStepDraft(draftKey, loaded !== null, { proof, slots, policies, cooling, forbidden }, baseline);

  const prefilled = useMemo(
    () => new Map((loaded?.policies ?? []).filter((p) => p.key !== "custom").map((p) => [p.key, chosenFromItem(p)])),
    [loaded],
  );
  const kindLabel = useMemo(() => new Map((loaded?.proof_kinds ?? []).map((k) => [k.key, k.label])), [loaded]);
  const openSlots = PROOF_SLOTS.filter((s) => !proof.some((p) => p.fact_key === s.kind));
  const reason = loaded ? blockingReason(policies, loaded.policy_types, cooling) : null;

  const { saving, error, submit } = useFormSubmit(async () => {
    const input: OnboardingEvidenceInput = {
      proof: [
        ...proof.map((p) => ({ id: p.id, fact_key: p.fact_key, text: p.text.trim() })).filter((p) => p.text),
        ...openSlots.map((s) => ({ fact_key: s.kind, text: (slots[s.kind] ?? "").trim() })).filter((p) => p.text),
      ],
      policies: policies.map((p) => (p.key === "custom"
        ? { key: p.key, params: p.params, sentence: p.sentence }
        : { key: p.key, params: filled(p.params) })),
      cooling_off: cooling.applies ? { applies: true } : { applies: false, disclosure: cooling.disclosure.trim() },
      forbidden: forbidden.map((f) => f.text.trim()).filter(Boolean),
    };
    await saveOnboardingEvidence(brandId, input);
    clearStepDraft(draftKey);
    setBaseline({ proof, slots, policies, cooling, forbidden });
    onNext();
  });

  const head = <OnboardingStepHead {...nav} title="品牌的證據與政策" purpose="廣告只會用這裡記下的；沒記的不會寫、也不會編" />;

  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        {head}
        <p role="alert" className="text-sm text-danger">{loadError}</p>
        <OnboardingBar back={back} />
      </div>
    );
  }

  const editProof = (row: ProofRow, patch: Partial<ProofRow>) =>
    setProof((prev) => prev.map((p) => (p.uid === row.uid ? { ...p, ...patch } : p)));

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (loaded && !saving && !reason) void submit();
      }}
    >
      {head}
      {loaded && (
        <>
          <EvidenceCard title="讓人相信你的東西（品牌層）" note="商品自己的檢驗報告、評論，在商品建檔再問" slot="proof-card">
            {proof.map((row) => {
              const label = kindLabel.get(row.fact_key) ?? row.fact_key;
              return (
                <Item key={row.uid} data-proof={row.fact_key}>
                  <Chip tone="ok">{label}</Chip>
                  <div className="min-w-0 flex-1">
                    {row.editing ? (
                      <input onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); editProof(row, { editing: false }); } }}
                        aria-label={label}
                        className={INPUT}
                        value={row.text}
                        autoFocus
                        onChange={(e) => editProof(row, { text: e.target.value })}
                      />
                    ) : (
                      <b className="font-semibold [overflow-wrap:anywhere]">{row.text}</b>
                    )}
                    {row.origin === "ai" && row.text === row.loadedText && (
                      <div className="mt-0.5"><AiTag source="ai" note={row.note} /></div>
                    )}
                    {row.origin === "custom" && <div className="mt-0.5"><CustomMark /></div>}
                  </div>
                  {!row.editing && (
                    <button type="button" className="text-[13px] font-medium whitespace-nowrap text-primary hover:underline" aria-label={`改「${row.text}」`} onClick={() => editProof(row, { editing: true })}>
                      改
                    </button>
                  )}
                  <RemoveButton label={row.text} onClick={() => setProof((prev) => prev.filter((p) => p.uid !== row.uid))} />
                </Item>
              );
            })}
            {openSlots.map((slot) => {
              const label = kindLabel.get(slot.kind) ?? slot.kind;
              return (
                <Item key={slot.kind} data-proof-slot={slot.kind}>
                  <Chip>{label}</Chip>
                  <div className="min-w-0 flex-1">
                    <input
                      aria-label={label}
                      className={INPUT}
                      placeholder={slot.placeholder}
                      value={slots[slot.kind] ?? ""}
                      onChange={(e) => setSlots((prev) => ({ ...prev, [slot.kind]: e.target.value }))}
                    />
                  </div>
                </Item>
              );
            })}
            <CustomEscape
              brandId={brandId}
              block="brand_proof"
              placeholder="例如：我們上過某某 Podcast、拿過某某市集的評審獎"
              onOption={({ fact_key, text }) => {
                const row: ProofRow = {
                  uid: uid.current++, id: null, fact_key, text, loadedText: text, origin: "custom", note: "", editing: false,
                };
                setProof((prev) => [...prev, row]);
              }}
            />
          </EvidenceCard>

          <PolicyCard
            brandId={brandId}
            types={loaded.policy_types}
            chosen={policies}
            onChange={setPolicies}
            cooling={cooling}
            onCooling={setCooling}
            prefilled={prefilled}
          />

          <EvidenceCard title="不能講的話" slot="forbidden-card" aside={loaded.regime_label ? <Chip>{loaded.regime_label}</Chip> : undefined}>
            {loaded.regime_label && (
              <p className="mb-2 text-[12.5px] text-muted-foreground">已套用食安法常見禁語（治療、預防、改善疾病…）；你自己還有不想講的，加在這裡。</p>
            )}
            {forbidden.map((row) => (
              <Item key={row.uid}>
                <div className="min-w-0 flex-1">
                  <b className="font-semibold [overflow-wrap:anywhere]">{row.text}</b>
                  {row.custom
                    ? <div className="mt-0.5"><CustomMark /></div>
                    : <div className="text-[11.5px] text-muted-foreground">你自己加的</div>}
                </div>
                <RemoveButton label={row.text} onClick={() => setForbidden((prev) => prev.filter((f) => f.uid !== row.uid))} />
              </Item>
            ))}
            <CustomEscape
              brandId={brandId}
              block="forbidden"
              placeholder="例如：不要拿別的品牌比較、不要講「減肥」"
              onOption={({ text }) => {
                setForbidden((prev) => [...prev.filter((f) => f.text !== text), { uid: uid.current++, text, custom: true }]);
              }}
            />
          </EvidenceCard>
        </>
      )}

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      <OnboardingBar back={back}>
        <BarNext type="submit" label="下一步" busy={!loaded || saving} disabledReason={reason} />
      </OnboardingBar>
    </form>
  );
}

/** A registry policy's params as sent: text trimmed, empty (optional) ones left out. */
function filled(params: Record<string, PolicyParamValue>): Record<string, PolicyParamValue> {
  const out: Record<string, PolicyParamValue> = {};
  for (const [name, value] of Object.entries(params)) {
    const v = typeof value === "string" ? value.trim() : value;
    if (v !== "") out[name] = v;
  }
  return out;
}
