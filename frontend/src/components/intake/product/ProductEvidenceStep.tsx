import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "@/components/layout/ui/button";
import type { OnboardingSource, ProofKind } from "@/lib/intakeOnboardingApi";
import type { ClaimVerdict, ProductClaim, ProductEvidence, ProductEvidenceInput } from "@/lib/intakeProductApi";
import { fetchProductEvidence, proposeProductCustom, saveProductEvidence } from "@/lib/intakeProductApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { cn } from "@/lib/utils";
import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";
import { AiTag } from "../shared/AiTag";
import { CustomEscape, CustomMark } from "../shared/CustomEscape";
import { clearStepDraft, productDraftKey, readStepDraft, useStepDraft } from "../shared/stepDraft";
import { Chip, EvidenceCard, INPUT, Item, RemoveButton } from "../steps/PolicyCard";

/** Product proof kinds the prototype always offers as an empty input when nothing of that kind is listed. */
const PROOF_SLOTS: { kind: ProofKind; placeholder: string }[] = [
  { kind: "expert_endorsement", placeholder: "誰、什麼身分、說了什麼；沒有就留空" },
];

interface ProofRow {
  uid: number;
  id: string | null;
  fact_key: ProofKind;
  text: string;
  /** The text as loaded: the read's tag stays only while the text is unchanged. */
  loadedText: string;
  origin: Exclude<OnboardingSource, "none"> | "custom";
  note: string;
  editing: boolean;
}

interface ClaimRow {
  uid: number;
  id: string | null;
  text: string;
  fromNote: string;
  verdict: ClaimVerdict | null;
  statutory: ProductClaim["statutory"];
  /** Set by 「自訂」 on this visit: marked 「你自訂」. */
  custom: boolean;
  /** Appended by 「自訂」 (not a row that was already listed): its × is the undo. */
  added: boolean;
}

/** Product onboarding `#/p3` 證據與說法 (prototype `R.p3` of `.harness/scratch/prototype/f41-onboarding/index.html`):
 * the product's own proof (AI-found rows + an empty 專家背書 input, 自訂 `product_proof`) and one 可以講／不能講
 * decision per claim found on the page or in reviews (自訂 `claim`). A 食安法 hit (`statutory`) is a reminder only
 * (F48 decision 13, F34 remind-only): the row is red with its law line, the 可以講／不能講 choice stays the user's and
 * is sent as chosen. 下一步 stays disabled with 「還有 N 句沒選」 while a claim is unset,
 * then sends both lists in full through `PUT …/onboarding/evidence` and moves on only after the server confirmed. */
export function ProductEvidenceStep({ brandId, productId, nav, back, onNext }: {
  brandId: string;
  productId: string;
  nav: StepNav;
  back: BarBack;
  onNext: () => void;
}) {
  const [loaded, setLoaded] = useState<ProductEvidence | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [proof, setProof] = useState<ProofRow[]>([]);
  const [slots, setSlots] = useState<Partial<Record<ProofKind, string>>>({});
  const [claims, setClaims] = useState<ClaimRow[]>([]);
  /** What the step loaded: the draft is kept only while the lists differ from it (F47-I03). */
  const [loadedDraft, setLoadedDraft] = useState<EvidenceDraft | null>(null);
  const uid = useRef(0);
  const draftKey = productDraftKey(brandId, productId, "evidence");

  useEffect(() => {
    let cancelled = false;
    fetchProductEvidence(brandId, productId)
      .then((evidence) => {
        if (cancelled) return;
        const fromServer: EvidenceDraft = {
          proof: evidence.proof.map((p) => ({
            id: p.id, fact_key: p.fact_key, text: p.text, loadedText: p.text,
            origin: p.source === "ai" ? "ai" : "saved", note: p.note, editing: false,
          })),
          slots: {},
          claims: evidence.claims.map((c) => ({
            id: c.id, text: c.text, fromNote: c.from_note,
            verdict: c.verdict, statutory: c.statutory, custom: false, added: false,
          })),
        };
        // F47-I03 (drill-10 乙 #1, b-04): unsaved edits come back when the step mounts again (back, step bar,
        // reload) until 下一步 saved them.
        const shown = readStepDraft(draftKey, isEvidenceDraft) ?? fromServer;
        setLoadedDraft(fromServer);
        setLoaded(evidence);
        setProof(shown.proof.map((p) => ({ ...p, uid: uid.current++ })));
        setSlots(shown.slots);
        setClaims(shown.claims.map((c) => ({ ...c, uid: uid.current++ })));
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。");
      });
    return () => {
      cancelled = true;
    };
  }, [brandId, productId, draftKey]);

  const kindLabel = useMemo(() => new Map((loaded?.proof_kinds ?? []).map((k) => [k.key, k.label])), [loaded]);
  const openSlots = PROOF_SLOTS.filter((s) => !proof.some((p) => p.fact_key === s.kind));
  const unset = claims.filter((c) => c.verdict === null).length;
  useStepDraft(draftKey, loaded !== null, {
    proof: proof.map(({ uid: _uid, ...row }) => row),
    slots,
    claims: claims.map(({ uid: _uid, ...row }) => row),
  }, loadedDraft);

  const { saving, error, submit, formProps } = useFormSubmit(async () => {
    const input: ProductEvidenceInput = {
      proof: [
        ...proof.map((p) => ({ id: p.id, fact_key: p.fact_key, text: p.text.trim() })).filter((p) => p.text),
        ...openSlots.map((s) => ({ fact_key: s.kind, text: (slots[s.kind] ?? "").trim() })).filter((p) => p.text),
      ],
      claims: claims.map((c) => ({ id: c.id, text: c.text, verdict: c.verdict })),
    };
    await saveProductEvidence(brandId, productId, input);
    clearStepDraft(draftKey);
    onNext();
  });

  const head = <OnboardingStepHead {...nav} title="證據與說法" purpose="廣告只講你說可以講的" />;

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
  const setVerdict = (row: ClaimRow, verdict: ClaimVerdict) =>
    setClaims((prev) => prev.map((c) => (c.uid === row.uid ? { ...c, verdict } : c)));
  const addClaim = (option: { text: string; verdict: ClaimVerdict; statutory: ProductClaim["statutory"] }) => {
    const { verdict } = option; // the proposal's own verdict; `statutory` only adds the reminder
    setClaims((prev) => {
      if (prev.some((c) => c.text === option.text)) {
        return prev.map((c) => (c.text === option.text ? { ...c, verdict, statutory: option.statutory, custom: true } : c));
      }
      const row: ClaimRow = {
        uid: uid.current++, id: null, text: option.text, fromNote: "", verdict, statutory: option.statutory, custom: true, added: true,
      };
      return [...prev, row];
    });
  };

  return (
    <form
      className="flex flex-col gap-4"
      {...formProps}
      onSubmit={(e) => {
        e.preventDefault();
        if (loaded && !saving && unset === 0) void submit();
      }}
    >
      {head}
      {loaded && (
        <>
          <EvidenceCard title="這個商品的證據" slot="product-proof-card">
            {proof.map((row) => {
              const label = kindLabel.get(row.fact_key) ?? row.fact_key;
              const quote = row.fact_key === "customer_review";
              const tag = row.origin === "custom"
                ? <CustomMark />
                : row.origin === "ai" && row.text === row.loadedText ? <AiTag source="ai" note={row.note} /> : null;
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
                    {quote ? (
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-0.5 text-[11.5px] text-muted-foreground">
                        原話照搬，不改寫{tag && <>・{tag}</>}
                      </div>
                    ) : (
                      tag && <div className="mt-0.5">{tag}</div>
                    )}
                  </div>
                  {!row.editing && (
                    <Button type="button" variant="link" className="h-auto p-0 text-[13px]" aria-label={`改「${row.text}」`} onClick={() => editProof(row, { editing: true })}>
                      改
                    </Button>
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
              block="product_proof"
              placeholder="例如：營養師朋友在 IG 推薦過，有截圖"
              propose={(text) => proposeProductCustom(brandId, productId, "product_proof", text)}
              onOption={({ fact_key, text }) => {
                const row: ProofRow = {
                  uid: uid.current++, id: null, fact_key, text, loadedText: text, origin: "custom", note: "", editing: false,
                };
                setProof((prev) => [...prev, row]);
              }}
            />
          </EvidenceCard>

          <EvidenceCard title="這些話可以在廣告裡講嗎" note="網站和評論上找到的說法" slot="claims-card">
            {claims.map((row) => (
              <ClaimItem
                key={row.uid}
                row={row}
                onVerdict={(verdict) => setVerdict(row, verdict)}
                onRemove={row.added ? () => setClaims((prev) => prev.filter((c) => c.uid !== row.uid)) : undefined}
              />
            ))}
            <CustomEscape
              brandId={brandId}
              block="claim"
              placeholder="例如：我想講「一天一顆就夠」，可以嗎？"
              propose={(text) => proposeProductCustom(brandId, productId, "claim", text)}
              onOption={addClaim}
            />
          </EvidenceCard>
        </>
      )}

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      <OnboardingBar back={back} hint={unset > 0 ? `還有 ${unset} 句沒選` : undefined}>
        <BarNext type="submit" label="下一步" busy={!loaded || saving} disabledReason={unset > 0 ? "先確認每條說法是否要使用" : null} />
      </OnboardingBar>
    </form>
  );
}

/** This step's draft (F47-I03, `useStepDraft`): both lists and the open slots, without render keys. */
interface EvidenceDraft {
  proof: Omit<ProofRow, "uid">[];
  slots: Partial<Record<ProofKind, string>>;
  claims: Omit<ClaimRow, "uid">[];
}

function isEvidenceDraft(value: unknown): value is EvidenceDraft {
  const v = value as Record<string, unknown>;
  const rows = (list: unknown, ok: (row: Record<string, unknown>) => boolean) =>
    Array.isArray(list) && list.every((row) => !!row && typeof row === "object" && ok(row as Record<string, unknown>));
  return typeof v === "object" && !!v.slots && typeof v.slots === "object"
    && rows(v.proof, (r) => typeof r.text === "string" && typeof r.fact_key === "string" && typeof r.loadedText === "string")
    && rows(v.claims, (r) => typeof r.text === "string" && (r.verdict === null || r.verdict === "ok" || r.verdict === "no"));
}

/** Prototype `.it` of the claims card: text, 「來自〈from_note〉」 and the 可以講／不能講 segmented control (amber while
 * unset). A 食安法 hit is a reminder only (F48 decision 13): the row is red with its law line, the control stays
 * enabled and the reminder stays visible whatever the user picks. */
function ClaimItem({ row, onVerdict, onRemove }: {
  row: ClaimRow;
  onVerdict: (verdict: ClaimVerdict) => void;
  onRemove?: () => void;
}) {
  const law = row.statutory;
  const origin = row.fromNote ? `來自${row.fromNote}` : "";
  return (
    <Item
      data-claim={row.verdict === null ? "unset" : "set"}
      data-statutory={law ? law.term : undefined}
      className={cn(law && "border-danger/30 bg-zone-over/40", !law && row.verdict === null && "border-warning/30 bg-zone-watch/40")}
    >
      <div className="min-w-0 flex-1">
        <b className="font-semibold [overflow-wrap:anywhere]">{row.text}</b>
        {(origin || law) && (
          <div className="text-[11.5px] text-muted-foreground">
            {origin}
            {origin && law && "・"}
            {law && <span className="text-danger">{law.sentence}</span>}
          </div>
        )}
        {row.custom && <div className="mt-0.5"><CustomMark /></div>}
      </div>
      <VerdictSegmented label={row.text} value={row.verdict} onChange={onVerdict} />
      {onRemove && <RemoveButton label={row.text} onClick={onRemove} />}
    </Item>
  );
}

const VERDICTS: { key: ClaimVerdict; label: string }[] = [
  { key: "ok", label: "可以講" },
  { key: "no", label: "不能講" },
];

/** Prototype `.seg` (`.on`, `.on.no`): one-of 可以講／不能講, radio keyboard pattern (the picked option is the tab
 * stop; nothing picked → the first). */
function VerdictSegmented({ label, value, onChange }: {
  label: string;
  value: ClaimVerdict | null;
  onChange: (verdict: ClaimVerdict) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const stop = value ?? VERDICTS[0].key;
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(e.key) || !ref.current) return;
    e.preventDefault();
    const radios = Array.from(ref.current.querySelectorAll<HTMLButtonElement>("[role=radio]"));
    const at = radios.indexOf(document.activeElement as HTMLButtonElement);
    const next = (at + 1) % radios.length; // two options: every arrow moves to the other one
    radios[next].focus();
    onChange(VERDICTS[next].key);
  };
  return (
    <div
      ref={ref}
      data-slot="segmented"
      role="radiogroup"
      aria-label={label}
      onKeyDown={onKeyDown}
      className="inline-flex shrink-0 overflow-hidden rounded-lg border border-border"
    >
      {VERDICTS.map((o, i) => {
        const on = o.key === value;
        return (
          <button
            key={o.key}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={o.key === stop ? 0 : -1}
            onClick={() => onChange(o.key)}
            className={cn(
              "px-3 py-[5px] text-[12.5px] font-medium whitespace-nowrap",
              i > 0 && "border-l border-border",
              on ? (o.key === "no" ? "bg-danger text-primary-foreground" : "bg-primary text-primary-foreground") : "bg-card hover:text-primary",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
