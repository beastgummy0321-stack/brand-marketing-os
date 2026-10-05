import { Button } from "@/components/layout/ui/button";
import { useEffect, useState } from "react";
import {
  adoptSuggestion,
  fetchDiagnosis,
  runDiagnosis,
  type Diagnosis,
  type DiagnosisCheckableNumbers,
  type DiagnosisSuggestion,
} from "@/lib/scheduleApi";
import { formatMoney } from "@/lib/format";

/** 票 02（T6c，02-diagnosis-on-cockpit.md）：成效判讀——長在既有「素材座標成效」區塊裡，
 * 不另開第三個長區塊（docs/design-system.md §1）。票面原文：「標題列右側加一顆『跑一次判讀』，
 * 結果顯示在標題下方、七維分頁與圖表上方」——按鈕跟既有的「素材座標成效」標題同一列，
 * 不是另起一顆子標題。狀態（載入／輪詢／採用）集中在這支 `useDiagnosisPanel()`，
 * `CockpitPage.tsx`（已 502 行，`CreativePerformanceSection` 的標題列）只呼叫一次這個 hook，
 * 把回傳值分別交給 `DiagnosisRunButton`（擺標題列）與 `DiagnosisResult`（擺標題下方）——
 * 新元件的邏輯與畫面全部留在這個新檔，`CockpitPage.tsx` 不多長業務邏輯。
 *
 * 四個狀態（票面「四個狀態，一個都不能少」）：
 * 1. 沒跑過（`diagnosis.status === null`）：一句話（`DiagnosisResult` 顯示）。
 * 2. 跑的時候（`busy`）：按鈕轉停用＋「判讀中」（`DiagnosisRunButton`），沿用既有
 *    `llm_task` 2 秒輪詢慣例（同 `SchedulePage.tsx` 的 `runningNow` 寫法：剛按下去那一刻
 *    也算進行中，不必等第一次輪詢才啟動）。
 * 3. 有結果（`status === "succeeded" && suggestions.length > 0`）：最多 5 張卡。
 * 4. 建議是空的：`no_tagged_spend` 分辨兩種不同原因，兩種都不是空白／錯誤紅框。
 */
type PanelState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; diagnosis: Diagnosis };

const DIRECTIONAL_ONLY_NOTE = "這是方向性判讀，不是統計顯著的結論。"; // ab-testing.md:75 原文，決定 4

export function useDiagnosisPanel(brandId: string) {
  const [state, setState] = useState<PanelState>({ status: "loading" });
  const [submitting, setSubmitting] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [adoptingIndex, setAdoptingIndex] = useState<number | null>(null);
  const [adoptError, setAdoptError] = useState<string | null>(null);
  const [adoptedIndexes, setAdoptedIndexes] = useState<Set<number>>(new Set());

  // 比照 SchedulePage.tsx `load()` 既有寫法：`submitting` 只在這裡清（每次輪詢／初次載入
  // 成功都會經過），不看這次讀到的 `diagnosis.status` 是什麼。POST 剛 enqueue 完那一刻，
  // 三個 lens 的新列還沒被 worker 寫進去，`_round_rows()` 摸到的仍是「上一輪」——那一輪多半
  // 是 succeeded，若靠這個狀態就清 submitting，畫面會在新一輪其實才剛開始跑的時候，誤以為
  // 已經跑完、把上一輪的舊建議當「這次」的結果展示（採用了索引，backend 那時再讀已經是新
  // 一輪還沒跑完，回 400）。改成不管這次讀到什麼都清 submitting：submitting 清掉之後
  // `busy` 還是不是 true，交給下一輪詢讀到的 `diagnosis.status` 自己決定——worker 真的還在
  // 跑，很快下一次 2 秒輪詢就會摸到新一輪的 running 列，busy 繼續撐著。
  function load() {
    fetchDiagnosis(brandId)
      .then((diagnosis) => {
        setState({ status: "ready", diagnosis });
        setSubmitting(false);
        // F31-I06: `suggestion.adopted` from the server is the truth; the local set only
        // bridges the moment between a click and this refetch.
        setAdoptedIndexes(new Set());
      })
      .catch((err: unknown) => {
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        });
        setSubmitting(false);
      });
  }

  useEffect(() => {
    setState({ status: "loading" });
    setAdoptedIndexes(new Set());
    setAdoptError(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId]);

  // 比照 SchedulePage.tsx 既有的 runningNow／輪詢寫法：剛按下去那一刻（submitting）跟伺服器
  // 回報的 running 一起算進行中，2 秒輪詢到不是 running 為止；worker 真的死了也會自己收斂
  // （伺服器狀態最終會變成 succeeded/failed，輪詢跟著停）。
  const busy = submitting || (state.status === "ready" && state.diagnosis.status === "running");
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, brandId]);

  async function onRun() {
    setSubmitting(true);
    setRunError(null);
    try {
      const diagnosis = await runDiagnosis(brandId);
      // POST 的回應可能還是上一輪（見上面 `load()` 的說明），這裡只拿它更新畫面看得到的
      // 資料，不靠它清 submitting——留給下一次輪詢的 `load()` 清。
      setState({ status: "ready", diagnosis });
    } catch (err) {
      setSubmitting(false);
      setRunError(err instanceof Error ? err.message : "判讀失敗，請稍後再試。");
    }
  }

  async function onAdopt(index: number) {
    setAdoptingIndex(index);
    setAdoptError(null);
    try {
      await adoptSuggestion(brandId, index);
      setAdoptedIndexes((prev) => new Set(prev).add(index));
      load();
    } catch (err) {
      setAdoptError(err instanceof Error ? err.message : "採用失敗，請稍後再試。");
    } finally {
      setAdoptingIndex(null);
    }
  }

  return {
    state, busy, runError, onRun, adoptedIndexes, adoptingIndex, adoptError, onAdopt,
  };
}

export type DiagnosisPanelState = ReturnType<typeof useDiagnosisPanel>;

/** 標題列右側那顆按鈕——跟既有「素材座標成效」`<h2>` 放同一個 flex row。 */
export function DiagnosisRunButton({ panel }: { panel: DiagnosisPanelState }) {
  return (
    <Button
      type="button"
      onClick={panel.onRun}
      busy={panel.busy}
      className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {panel.busy ? "判讀中…" : "跑一次判讀"}
    </Button>
  );
}

/** 標題下方、七維分頁與圖表上方的結果區。 */
export function DiagnosisResult({ panel }: { panel: DiagnosisPanelState }) {
  const { state, runError } = panel;

  if (state.status === "loading") {
    return <p className="text-sm text-muted-foreground">判讀讀取中…</p>;
  }
  if (state.status === "error") {
    return <p className="text-sm text-danger">判讀讀取失敗：{state.message}</p>;
  }

  const { diagnosis } = state;

  return (
    <div className="flex flex-col gap-2">
      {runError && <p className="text-sm text-danger">{runError}</p>}
      {diagnosis.status === null ? (
        !panel.busy && <p className="text-sm text-muted-foreground">還沒判讀過這個月的成效。</p>
      ) : diagnosis.status === "running" ? null : (
        <DiagnosisReadout diagnosis={diagnosis} panel={panel} />
      )}
    </div>
  );
}

function DiagnosisReadout({ diagnosis, panel }: { diagnosis: Diagnosis; panel: DiagnosisPanelState }) {
  const { window: readWindow, breakeven, suggestions, no_tagged_spend: noTaggedSpend } = diagnosis;
  const breakevenText =
    breakeven.roas !== null
      ? `賺賠線 ${breakeven.roas.toFixed(2)}x（${breakeven.source}）`
      : `${breakeven.source}，這個月不判賺賠`;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        {DIRECTIONAL_ONLY_NOTE}窗口：{readWindow.start_date} ~ {readWindow.end_date}
      </p>
      <p className="text-sm text-foreground">{breakevenText}</p>
      {suggestions.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {noTaggedSpend
            ? "這個月的花費都還對不到座標：綁定的節點還沒有文案（到投放中心的素材分頁看進度），或花費還沒拉回來。"
            : "有座標，但這一輪判讀沒有給出建議。"}
        </p>
      ) : (
        <>
          {panel.adoptError && <p className="text-sm text-danger">{panel.adoptError}</p>}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {suggestions.map((suggestion, index) => (
              <SuggestionCard
                key={index}
                suggestion={suggestion}
                adopted={suggestion.adopted || panel.adoptedIndexes.has(index)}
                adopting={panel.adoptingIndex === index}
                roundBusy={panel.busy}
                onAdopt={() => panel.onAdopt(index)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** issue diagnosis-lacks-checkable-numbers：一條建議底下那行可核對的數字。保守 ROAS 是
 * 分母含未追蹤花費的那一個（`roas_conservative`），跟座標成效表同一欄，兩邊對得起來。 */
function formatCheckable(n: DiagnosisCheckableNumbers, currency: string): string {
  const roas = n.roas_conservative === null ? "ROAS 未追蹤" : `保守 ROAS ${n.roas_conservative.toFixed(2)}x`;
  return `${formatMoney(n.spend, currency)}・${n.ad_count} 則廣告・${roas}（追蹤覆蓋 ${Math.round(n.roas_coverage * 100)}%）`;
}

function SuggestionCard({
  suggestion, adopted, adopting, roundBusy, onAdopt,
}: {
  suggestion: DiagnosisSuggestion;
  adopted: boolean;
  adopting: boolean;
  /** A new round is submitting or running: these cards are the previous round, and the
   * server already reads the new one, so adopting now would miss (400). */
  roundBusy: boolean;
  onAdopt: () => void;
}) {
  // 票 past-ads-07：可核對數字的花費跟著 suggestion 自己的 currency 走，不是系統 TWD——
  // 後端 attach_checkable_numbers()／_dimension_values() 讓 currency 跟 numbers／
  // compared_with 同源（找不到幣別就兩者都是空），所以這裡有 numbers／compared_with 時
  // currency 必定非 null；用區域變數讓窄化能穿過下面 .map() 的 closure。
  const currency = suggestion.currency;

  return (
    <div className="flex flex-col gap-2 rounded-md border border-border bg-card p-3">
      <p className="text-sm font-medium text-foreground">{suggestion.headline}</p>
      <p className="text-xs text-muted-foreground">{suggestion.evidence}</p>
      {suggestion.numbers && currency && (
        <p className="text-xs text-muted-foreground">
          這一組：{formatCheckable(suggestion.numbers, currency)}
        </p>
      )}
      {(suggestion.compared_with ?? []).length > 0 && currency && (
        <p className="text-xs text-muted-foreground">
          對照：{(suggestion.compared_with ?? [])
            .map((peer) => `${peer.label} ${formatCheckable(peer, currency)}`)
            .join("｜")}
        </p>
      )}
      {suggestion.agreed_by.length >= 2 && (
        <span className="w-fit rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
          兩個判讀器都這麼說
        </span>
      )}
      <Button
        type="button"
        onClick={onAdopt}
        busy={adopting || roundBusy}
        disabledReason={adopted ? "這項建議已採用" : null}
        className="mt-1 w-fit rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {adopted ? "已採用" : adopting ? "採用中…" : "採用"}
      </Button>
    </div>
  );
}
