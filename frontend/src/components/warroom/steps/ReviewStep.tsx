import { useEffect, useState } from "react";
import type { EChartsOption } from "echarts";
import { Link } from "react-router-dom";
import { FluidCard } from "@/components/layout/FluidCard";
import { StatBig } from "@/components/layout/StatBig";
import { CHART_COLOR_REVENUE, CHART_COLOR_SPEND } from "@/lib/chartColors";
import { formatCurrency, formatPercent, formatRoas, formatUsd } from "@/lib/format";
import { useEchart } from "@/lib/useEchart";
import { useFormSubmit } from "@/lib/useFormSubmit";
import {
  fetchClosingReview,
  fetchSettleNow,
  resolveHypotheses,
  settleNow,
  type ClosingReview,
  type Cycle,
  type SettleNowInfo,
} from "@/lib/warroomApi";

const VERDICT_LABELS = { supported: "成立", rejected: "不成立", inconclusive: "看不出來" } as const;
const VERDICT_OPTIONS: { value: keyof typeof VERDICT_LABELS; label: string }[] = [
  { value: "supported", label: "成立" },
  { value: "rejected", label: "不成立" },
  { value: "inconclusive", label: "看不出來" },
];
/** R2-learning-honesty 契約第 3 點：少於這個切角數＝這期沒有真的做過 A／B 對照，
 * 跟後端 `app/ads/reading_hypotheses.py::MIN_COMPARISON_CELLS` 對齊。 */
const MIN_COMPARISON_CELLS = 2;

/** 覆盤（S8R.23-26 重設計，吸收舊 `S8.59-66`，僅 `cycle.status === 'CLOSED'` 後出現）：固定
 * 四段式，圖像化每一段（雙條圖／環形圖／學習兩張卡／前後對照長條），資料源完全沿用舊條文，
 * 只新增每段的視覺形式，不重新計算任何判讀邏輯。 */
export function ReviewStep({ brandId, cycle }: { brandId: string; cycle: Cycle }) {
  const [state, setState] = useState<{ status: "loading" } | { status: "locked" } | { status: "ready"; review: ClosingReview }>({ status: "loading" });

  function load() {
    fetchClosingReview(brandId, cycle.id)
      .then((review) => setState({ status: "ready", review }))
      .catch(() => setState({ status: "locked" }));
  }
  useEffect(load, [brandId, cycle.id]);

  if (state.status === "loading") return <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">讀取中…</div>;
  if (state.status === "locked") {
    return <SettleNowPanel brandId={brandId} cycle={cycle} onSettled={load} />;
  }

  const { review } = state;
  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-display text-lg text-foreground">這期覆盤</h2>
      <GoalComparisonCard review={review} />
      <AttributionCard review={review} />
      <LearningCard brandId={brandId} cycleId={cycle.id} review={review} onResolved={load} />
      <NextCycleCard brandId={brandId} review={review} cycle={cycle} />
    </div>
  );
}

/** 票 S1-01：這期還沒收帳時的覆盤畫面——原本只印一句死板的「還沒結案」，現在直接給
 * 「現在結算」按鈕（不必等結束後 14 天的背景工）。can_settle 為假時按鈕 disabled＋顯示
 * 原因（例如這期一筆成效數字都還沒有）。按下先跳 `window.confirm`（沿用
 * `ProposalBook.tsx:172` 同一種一鍵確認框寫法），成功後呼叫 `onSettled()` 就地重抓覆盤，
 * 不整頁重整。
 *
 * B0-05：文案不再承諾「結束後 14 天自動收帳」——背景收帳只在系統開著的時候才會被排到
 * （`app/main.py _auto_sync_if_due()`），單機單人使用型態下沒辦法保證在第 14 天那一刻
 * 剛好在跑，真機重現時已經過了 35 天還沒收帳。
 *
 * F6：現在系統能兌現的說法變了——排程改用 Windows 工作排程器 `onlogon` 觸發（使用者
 * 2026-08-25 核准的機制，見 .scratch/rehearsal-b0-fix2/issues/F6-auto-settlement-on-boot.md），
 * process 一起來就會先補跑一次，不必等滿一小時。文案只敢講「登入時」，不敢講「幾天內」——
 * 排程只在使用者登入 Windows 那一刻觸發，機器沒開、沒登入就是沒有這回事，這是誠實的邊界，
 * 不是又一次過度承諾。 */
function SettleNowPanel({ brandId, cycle, onSettled }: { brandId: string; cycle: Cycle; onSettled: () => void }) {
  const [info, setInfo] = useState<SettleNowInfo | null>(null);

  useEffect(() => {
    fetchSettleNow(brandId, cycle.id).then(setInfo).catch(() => setInfo(null));
  }, [brandId, cycle.id]);

  const settleForm = useFormSubmit(async () => {
    await settleNow(brandId, cycle.id);
    onSettled();
  });

  function onClick() {
    if (!info) return;
    // 票 F9：還有沒處理的建議卡時多問一句——結案後這些卡會直接歸檔，不再是候著使用者
    // 核可的狀態，讓使用者在按下去之前知道會發生這件事。
    const unhandled = info.unhandled_cards;
    const unhandledNote =
      unhandled.count > 0 ? `這期還有 ${unhandled.count} 張建議卡沒處理（${unhandled.names.join("、")}），結案後會歸檔。` : "";
    const confirmed = window.confirm(
      `${unhandledNote}收帳後這期就不能改回投放中；之後補進來的數字還是會算，系統會重新算結論並告訴你哪裡變了。這一步會用 AI 整理結論，最多花費 ${formatUsd(info.estimated_cost)}。確定要現在收帳嗎？`,
    );
    if (!confirmed) return;
    void settleForm.submit();
  }

  return (
    <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
      <p>這期還沒收帳。系統設定成你下次登入電腦時會自動幫你收帳；不想等下次登入，也可以直接按下面「現在結算」。</p>
      {info && !info.already_closed && (
        <div className="mt-4 flex flex-col items-center gap-2">
          <button
            type="button"
            onClick={onClick}
            disabled={!info.can_settle || settleForm.saving}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {settleForm.saving ? "結算中…" : "現在結算"}
          </button>
          {!info.can_settle && info.reason && <p className="text-xs text-warning">{info.reason}</p>}
          {settleForm.error && <p className="text-xs text-danger">{settleForm.error}</p>}
        </div>
      )}
    </div>
  );
}

/** S8R.23：①目標對照——雙條圖（左＝原訂目標，右＝實際算出的對應 KPI）。 */
function GoalComparisonCard({ review }: { review: ClosingReview }) {
  const { goal_comparison: g } = review;
  const gapPct = g.actual_value === null ? null : Math.round(((g.actual_value - g.target_value) / g.target_value) * 1000) / 10;
  const option: EChartsOption = {
    grid: { left: 56, right: 32, top: 16, bottom: 24 },
    xAxis: { type: "value", name: g.metric_label, axisLabel: { formatter: (v: number) => v.toLocaleString("zh-TW") } },
    yAxis: { type: "category", data: ["目標", "實際"] },
    series: [
      {
        type: "bar",
        barWidth: 22,
        label: { show: true, position: "right", formatter: (p) => (p.value as number).toLocaleString("zh-TW") },
        data: [g.target_value, g.actual_value ?? 0],
      },
    ],
  };
  const ref = useEchart(option);

  return (
    <FluidCard title="①目標對照" subtitle={`${g.objective_label}・${g.target}・來源：${g.source}`}>
      <div ref={ref} className="h-32 w-full" />
      <p className="mt-1 text-sm text-foreground">
        {g.actual_value === null
          ? "還沒有可以算的成效數字，算不出差距。"
          : `實際比目標${gapPct !== null && gapPct >= 0 ? "高" : "低"} ${Math.abs(gapPct ?? 0)}%${g.lower_is_better ? "（這個指標越低越好）" : ""}`}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        CTR {review.goal_comparison.actual_kpis.ctr !== null ? formatPercent(review.goal_comparison.actual_kpis.ctr) : "資料不足"}、CPA {formatCurrency(review.goal_comparison.actual_kpis.cpa)}、ROAS {formatRoas(review.goal_comparison.actual_kpis.roas)}
      </p>
    </FluidCard>
  );
}

/** S8R.24：②落差歸因——環形圖（訂單歸因四分類佔比）＋下方判讀結論既有理由清單原樣引用。 */
function AttributionCard({ review }: { review: ClosingReview }) {
  const { attribution: a, reasons, channel_note, ga4_leak_note, source, two_ledger_note } = review.gap_attribution;
  const total = a.gross.count + a.net.count + a.excluded.count + a.natural.count;
  const option: EChartsOption = {
    tooltip: { trigger: "item" },
    legend: { bottom: 0 },
    series: [
      {
        type: "pie",
        radius: ["40%", "68%"],
        avoidLabelOverlap: true,
        label: { formatter: "{b}\n{d}%" },
        data: [
          { name: "毛單", value: a.gross.count },
          { name: "淨單", value: a.net.count },
          { name: "排除", value: a.excluded.count },
          { name: "自然單", value: a.natural.count },
        ],
      },
    ],
  };
  const ref = useEchart(option);

  return (
    <FluidCard title="②落差歸因" subtitle={`來源：${source}`}>
      <p className="text-xs text-muted-foreground">{two_ledger_note}</p>
      {total === 0 ? (
        <p className="text-sm text-muted-foreground">這期還沒有收到訂單歸因資料。</p>
      ) : (
        <>
          <div ref={ref} className="h-56 w-full" />
          <dl className="mt-2 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            {([
              ["毛單", a.gross],
              ["淨單", a.net],
              ["排除", a.excluded],
              ["自然單", a.natural],
            ] as const).map(([label, cat]) => (
              <div key={label}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="text-foreground">{cat.count} 筆・{formatCurrency(cat.net_revenue)}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      <ul className="mt-3 list-disc pl-4 text-sm text-foreground">
        {reasons.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
      {channel_note && <p className="mt-1 text-xs text-muted-foreground">{channel_note}</p>}
      {ga4_leak_note && <p className="mt-1 text-xs text-warning">{ga4_leak_note}</p>}
    </FluidCard>
  );
}

/** S8R.25：③學習兩層——本期層（策略假設結案）／跨期層（累積智慧）兩張卡。 */
/** 票 L1-01：pending 的假設逐條三選一結案（人確認後才入帳，決策 0035 第三節第 6 點——
 * AI 預選＋一路下一步＝確認偏誤幫浦，這裡只是預設選取，使用者可以改）。 */
function LearningCard({
  brandId,
  cycleId,
  review,
  onResolved,
}: {
  brandId: string;
  cycleId: string;
  review: ClosingReview;
  onResolved: () => void;
}) {
  const { learning } = review;
  const [overrides, setOverrides] = useState<Record<string, keyof typeof VERDICT_LABELS>>({});
  const pending = learning.hypotheses.filter((h) => h.pending);

  function verdictFor(h: ClosingReview["learning"]["hypotheses"][number]) {
    return overrides[h.id] ?? h.preselected ?? "inconclusive";
  }

  const resolveForm = useFormSubmit(async () => {
    const verdicts: Record<string, keyof typeof VERDICT_LABELS> = {};
    for (const h of pending) verdicts[h.id] = verdictFor(h);
    await resolveHypotheses(brandId, cycleId, verdicts);
    setOverrides({});
    onResolved();
  });

  return (
    <FluidCard title="③學到的事">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-md border border-border p-3">
          <p className="text-xs font-medium text-muted-foreground">這期驗證了什麼</p>
          <ul className="mt-1 space-y-2 text-sm text-foreground">
            {learning.hypotheses.map((h) => (
              <li key={h.id}>
                {h.pending ? (
                  <div>
                    <p>{h.statement}</p>
                    {h.comparison_cells.length > 0 ? (
                      <div className="mt-1 overflow-x-auto rounded border border-border/60">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-muted-foreground">
                              <th className="px-2 py-1 text-left font-normal">切角</th>
                              <th className="px-2 py-1 text-right font-normal">樣本數</th>
                              <th className="px-2 py-1 text-right font-normal">花費</th>
                              <th className="px-2 py-1 text-right font-normal">CPA</th>
                              <th className="px-2 py-1 text-right font-normal">ROAS</th>
                            </tr>
                          </thead>
                          <tbody>
                            {h.comparison_cells.map((c) => (
                              <tr key={c.cell_id} className="border-t border-border/40 text-foreground">
                                <td className="px-2 py-1">{c.creative_angle ?? "（未命名切角）"}</td>
                                <td className="px-2 py-1 text-right">{c.conversions}</td>
                                <td className="px-2 py-1 text-right">{formatCurrency(c.spend)}</td>
                                <td className="px-2 py-1 text-right">{formatCurrency(c.kpis.cpa)}</td>
                                <td className="px-2 py-1 text-right">{formatRoas(c.kpis.roas)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : null}
                    {h.comparison_cells.length < MIN_COMPARISON_CELLS && (
                      <p className="mt-1 text-xs text-warning">
                        這期只投了 {h.comparison_cells.length} 個切角，沒有對照組，看不出這條假設成不成立，「成立」先不能選。
                      </p>
                    )}
                    <div className="mt-1 flex flex-wrap gap-3 text-xs text-muted-foreground">
                      {VERDICT_OPTIONS.map((opt) => {
                        const disabled = opt.value === "supported" && h.comparison_cells.length < MIN_COMPARISON_CELLS;
                        return (
                          <label key={opt.value} className={`flex items-center gap-1 ${disabled ? "opacity-40" : ""}`}>
                            <input
                              type="radio"
                              name={`hyp-verdict-${h.id}`}
                              checked={verdictFor(h) === opt.value}
                              disabled={disabled}
                              onChange={() => setOverrides((prev) => ({ ...prev, [h.id]: opt.value }))}
                            />
                            {opt.label}
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  <div>
                    <p>
                      {h.statement}：{VERDICT_LABELS[h.verdict]}
                    </p>
                    {h.stale_note && <p className="mt-1 text-xs text-warning">⚠ {h.stale_note}</p>}
                  </div>
                )}
              </li>
            ))}
          </ul>
          {pending.length > 0 && (
            <div className="mt-3 border-t border-border pt-2">
              <p className="text-xs text-muted-foreground">確認後不能改，成立的會寫進累積智慧。</p>
              <button
                type="button"
                onClick={() => void resolveForm.submit()}
                disabled={resolveForm.saving}
                className="mt-1 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {resolveForm.saving ? "送出中…" : "確認結案"}
              </button>
              {resolveForm.error && <p className="mt-1 text-xs text-danger">{resolveForm.error}</p>}
            </div>
          )}
        </div>
        <div className="rounded-md border border-border p-3">
          <p className="text-xs font-medium text-muted-foreground">累積下來學到什麼</p>
          {learning.ledger_entries.length === 0 ? (
            <p className="mt-1 text-sm text-muted-foreground">這期沒有新入帳的累積智慧。</p>
          ) : (
            <ul className="mt-1 list-disc pl-4 text-sm text-foreground">
              {learning.ledger_entries.map((e, i) => (
                <li key={i}>{e.text}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </FluidCard>
  );
}

/** S8R.26：④下期建議——前後對照長條（本期預算→下期建議預算）＋一鍵帶設定按鈕。 */
function NextCycleCard({ brandId, review, cycle }: { brandId: string; review: ClosingReview; cycle: Cycle }) {
  const { recommendation: r } = review;
  const option: EChartsOption = {
    color: [CHART_COLOR_SPEND, CHART_COLOR_REVENUE],
    grid: { left: 56, right: 32, top: 16, bottom: 24 },
    xAxis: { type: "value", axisLabel: { formatter: (v: number) => `NT$${Math.round(v / 1000)}k` } },
    yAxis: { type: "category", data: ["本期預算", "下期建議"] },
    series: [
      {
        type: "bar",
        barWidth: 22,
        label: { show: true, position: "right", formatter: (p) => formatCurrency(p.value as number) },
        data: [
          { value: cycle.budget, itemStyle: { color: CHART_COLOR_SPEND } },
          { value: r.proposed_budget, itemStyle: { color: CHART_COLOR_REVENUE } },
        ],
      },
    ],
  };
  const ref = useEchart(option);

  return (
    <FluidCard title="④下期建議">
      <div ref={ref} className="h-24 w-full" />
      <StatBig value={formatCurrency(r.proposed_budget)} label="下期建議預算" className="mt-2" />
      <p className="mt-1 text-sm text-foreground">{r.budget_advice}</p>
      {r.delta_reason && <p className="mt-1 text-xs text-muted-foreground">{r.delta_reason}</p>}
      <p className="mt-1 text-xs text-muted-foreground">
        新增規則卡 {r.rule_cards_created} 張
        {r.echo_chamber && "・已提示避免回音室"}
      </p>
      <Link to={`/brands/${brandId}/campaigns/new?from_cycle=${encodeURIComponent(cycle.id)}`} className="mt-3 inline-block self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">
        開下一期就這樣開
      </Link>
    </FluidCard>
  );
}
