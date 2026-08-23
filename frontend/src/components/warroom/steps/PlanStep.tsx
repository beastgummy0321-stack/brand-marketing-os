import { useEffect, useRef, useState } from "react";
import { Pencil } from "lucide-react";
import {
  approvePlan,
  decideDissent,
  fetchPlanOptions,
  fetchPlanStatus,
  fetchRuleCardsLearned,
  fetchScheduleReminder,
  renameAngle,
  selectPlanOption,
  startPlanGeneration,
  updatePacing,
  AUDIENCE_TIER_LABELS,
  MAX_ANGLE_LENGTH,
  PACING_STRATEGY_LABELS,
  type AccountStructure,
  type Cycle,
  type Dissent,
  type PacingStrategy,
  type PlanCellAngle,
  type PlanOption,
  type RuleCardLearned,
  type ScheduleReminder,
} from "@/lib/warroomApi";
import { decideRuleCard } from "@/lib/learningsApi";
import { Badge } from "../shared/Badge";

type LoadState =
  | { status: "idle" }
  | { status: "generating" }
  | { status: "generate-failed"; message: string }
  | {
      status: "ready";
      options: PlanOption[];
      structure: AccountStructure;
      dissents: Dissent[];
      cells: PlanCellAngle[];
      angleLocked: boolean;
    };

const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 180_000;

/** 企劃（S8.12-22，吸收 `ads_plan_select.html`＋`ads_cycle.html` 計畫區塊）：依 `cycle.status`
 * 分三段——PLANNING 沒方案要先產出；PLAN_SELECT 待選方案；REVIEW（含之後）已選定計畫確認卡。
 * 「AI 出方案進行中」真輪詢 `GET .../plan/status`，沿用既有 `_progress_state` 90 秒逾時機制
 * （routes_campaigns_open_api.py plan_status，跟舊 Jinja `ads_plan_progress` 同一份底層狀態，
 * 不是兩套邏輯）；前端每 3 秒問一次，180 秒還沒問到 done／failed 就當作卡住讓使用者重試
 * （本機端額外的保險，後端本身 90 秒就會先回 failed）。 */
export function PlanStep({ brandId, cycle, onApproved, onRefresh }: { brandId: string; cycle: Cycle; onApproved: () => void; onRefresh: () => void }) {
  const [state, setState] = useState<LoadState>({ status: "idle" });
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollDeadlineRef = useRef(0);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, []);
  const [pacing, setPacing] = useState<PacingStrategy>(cycle.pacing_strategy);
  const [pacingReason, setPacingReason] = useState(cycle.pacing_reason);
  const [ruleCards, setRuleCards] = useState<RuleCardLearned[]>([]);
  const [ruleCardsDecided, setRuleCardsDecided] = useState(false);
  const [decidingRuleCards, setDecidingRuleCards] = useState(false);
  const [ruleCardsError, setRuleCardsError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [reminder, setReminder] = useState<ScheduleReminder | null>(null);

  const alreadyGenerated = cycle.status !== "PLANNING" || cycle.plan_version > 0;

  useEffect(() => {
    fetchScheduleReminder(brandId, cycle.id).then(setReminder);
  }, [brandId, cycle.id]);

  useEffect(() => {
    if (!alreadyGenerated) return;
    fetchPlanOptions(brandId, cycle.id).then(({ options, cells, angle_locked, account_structure, dissents }) =>
      setState({ status: "ready", options, structure: account_structure, dissents, cells, angleLocked: angle_locked }),
    );
    fetchRuleCardsLearned(brandId, cycle.id).then(setRuleCards);
    // 依賴含 cycle.status：cyc.id 不變、status 從 PLANNING 轉 PLAN_SELECT 也要重新抓一次
    // （出方案完成後父層 `refresh()` 帶回新狀態，同一個元件實例不會重新掛載）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, cycle.id, alreadyGenerated]);

  // 05b：畫面還沒生成過方案時，可能是「真的沒點過」，也可能是「點過但中途離開又回來」——
  // 背景生成執行緒不受畫面掛載／卸載影響，繼續跑在 `_progress_state`。掛載時先問一次
  // plan/status 把畫面接回真實狀態，而不是無條件顯示未點過的按鈕（票 05b 根因）。
  useEffect(() => {
    if (alreadyGenerated) return;
    let cancelled = false;
    fetchPlanStatus(brandId, cycle.id)
      .then((res) => {
        if (cancelled) return;
        if (res.status === "running") {
          setState({ status: "generating" });
          beginPolling();
        } else if (res.status === "failed") {
          setState({ status: "generate-failed", message: res.message ?? "產生方案失敗，請稍後再試。" });
        } else {
          // "done"：entry 不存在（從沒生成過）或剛好被這次讀取消化掉（生成其實已完成）
          // 兩種情況都無法從回應本身分辨，一律刷新一次交給 cycle.status／plan_version 判斷即可，
          // 從沒生成過時這只是一次無害的重讀。
          onRefresh();
        }
      })
      .catch(() => {
        // 問不到就當作沒事，維持原本未生成的按鈕畫面，讓使用者自己點。
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, cycle.id, alreadyGenerated]);

  function stopPolling() {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }

  function beginPolling() {
    pollDeadlineRef.current = Date.now() + POLL_TIMEOUT_MS;
    stopPolling();
    pollTimerRef.current = setInterval(() => void pollOnce(), POLL_INTERVAL_MS);
  }

  async function pollOnce() {
    if (Date.now() > pollDeadlineRef.current) {
      stopPolling();
      setState({ status: "generate-failed", message: "花比較久，稍後重新整理看看。" });
      return;
    }
    try {
      const res = await fetchPlanStatus(brandId, cycle.id);
      if (res.status === "done") {
        stopPolling();
        onRefresh();
      } else if (res.status === "failed") {
        stopPolling();
        setState({ status: "generate-failed", message: res.message ?? "產生方案失敗，請稍後再試。" });
      }
      // status === "running"：什麼都不做，等下一次輪詢。
    } catch (err) {
      stopPolling();
      setState({ status: "generate-failed", message: err instanceof Error ? err.message : "產生方案失敗，請稍後再試。" });
    }
  }

  async function generate() {
    setState({ status: "generating" });
    try {
      await startPlanGeneration(brandId, cycle.id);
    } catch (err) {
      setState({ status: "generate-failed", message: err instanceof Error ? err.message : "產生方案失敗，請稍後再試。" });
      return;
    }
    beginPolling();
  }

  async function pickOption(optionId: string) {
    await selectPlanOption(brandId, cycle.id, optionId);
    onApproved(); // 選定後狀態轉 REVIEW，讓上層重新整理 cycle
  }

  /** 改名成功後就地改這一格的顯示名字（票 04-angle-rename 二.2）：不重打 fetchPlanOptions
   * ——選定後 `campaign_plan_option` 已被清空（見 plan.py select_option()），重抓只會拿到
   * 空的 `options[]`，畫面反而空白，直接覆蓋本地 `cells[]` 才是正確、也是最省的做法。 */
  function handleAngleRenamed(cellId: string, creativeAngle: string) {
    setState((prev) =>
      prev.status !== "ready"
        ? prev
        : {
            ...prev,
            cells: prev.cells.map((c) => (c.id === cellId ? { ...c, creative_angle: creativeAngle } : c)),
          },
    );
  }

  async function decide(dissentId: string, accepted: boolean) {
    await decideDissent(brandId, cycle.id, dissentId, accepted);
  }

  async function savePacing() {
    await updatePacing(brandId, cycle.id, pacing, pacingReason);
  }

  async function decideRuleCards(accepted: boolean) {
    setDecidingRuleCards(true);
    setRuleCardsError(null);
    try {
      await Promise.all(ruleCards.map((card) => decideRuleCard(brandId, card.id, accepted)));
      setRuleCardsDecided(true);
    } catch (err) {
      setRuleCardsError(err instanceof Error ? err.message : "存不進去，稍後再試一次。");
    } finally {
      setDecidingRuleCards(false);
    }
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
    if (state.status === "generate-failed") {
      return (
        <div className="flex flex-col gap-3 rounded-lg border border-danger/30 bg-danger/10 p-6 shadow-[var(--shadow-card)]">
          <h2 className="font-display text-lg text-foreground">出方案失敗</h2>
          <p className="text-sm text-danger">{state.message}</p>
          <button type="button" onClick={() => void generate()} className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">
            再試一次
          </button>
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
        <PlanOptionShowcase
          options={state.options}
          readOnly={false}
          onSelect={pickOption}
          cells={state.cells}
          angleLocked={state.angleLocked}
          brandId={brandId}
          cycleId={cycle.id}
          onAngleRenamed={handleAngleRenamed}
        />
      </div>
    );
  }
  // REVIEW（或之後——已核准，唯讀回顧）
  const approved = cycle.status !== "REVIEW";
  return (
    <div className="flex flex-col gap-4">
      <PlanOptionShowcase
        options={state.options}
        readOnly={approved}
        onSelect={pickOption}
        cells={state.cells}
        angleLocked={state.angleLocked}
        brandId={brandId}
        cycleId={cycle.id}
        onAngleRenamed={handleAngleRenamed}
      />
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

      {reminder && (
        <div className="rounded-lg border border-warning/40 bg-warning/10 p-4 shadow-[var(--shadow-card)]">
          <p className="font-medium text-foreground">排期到期提醒・{reminder.date}</p>
          <p className="mt-1 text-sm text-foreground">{reminder.copy_text}</p>
          <button
            type="button"
            onClick={() => {
              void navigator.clipboard?.writeText(reminder.copy_text).catch(() => {});
            }}
            className="mt-2 rounded-md border border-warning px-3 py-1 text-xs font-medium text-warning hover:bg-warning/20"
          >
            複製
          </button>
        </div>
      )}

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
              <button type="button" disabled={decidingRuleCards} onClick={() => void decideRuleCards(true)} className="rounded-md border border-primary px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50">同意</button>
              <button type="button" disabled={decidingRuleCards} onClick={() => void decideRuleCards(false)} className="rounded-md border border-border px-2 py-1 text-xs font-medium text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50">不用</button>
            </div>
          )}
          {ruleCardsError && <p className="mt-2 text-xs text-danger">{ruleCardsError}</p>}
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

function PlanOptionShowcase({
  options,
  readOnly,
  onSelect,
  cells,
  angleLocked,
  brandId,
  cycleId,
  onAngleRenamed,
}: {
  options: PlanOption[];
  readOnly: boolean;
  onSelect: (optionId: string) => Promise<void>;
  cells: PlanCellAngle[];
  angleLocked: boolean;
  brandId: string;
  cycleId: string;
  onAngleRenamed: (cellId: string, creativeAngle: string) => void;
}) {
  const primary = options.find((option) => option.is_recommended) ?? options[0];
  const [activeId, setActiveId] = useState(primary?.id ?? "");
  const [selecting, setSelecting] = useState(false);
  useEffect(() => setActiveId(primary?.id ?? ""), [primary?.id]);
  const active = options.find((option) => option.id === activeId) ?? primary;
  const alternatives = options.filter((option) => option.id !== active?.id).slice(0, 2);
  if (!active) return null;

  function choose(option: PlanOption) {
    setActiveId(option.id);
  }

  async function selectActive() {
    if (selecting) return;
    setSelecting(true);
    try {
      await onSelect(active.id);
    } finally {
      setSelecting(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-xl border border-primary/40 bg-card p-5 shadow-[var(--shadow-card)]">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-display text-xl text-foreground">AI 完整方案</p>
          <Badge tone="success">{readOnly ? "已選定" : active.is_recommended ? "AI 推薦" : "預覽中"}</Badge>
        </div>
        <p className="mt-3 text-base font-medium text-foreground">{active.summary}</p>
        {active.difference && <p className="mt-1 text-sm text-muted-foreground">{active.difference}</p>}
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div>
            <p className="text-xs font-medium text-muted-foreground">受眾</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {Object.entries(active.audience.tiers).map(([tier, info]) => <Badge key={tier} tone={info.available ? "success" : "neutral"}>{AUDIENCE_TIER_LABELS[tier] ?? tier}{!info.available ? "・不可用" : ""}</Badge>)}
            </div>
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">投放切角</p>
            <ul className="mt-1 flex flex-col gap-1 text-sm text-foreground">
              {active.angles.map((angle, index) => (
                <AngleListItem
                  key={index}
                  angle={angle}
                  cell={cells[index]}
                  locked={angleLocked}
                  brandId={brandId}
                  cycleId={cycleId}
                  onRenamed={onAngleRenamed}
                />
              ))}
            </ul>
          </div>
        </div>
        {active.hypotheses && <details className="mt-3 text-sm text-muted-foreground"><summary className="cursor-pointer text-primary">想驗證的事</summary><ul className="mt-1 list-disc pl-4">{active.hypotheses.map((hypothesis, index) => <li key={index}>{hypothesis.statement}</li>)}</ul></details>}
        {!readOnly && (
          <button
            type="button"
            disabled={selecting}
            onClick={() => void selectActive()}
            className="mt-4 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {selecting ? "送出中…" : "就用這案，看提案書"}
          </button>
        )}
      </div>
      {alternatives.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-xs font-medium text-muted-foreground">另兩案・點一下先看內容，確認才定案</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {alternatives.map((option) => (
              <button key={option.id} type="button" disabled={readOnly} onClick={() => choose(option)} className="rounded-lg border border-border bg-card p-3 text-left transition-colors hover:border-primary disabled:cursor-default disabled:opacity-70">
                <span className="block text-sm font-medium text-foreground">{option.summary}</span>
                {option.difference && <span className="mt-1 block text-xs text-muted-foreground">{option.difference}</span>}
                <span className="mt-2 block text-xs text-primary">改看這案</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
/** 投放切角一列＋改名鉛筆（票 04-angle-rename 一.2、一.3）：`cell` 沒有值代表這格還沒落地
 * 成 `experiment_cell`（PLAN_SELECT 階段，還沒選定方案），直接顯示快照標題、不給鉛筆——
 * 落地之後才有可以改的東西。名稱顯示以 `cell.creative_angle` 為準，不是 `angle.title` 快照。 */
function AngleListItem({
  angle,
  cell,
  locked,
  brandId,
  cycleId,
  onRenamed,
}: {
  angle: { title: string; message: string; why?: string };
  cell: PlanCellAngle | undefined;
  locked: boolean;
  brandId: string;
  cycleId: string;
  onRenamed: (cellId: string, creativeAngle: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const displayTitle = cell?.creative_angle ?? angle.title;
  const [value, setValue] = useState(displayTitle);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEdit() {
    setValue(displayTitle);
    setError(null);
    setEditing(true);
  }

  async function save() {
    if (!cell) return;
    const trimmed = value.trim();
    if (!trimmed) {
      setError("切角名稱不能空白");
      return;
    }
    if (trimmed.length > MAX_ANGLE_LENGTH) {
      setError(`切角名稱最多 ${MAX_ANGLE_LENGTH} 字`);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const saved = await renameAngle(brandId, cycleId, cell.id, trimmed);
      onRenamed(cell.id, saved);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "改名失敗，請稍後再試。");
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <li className="flex flex-col gap-1">
        <div className="flex items-center gap-1">
          <input
            autoFocus
            value={value}
            onChange={(e) => setValue(e.target.value)}
            maxLength={MAX_ANGLE_LENGTH}
            className="rounded-md border border-border px-1.5 py-0.5 text-sm text-foreground"
          />
          <span>：{angle.message}</span>
          <button
            type="button"
            disabled={saving}
            onClick={() => void save()}
            className="text-xs font-medium text-primary hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? "存中…" : "儲存"}
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => setEditing(false)}
            className="text-xs text-muted-foreground hover:opacity-80"
          >
            取消
          </button>
        </div>
        {error && <p className="text-xs text-danger">{error}</p>}
      </li>
    );
  }

  return (
    <li
      className="flex items-center gap-1"
      title={cell && locked ? "交接包已產出，改名會讓 Meta 上的名稱對不上，這裡先鎖住。" : undefined}
    >
      <span>{displayTitle}：{angle.message}</span>
      {cell && !locked && (
        <button
          type="button"
          onClick={startEdit}
          aria-label="改切角名稱"
          className="text-muted-foreground hover:text-primary"
        >
          <Pencil className="h-3 w-3" aria-hidden="true" />
        </button>
      )}
    </li>
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
