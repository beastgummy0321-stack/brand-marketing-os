import { useEffect, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { selectScenario, setBudgetCap, type BudgetScenarioRow, type CampaignDetail, type ResplitRow, type SelectScenarioResult } from "@/lib/adsApi";
import { daysBetween } from "@/lib/orgClock";
import { Chip, ConfirmSheet, Disclosure, ScenarioBars, WarnButton, formatAmount, type ScenarioRow } from "../patterns";
import { BudgetAdviceView } from "./StrategyQualification";

/** F28-I09: the strategy tab's 「這一期的總預算」 card (prototype v9 `budgetBlock()`): the API's budget scenarios as bars
 * against the campaign's budget cap (`budget_cap`, `over_cap`, the 照預算上限 row — Feature F28 "Budget scenarios"),
 * the budget cap edited in place (`setBudgetCap`), and the over-cap confirmation. Internal campaigns only.
 *
 * Nothing is preselected: the highlighted row is the user's unsaved pick, else the saved row, else none (§1.7 item 3).
 * A row over the budget cap is never picked directly — it opens the confirm sheet, and only its second yes saves it
 * (`confirm_over_cap: true`). The in-cap pick is saved by the tab's bottom bar (「儲存預算 X」).
 *
 * F48 Contract M: under the title, the saved total's `budget_preview` — 「每天 X・這期實際 Y」 and the server's note
 * when the whole daily does not spend the chosen total exactly; after a save on an adopted plan, the API's `resplit`
 * (「已照比例重分到 N 個投放組：…」). Every number is served; the card computes no money. */

export interface OverCapPending {
  key: string;
  label: string;
  total: number;
  over: number;
  /** A 自己填 total goes out as `custom_total`; a scenario row sends only its key. */
  customTotal: number | null;
}

const fmt = (v: number | null | undefined) => formatAmount(v) ?? "未知";
const mmdd = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(8, 10)}`;
const errorText = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);
const WHOLE = /^[1-9]\d*$/;
const summaryLabel = (label: string) => Array.from(label).length > 20 ? `${Array.from(label).slice(0, 20).join("")}…` : label;

function periodDays(start: string | null, end: string | null): number | null {
  if (!start || !end) return null;
  const days = daysBetween(start, end);
  return days !== null && days > 0 ? days : null;
}

/** The row the campaign has saved: same key AND the same money. A cap row whose total moved with a new budget cap is
 * no longer what was saved, so it does not wear 已儲存 (the header chip prints the saved amount instead). */
function savedRowKey(c: CampaignDetail): string | null {
  const rows = c.budget_basis_json.scenarios?.scenarios ?? [];
  const row = rows.find((r) => r.key === c.budget_scenario && selectableScenario(r) && r.total === c.budget_planned);
  return row ? row.key : null;
}

/** Scenario source money must match the existing TWD planning interface. Legacy units stay unknown. */
export function selectableScenario(row: BudgetScenarioRow | null | undefined): boolean {
  return row?.currency === "TWD" && row.total !== null && Number.isFinite(row.total) && row.total > 0;
}

function scenarioRow(c: CampaignDetail, key: string | null): BudgetScenarioRow | null {
  if (!key) return null;
  return c.budget_basis_json.scenarios?.scenarios.find((r) => r.key === key) ?? null;
}

/** 「已照比例重分到 N 個投放組：〈role〉 before → after、…」: each re-split ad set under its role's served label (the
 * strategy's allocation row), else its group name. */
function ResplitNote({ c, rows }: { c: CampaignDetail; rows: ResplitRow[] }) {
  const roleLabel = (row: ResplitRow) =>
    c.budget_basis_json.strategy?.allocation.find((a) => a.role === row.role)?.label
    ?? c.groups.find((g) => g.id === row.group_id)?.name ?? row.role;
  return (
    <p role="status" data-slot="budget-resplit" className="mt-2 text-sm [overflow-wrap:anywhere]">
      已照比例重分到 {rows.length} 個投放組：
      {rows.map((row) => `${roleLabel(row)} ${fmt(row.before)} → ${fmt(row.after)}`).join("、")}
    </p>
  );
}

export function BudgetScenarios({ brandId, campaign: c, picked, onPick, pending, onPending, onCampaignChange, onBudgetSaved, resplit = null }: {
  brandId: string;
  campaign: CampaignDetail;
  picked: string | null;
  onPick: (key: string | null) => void;
  pending: OverCapPending | null;
  onPending: (pending: OverCapPending | null) => void;
  onCampaignChange: (campaign: CampaignDetail) => void;
  /** A total was saved (`selectScenario`): the returned campaign and its re-split list. */
  onBudgetSaved: (result: SelectScenarioResult) => void;
  /** The ad sets the last save re-split (an adopted, unbound plan); null when nothing was re-split. */
  resplit?: ResplitRow[] | null;
}) {
  const scenarios = c.budget_basis_json.scenarios;
  const budgetCap = scenarios?.budget_cap ?? null;
  const saved = savedRowKey(c);
  const preview = c.budget_preview ?? null;
  const [capEditing, setCapEditing] = useState(false);
  const [capValue, setCapValue] = useState("");
  const [capSaving, setCapSaving] = useState(false);
  const [capError, setCapError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [customValue, setCustomValue] = useState("");
  const [customSaving, setCustomSaving] = useState(false);

  const pendingRow = scenarioRow(c, pending?.key ?? null);
  const pendingCurrent = pending !== null && (pending.customTotal !== null
    ? budgetCap !== null && pending.customTotal - budgetCap === pending.over
    : selectableScenario(pendingRow) && pendingRow?.total === pending.total && pendingRow.over_cap === pending.over);
  useEffect(() => {
    if (pending && !pendingCurrent) {
      onPending(null);
      setError("預算選項或上限已更新，請重新選擇並確認金額。");
    }
  }, [pending, pendingCurrent, onPending]);

  if (!scenarios) return null;

  const advice = c.budget_advice !== undefined ? c.budget_advice : scenarios.advice !== undefined
    ? scenarios.advice : c.budget_basis_json.strategy?.decision?.budget_advice;
  const compatible = scenarios.scenarios.filter(r => r.currency === "TWD" && (r.total === null || selectableScenario(r)));
  const references = scenarios.scenarios.filter(r => !compatible.includes(r));
  const rows: ScenarioRow[] = compatible.map((r) => ({
    key: r.key, label: summaryLabel(r.label), total: r.total, overCap: r.over_cap, caption: r.caption,
    recommended: advice?.state === "retain" && r.key === scenarios.recommended && r.key === advice.recommended_key, saved: r.key === saved,
  }));
  const days = periodDays(c.start_date, c.end_date);
  const pickedRow = scenarioRow(c, picked);
  const keepTotal = pickedRow?.total ?? c.budget_planned;
  // Saved money that no row carries any more (a 自己填 total, or a cap row that moved): said once, in the header.
  const savedOff = saved === null && c.budget_planned !== null ? c.budget_planned : null;
  const savedOffOver = savedOff !== null && budgetCap !== null && savedOff > budgetCap ? savedOff - budgetCap : 0;

  function choose(key: string) {
    const row = scenarioRow(c, key);
    if (!row || !selectableScenario(row) || row.total === null) return;
    setError(null);
    if (key === saved) { onPick(null); onPending(null); return; }
    if (row.over_cap !== null && row.over_cap > 0) {
      onPending({ key, label: row.label, total: row.total, over: row.over_cap as number, customTotal: null });
      return;
    }
    onPending(null);
    onPick(key);
  }

  async function confirmOver() {
    if (!pending || !pendingCurrent) return;
    setConfirming(true);
    setError(null);
    try {
      onBudgetSaved(await selectScenario(brandId, c.id, { scenario_key: pending.key, custom_total: pending.customTotal }, { confirmOverCap: true }));
      onPending(null);
      onPick(null);
      if (pending.customTotal !== null) setCustomValue("");
    } catch (err) {
      setError(errorText(err, "儲存預算失敗，請稍後再試。"));
    } finally {
      setConfirming(false);
    }
  }

  async function applyCustom() {
    if (!WHOLE.test(customValue.trim())) return;
    const total = Number(customValue.trim());
    setError(null);
    if (budgetCap !== null && total > budgetCap) {
      onPick(null);
      onPending({ key: "custom", label: "自己填", total, over: total - budgetCap, customTotal: total });
      return;
    }
    setCustomSaving(true);
    try {
      onBudgetSaved(await selectScenario(brandId, c.id, { scenario_key: "custom", custom_total: total }));
      onPick(null);
      onPending(null);
      setCustomValue("");
    } catch (err) {
      setError(errorText(err, "儲存預算失敗，請稍後再試。"));
    } finally {
      setCustomSaving(false);
    }
  }

  const capTrimmed = capValue.trim();
  const capValid = capTrimmed === "" || WHOLE.test(capTrimmed);

  async function saveCap() {
    if (!capValid) return;
    setCapSaving(true);
    setCapError(null);
    try {
      // Empty clears the cap. The unsaved pick and any open sheet were judged against the old cap, so they go; the
      // saved scenario stays saved and simply shows its new over-cap mark (nothing is re-chosen).
      onCampaignChange(await setBudgetCap(brandId, c.id, capTrimmed === "" ? null : Number(capTrimmed)));
      onPick(null);
      onPending(null);
      setCapEditing(false);
    } catch (err) {
      setCapError(errorText(err, "更新預算上限失敗，請稍後再試。"));
    } finally {
      setCapSaving(false);
    }
  }

  return (
    <section className="surface px-[22px] py-5" aria-labelledby="budget-card-title">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 id="budget-card-title" className="text-[15px] font-semibold">這一期的總預算</h2>
        <div className="flex flex-wrap items-center gap-2">
          {c.start_date && c.end_date && <Chip>{mmdd(c.start_date)} – {mmdd(c.end_date)}{days !== null && `・${days} 天`}</Chip>}
          {savedOff !== null && <Chip tone="ok">已儲存 {fmt(savedOff)}</Chip>}
          {savedOffOver > 0 && <Chip tone="warn">超出預算上限 {fmt(savedOffOver)}</Chip>}
          {capEditing ? (
            <span className="flex flex-wrap items-center gap-2">
              <label className="inline-flex w-[150px] items-center rounded-lg border border-input bg-card px-2.5 focus-within:border-primary focus-within:ring-[3px] focus-within:ring-accent">
                <span className="text-xs text-muted-foreground">NT$</span>
                <input
                  type="number" min={1} step={1} inputMode="numeric" value={capValue} autoFocus
                  aria-label="這一期的預算上限（留空＝不設）" placeholder="不設上限"
                  className="numeric w-full border-0 bg-transparent px-1.5 py-1 text-sm font-semibold outline-none"
                  onChange={(e) => setCapValue(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && capValid && !capSaving) void saveCap(); if (e.key === "Escape") setCapEditing(false); }}
                />
              </label>
              <Button variant="outline" size="sm" busy={capSaving} disabledReason={!capValid ? "請填大於 0 的整數預算上限" : undefined} onClick={() => void saveCap()}>{capSaving ? "儲存中…" : "儲存"}</Button>
              <Button variant="ghost" size="sm" busy={capSaving} onClick={() => { setCapEditing(false); setCapError(null); }}>取消</Button>
            </span>
          ) : (
            <>
              {budgetCap !== null ? <Chip tone="accent">你的預算上限 {fmt(budgetCap)}</Chip> : <Chip>沒設預算上限</Chip>}
              <Button
                variant="link" size="sm" className="h-auto px-0"
                onClick={() => { setCapValue(budgetCap !== null ? String(budgetCap) : ""); setCapError(null); setCapEditing(true); }}
              >
                {budgetCap !== null ? "改預算上限" : "設預算上限"}
              </Button>
            </>
          )}
        </div>
        {capEditing && !capValid && <p role="alert" className="w-full text-right text-xs text-danger">預算上限要是大於 0 的整數；留空＝不設上限。</p>}
        {capError && <p role="alert" className="w-full text-right text-xs text-danger">{capError}</p>}
      </div>

      {preview && preview.daily !== null && preview.total !== null && (
        <p data-slot="budget-preview" className="-mt-1.5 mb-3 text-[13px]">
          <span className="numeric">每天 {fmt(preview.daily)}・這期實際 {fmt(preview.total)}</span>
          {preview.note && <span className="ml-2 text-muted-foreground">{preview.note}</span>}
        </p>
      )}

      <BudgetAdviceView advice={advice} legacyRecommendation={scenarios.recommended !== null} />
      {rows.length > 0 && <>
        <p className="mb-2 text-xs text-muted-foreground">台幣規劃選項（TWD）{scenarios.mode === "history" ? "・歷史倍數僅供金額比較，不代表效果成長" : "・測試金額不代表預期成果"}</p>
        <ScenarioBars rows={rows} budgetCap={budgetCap} selected={picked ?? saved} onSelect={choose} missingText="金額尚未核實" />
      </>}
      {references.map(row => <div key={row.key} data-slot="unselectable-budget" className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2.5 text-sm">
        <div className="min-w-0 [overflow-wrap:anywhere]"><b>{summaryLabel(row.label)}</b><p className="text-xs text-muted-foreground">僅供來源對照，不能套用台幣預算。</p></div>
        <span className="numeric">{row.currency ?? "幣別未知"} {fmt(row.total)}</span>
      </div>)}

      {pending && pendingCurrent && (
        <ConfirmSheet
          variant="over-cap"
          title={`選「${pending.label} ${fmt(pending.total)}」會超出預算上限 ${fmt(pending.over)} 元`}
          split={budgetCap !== null ? { within: budgetCap, over: pending.over } : undefined}
          actions={(
            <>
              {/* Focus moves into the sheet once it opens (prototype `pickSc`), so a keyboard user lands on the safe choice. */}
              <Button variant="outline" autoFocus busy={confirming} onClick={() => { onPending(null); setError(null); }}>
                {keepTotal !== null ? `維持 ${fmt(keepTotal)}` : "先不選"}
              </Button>
              <WarnButton busy={confirming} onClick={() => void confirmOver()}>{confirming ? "儲存中…" : "超出預算上限也要用"}</WarnButton>
            </>
          )}
        />
      )}
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      {resplit && resplit.length > 0 && <ResplitNote c={c} rows={resplit} />}

      <div className="mt-3 flex flex-col gap-2">
        <Disclosure label="為什麼是這幾個數字">
          <div className="text-sm leading-7 text-muted-foreground [overflow-wrap:anywhere]">
            {scenarios.scenarios.map((r) => <div key={r.key}>{r.label}：{r.caption}</div>)}
            {scenarios.mode === "history" && <div>歷史倍數僅供比較，不能據此推定成長或加碼。</div>}
          </div>
        </Disclosure>
        <Disclosure label="自己填總額">
          <div className="flex flex-wrap items-center gap-2">
            <label className="inline-flex w-[180px] items-center rounded-lg border border-input bg-card px-3 focus-within:border-primary focus-within:ring-[3px] focus-within:ring-accent">
              <span className="text-muted-foreground">NT$</span>
              <input
                type="number" min={1} step={1} inputMode="numeric" value={customValue} aria-label="自己填這一期的總預算"
                className="numeric w-full border-0 bg-transparent px-2 py-2 text-base font-semibold outline-none"
                onChange={(e) => setCustomValue(e.target.value)}
              />
            </label>
            <Button variant="outline" busy={customSaving || confirming} disabledReason={!WHOLE.test(customValue.trim()) ? "請填大於 0 的整數預算" : undefined} onClick={() => void applyCustom()}>
              {customSaving ? "儲存中…" : "套用"}
            </Button>
            {customValue.trim() !== "" && !WHOLE.test(customValue.trim()) && <span className="text-xs text-danger">請填大於 0 的整數金額</span>}
          </div>
        </Disclosure>
      </div>
    </section>
  );
}
