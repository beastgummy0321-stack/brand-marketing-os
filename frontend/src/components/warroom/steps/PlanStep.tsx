import { useEffect, useState } from "react";
import {
  approvePlan,
  decideDissent,
  fetchPlanOptions,
  fetchRuleCardsLearned,
  selectPlanOption,
  startPlanGeneration,
  updatePacing,
  AUDIENCE_TIER_LABELS,
  PACING_STRATEGY_LABELS,
  type AccountStructure,
  type Cycle,
  type Dissent,
  type PacingStrategy,
  type PlanOption,
  type RuleCardLearned,
} from "@/lib/warroomApi";
import { Badge } from "../shared/Badge";

type LoadState =
  | { status: "idle" }
  | { status: "generating" }
  | { status: "ready"; options: PlanOption[]; structure: AccountStructure; dissents: Dissent[] };

/** 企劃（S8.12-22，吸收 `ads_plan_select.html`＋`ads_cycle.html` 計畫區塊）：依 `cycle.status`
 * 分三段——PLANNING 沒方案要先產出；PLAN_SELECT 待選方案；REVIEW（含之後）已選定計畫確認卡。
 * 「AI 出方案進行中」真後端沿用既有 `_progress_state` 90 秒逾時機制（契約「背景生成等待態」
 * 節，不是本票新設計）；原型用 1.5 秒 `setTimeout` 示意同一段等待態畫面，不架一套假輪詢
 * 伺服器（跳過了什麼：見交付報告）。 */
export function PlanStep({ brandId, cycle, onApproved, onRefresh }: { brandId: string; cycle: Cycle; onApproved: () => void; onRefresh: () => void }) {
  const [state, setState] = useState<LoadState>({ status: "idle" });
  const [customDirection, setCustomDirection] = useState("");
  const [pacing, setPacing] = useState<PacingStrategy>(cycle.pacing_strategy);
  const [pacingReason, setPacingReason] = useState(cycle.pacing_reason);
  const [ruleCards, setRuleCards] = useState<RuleCardLearned[]>([]);
  const [ruleCardsDecided, setRuleCardsDecided] = useState(false);
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);

  const alreadyGenerated = cycle.status !== "PLANNING";

  useEffect(() => {
    if (!alreadyGenerated) return;
    fetchPlanOptions(brandId, cycle.id).then(({ options, account_structure, dissents }) => setState({ status: "ready", options, structure: account_structure, dissents }));
    fetchRuleCardsLearned(brandId, cycle.id).then(setRuleCards);
    // 依賴含 cycle.status：cyc.id 不變、status 從 PLANNING 轉 PLAN_SELECT 也要重新抓一次
    // （出方案完成後父層 `refresh()` 帶回新狀態，同一個元件實例不會重新掛載）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, cycle.id, alreadyGenerated]);

  async function generate() {
    setState({ status: "generating" });
    await startPlanGeneration(brandId, cycle.id);
    // 真後端沿用 app/ads/routes.py 既有 90 秒逾時的 `_progress_state` 輪詢機制；原型用
    // 固定延遲示意同一段等待態，不架一套假輪詢伺服器（見交付報告「跳過了什麼」）。
    setTimeout(() => onRefresh(), 1500);
  }

  async function pickOption(optionId: string) {
    await selectPlanOption(brandId, cycle.id, optionId);
    onApproved(); // 選定後狀態轉 REVIEW，讓上層重新整理 cycle
  }

  async function decide(dissentId: string, accepted: boolean) {
    await decideDissent(brandId, cycle.id, dissentId, accepted);
  }

  async function savePacing() {
    await updatePacing(brandId, cycle.id, pacing, pacingReason);
  }

  async function approve() {
    setApproving(true);
    setApproveError(null);
    try {
      await approvePlan(brandId, cycle.id);
      onApproved();
    } catch (err) {
      setApproveError(err instanceof Error ? err.message : "核准失敗，請稍後再試。");
    } finally {
      setApproving(false);
    }
  }

  if (!alreadyGenerated) {
    if (state.status === "generating") {
      return (
        <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground shadow-[var(--shadow-card)]">
          AI 正在出方案，通常一到兩分鐘…
        </div>
      );
    }
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
        <h2 className="font-display text-lg text-foreground">產出這期的方案</h2>
        <p className="text-sm text-muted-foreground">AI 會依品牌智庫資料，準備 2–4 張可選的投放方案。</p>
        <button type="button" onClick={() => void generate()} className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">
          產出這期的方案
        </button>
      </div>
    );
  }

  if (state.status !== "ready") {
    return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">讀取中…</div>;
  }

  if (cycle.status === "PLAN_SELECT") {
    return (
      <div className="flex flex-col gap-4">
        <AccountStructureCard structure={state.structure} />
        {state.dissents.length > 0 && (
          <div className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
            <p className="text-sm font-medium text-foreground">AI 對底案的意見</p>
            {state.dissents.map((d) => (
              <div key={d.id} className="mt-2 flex flex-col gap-1 rounded-md border border-border p-3 text-sm">
                <p className="text-foreground">{d.suggestion}</p>
                <p className="text-xs text-muted-foreground">{d.reason}</p>
                <div className="flex gap-2">
                  <button type="button" onClick={() => void decide(d.id, true)} className="rounded-md border border-primary px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10">採納</button>
                  <button type="button" onClick={() => void decide(d.id, false)} className="rounded-md border border-border px-2 py-1 text-xs font-medium text-muted-foreground hover:border-primary">不採納</button>
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          {state.options.map((opt) => (
            <div key={opt.id} className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
              <div className="flex items-center justify-between">
                <p className="font-medium text-foreground">{opt.summary}</p>
                {opt.is_recommended && <Badge tone="success">AI 推薦</Badge>}
              </div>
              {opt.difference && <p className="text-xs text-muted-foreground">{opt.difference}</p>}
              <div className="flex flex-wrap gap-1">
                {Object.entries(opt.audience.tiers).map(([tier, info]) => (
                  <Badge key={tier} tone={info.available ? "success" : "neutral"}>
                    {AUDIENCE_TIER_LABELS[tier] ?? tier}
                    {!info.available ? "・不可用" : ""}
                  </Badge>
                ))}
              </div>
              <ul className="flex flex-col gap-0.5 text-xs text-muted-foreground">
                {opt.angles.map((a, i) => (
                  <li key={i}>切角：{a.title}</li>
                ))}
              </ul>
              {opt.hypotheses && (
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer text-primary">想驗證的事</summary>
                  <ul className="mt-1 list-disc pl-4">
                    {opt.hypotheses.map((h, i) => (
                      <li key={i}>{h.statement}</li>
                    ))}
                  </ul>
                </details>
              )}
              <button type="button" onClick={() => void pickOption(opt.id)} className="self-start rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90">
                就選這個
              </button>
            </div>
          ))}
        </div>
        <details className="rounded-lg border border-dashed border-border p-3 text-sm">
          <summary className="cursor-pointer text-primary">都不喜歡，我自己寫方向</summary>
          <textarea value={customDirection} onChange={(e) => setCustomDirection(e.target.value)} rows={2} className="mt-2 w-full rounded-md border border-border px-3 py-2 text-sm text-foreground" />
          <button type="button" onClick={() => void generate()} className="mt-2 rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10">
            重新生成
          </button>
        </details>
      </div>
    );
  }

  // REVIEW（或之後——已核准，唯讀回顧）
  const approved = cycle.status !== "REVIEW";
  return (
    <div className="flex flex-col gap-4">
      <AccountStructureCard structure={state.structure} />
      <div className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        <p className="font-medium text-foreground">排期策略</p>
        <div className="mt-2 flex flex-col gap-2">
          {(Object.keys(PACING_STRATEGY_LABELS) as PacingStrategy[]).map((key) => (
            <label key={key} className="flex items-center gap-2 text-sm text-foreground">
              <input type="radio" disabled={approved} checked={pacing === key} onChange={() => setPacing(key)} />
              {PACING_STRATEGY_LABELS[key].title}（{PACING_STRATEGY_LABELS[key].tag}）
              <span className="text-xs text-muted-foreground">{PACING_STRATEGY_LABELS[key].desc}</span>
            </label>
          ))}
        </div>
        {!approved && (
          <div className="mt-2 flex items-center gap-2">
            <input type="text" value={pacingReason} onChange={(e) => setPacingReason(e.target.value)} className="flex-1 rounded-md border border-border px-2 py-1 text-sm text-foreground" />
            <button type="button" onClick={() => void savePacing()} className="rounded-md border border-primary px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10">存理由</button>
          </div>
        )}
        {approved && <p className="mt-1 text-xs text-muted-foreground">理由：{cycle.pacing_reason}</p>}
      </div>

      {ruleCards.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
          <p className="font-medium text-foreground">我從你上次的挑選裡學到這些</p>
          <ul className="mt-2 flex flex-col gap-1 text-sm text-foreground">
            {ruleCards.map((c, i) => (
              <li key={i} className="rounded-md border border-border p-2">{c.text}</li>
            ))}
          </ul>
          {!approved && !ruleCardsDecided && (
            <div className="mt-2 flex gap-2">
              <button type="button" onClick={() => setRuleCardsDecided(true)} className="rounded-md border border-primary px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10">同意</button>
              <button type="button" onClick={() => setRuleCardsDecided(true)} className="rounded-md border border-border px-2 py-1 text-xs font-medium text-muted-foreground">不用</button>
            </div>
          )}
        </div>
      )}

      {approveError && <p className="text-sm text-danger">{approveError}</p>}
      {approved ? (
        <p className="rounded-md bg-success/10 px-3 py-2 text-sm text-success">計畫已核准，素材已在背景批次預生成中。</p>
      ) : (
        <button
          type="button"
          disabled={approving}
          onClick={() => void approve()}
          className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {approving ? "核准中…" : "就照這個做"}
        </button>
      )}
    </div>
  );
}

export function AccountStructureCard({ structure }: { structure: AccountStructure }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <p className="font-medium text-foreground">
        帳戶結構與預算配置底案・<Badge>{structure.tier_label}</Badge>
      </p>
      <p className="mt-1 text-sm text-foreground">{structure.structure_label}</p>
      <ul className="mt-2 flex flex-col gap-1 text-sm">
        {structure.groups.map((g) => (
          <li key={g.role} className="flex items-center justify-between gap-2 text-foreground">
            <span>{g.label}（{Math.round(g.ratio * 100)}%）</span>
            <span className="flex items-center gap-1">
              NT$ {g.daily_budget.toLocaleString("zh-TW")}／天
              {g.below_floor && <Badge tone="warning">低於下限</Badge>}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted-foreground">{structure.note}</p>
    </div>
  );
}
