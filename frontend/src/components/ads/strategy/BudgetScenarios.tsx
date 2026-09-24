import { useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { selectScenario, setBudgetCap, type BudgetScenarioRow, type CampaignDetail } from "@/lib/adsApi";
import { Chip, ConfirmSheet, Disclosure, ScenarioBars, WarnButton, formatAmount, type ScenarioRow } from "../patterns";

/** F28-I09: the strategy tab's 「這一期的總預算」 card (prototype v9 `budgetBlock()`): the API's budget scenarios as bars
 * against the campaign's budget cap (`budget_cap`, `over_cap`, the 照預算上限 row — Feature F28 "Budget scenarios"),
 * the budget cap edited in place (`setBudgetCap`), and the over-cap confirmation. Internal campaigns only.
 *
 * Nothing is preselected: the highlighted row is the user's unsaved pick, else the saved row, else none (§1.7 item 3).
 * A row over the budget cap is never picked directly — it opens the confirm sheet, and only its second yes saves it
 * (`confirm_over_cap: true`). The in-cap pick is saved by the tab's bottom bar (「儲存預算 X」). */

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

function periodDays(start: string | null, end: string | null): number | null {
  if (!start || !end) return null;
  const days = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 86_400_000) + 1;
  return days > 0 ? days : null;
}

/** The row the campaign has saved: same key AND the same money. A cap row whose total moved with a new budget cap is
 * no longer what was saved, so it does not wear 已儲存 (the header chip prints the saved amount instead). */
export function savedRowKey(c: CampaignDetail): string | null {
  const rows = c.budget_basis_json.scenarios?.scenarios ?? [];
  const row = rows.find((r) => r.key === c.budget_scenario && r.total !== null && r.total === c.budget_planned);
  return row ? row.key : null;
}

export function scenarioRow(c: CampaignDetail, key: string | null): BudgetScenarioRow | null {
  if (!key) return null;
  return c.budget_basis_json.scenarios?.scenarios.find((r) => r.key === key) ?? null;
}

export function BudgetScenarios({ brandId, campaign: c, picked, onPick, pending, onPending, onCampaignChange }: {
  brandId: string;
  campaign: CampaignDetail;
  picked: string | null;
  onPick: (key: string | null) => void;
  pending: OverCapPending | null;
  onPending: (pending: OverCapPending | null) => void;
  onCampaignChange: (campaign: CampaignDetail) => void;
}) {
  const scenarios = c.budget_basis_json.scenarios;
  const budgetCap = scenarios?.budget_cap ?? null;
  const saved = savedRowKey(c);
  const [capEditing, setCapEditing] = useState(false);
  const [capValue, setCapValue] = useState("");
  const [capSaving, setCapSaving] = useState(false);
  const [capError, setCapError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [customValue, setCustomValue] = useState("");
  const [customSaving, setCustomSaving] = useState(false);

  if (!scenarios) return null;

  const rows: ScenarioRow[] = scenarios.scenarios.map((r) => ({
    key: r.key, label: r.label, total: r.total, overCap: r.over_cap,
    recommended: r.key === scenarios.recommended, saved: r.key === saved,
  }));
  const days = periodDays(c.start_date, c.end_date);
  const pickedRow = scenarioRow(c, picked);
  const keepTotal = pickedRow?.total ?? c.budget_planned;
  // Saved money that no row carries any more (a 自己填 total, or a cap row that moved): said once, in the header.
  const savedOff = saved === null && c.budget_planned !== null ? c.budget_planned : null;
  const savedOffOver = savedOff !== null && budgetCap !== null && savedOff > budgetCap ? savedOff - budgetCap : 0;

  function choose(key: string) {
    const row = scenarioRow(c, key);
    if (!row || row.total === null) return;
    setError(null);
    if (key === saved) { onPick(null); onPending(null); return; }
    if ((row.over_cap ?? 0) > 0) {
      onPending({ key, label: row.label, total: row.total, over: row.over_cap as number, customTotal: null });
      return;
    }
    onPending(null);
    onPick(key);
  }

  async function confirmOver() {
    if (!pending) return;
    setConfirming(true);
    setError(null);
    try {
      onCampaignChange(await selectScenario(brandId, c.id, { scenario_key: pending.key, custom_total: pending.customTotal }, { confirmOverCap: true }));
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
      onCampaignChange(await selectScenario(brandId, c.id, { scenario_key: "custom", custom_total: total }));
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
              <Button variant="outline" size="sm" disabled={!capValid || capSaving} onClick={() => void saveCap()}>{capSaving ? "儲存中…" : "儲存"}</Button>
              <Button variant="ghost" size="sm" disabled={capSaving} onClick={() => { setCapEditing(false); setCapError(null); }}>取消</Button>
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

      <ScenarioBars rows={rows} budgetCap={budgetCap} selected={picked ?? saved} onSelect={choose} resultCap={c.cap.value} />

      {pending && (
        <ConfirmSheet
          variant="over-cap"
          title={`選「${pending.label} ${fmt(pending.total)}」會超出預算上限 ${fmt(pending.over)} 元`}
          split={budgetCap !== null ? { within: budgetCap, over: pending.over } : undefined}
          actions={(
            <>
              <Button variant="outline" disabled={confirming} onClick={() => { onPending(null); setError(null); }}>
                {keepTotal !== null ? `維持 ${fmt(keepTotal)}` : "先不選"}
              </Button>
              <WarnButton disabled={confirming} onClick={() => void confirmOver()}>{confirming ? "儲存中…" : "超出預算上限也要用"}</WarnButton>
            </>
          )}
        />
      )}
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}

      <div className="mt-3 flex flex-col gap-2">
        <Disclosure label="為什麼是這幾個數字">
          <div className="text-sm leading-7 text-muted-foreground">
            {scenarios.scenarios.map((r) => <div key={r.key}>{r.label}：{r.caption}</div>)}
            {c.cap.value !== null && <div>約幾筆購買＝總額 ÷ 每筆上限；每筆都花到上限時的估計</div>}
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
            <Button variant="outline" disabled={customSaving || confirming || !WHOLE.test(customValue.trim())} onClick={() => void applyCustom()}>
              {customSaving ? "儲存中…" : "套用"}
            </Button>
            {customValue.trim() !== "" && !WHOLE.test(customValue.trim()) && <span className="text-xs text-danger">請填大於 0 的整數金額</span>}
          </div>
        </Disclosure>
      </div>
    </section>
  );
}
