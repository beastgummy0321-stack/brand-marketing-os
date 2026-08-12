import { useEffect, useState } from "react";
import { formatCurrency, formatRoas } from "@/lib/format";
import { fetchHealthLights, fetchPerformance, simulatePerformance, type Cycle, type HealthLights, type PerformanceSummary, type ReadingResult } from "@/lib/warroomApi";
import { HealthLightsRow } from "../shared/HealthLightsRow";
import { Badge } from "../shared/Badge";

/** 成效（S8R.20-22 重設計，吸收舊 `S8.51-58`）：最上方一排健康燈號（S8R.20，全綠收合成一行，
 * 異常才展開），底下 KPI 表格／判讀結論卡完整細節不變（漸進揭露，S8R.22）。期中檢查點
 * （原本掛在本步驟開頭）已依 S8R.19 併回「交接」區塊，本步驟不再重複顯示。資料操作子頁
 * （CSV／手動填寫／蝦皮期別碼／對帳三題／營收校準）契約明講「入口只寫『點下去去這個子頁』，
 * 內部長相不屬本頁」，這裡只留入口訊息，不做死連結（跟 S7「開新檔期」同一慣例）。 */
export function PerformanceStep({ brandId, cycle }: { brandId: string; cycle: Cycle }) {
  const [summary, setSummary] = useState<PerformanceSummary | null | undefined>(undefined);
  const [reading, setReading] = useState<ReadingResult | null>(null);
  const [confidence, setConfidence] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [lights, setLights] = useState<HealthLights | null>(null);

  function load() {
    fetchPerformance(brandId, cycle.id).then((res) => {
      setSummary(res.summary);
      setReading(res.reading);
      setConfidence(res.confidence_label);
    });
  }
  useEffect(load, [brandId, cycle.id]);
  useEffect(() => {
    fetchHealthLights(brandId, cycle.id).then(setLights);
  }, [brandId, cycle.id]);

  return (
    <div className="flex flex-col gap-4">
      {lights && <HealthLightsRow lights={lights} />}

      {cycle.phase === "simulation" && (
        <div className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
          紙上模擬期：可以產生一組模擬成效來看畫面長什麼樣。
          <button type="button" onClick={() => void simulatePerformance(brandId, cycle.id).then(load)} className="ml-2 rounded-md border border-warning px-2 py-0.5 text-xs font-medium hover:bg-warning/20">
            產生一組模擬成效
          </button>
        </div>
      )}

      {summary === undefined ? (
        <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">讀取中…</div>
      ) : summary === null ? (
        <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">資料不足，還沒有可以算的成效數字。</div>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-3">
            <Kpi label="CTR" value={summary.kpis.ctr !== null ? `${summary.kpis.ctr}%` : null} />
            <Kpi label="CPC" value={summary.kpis.cpc !== null ? formatCurrency(summary.kpis.cpc) : null} />
            <Kpi label="CPA" value={summary.kpis.cpa !== null ? formatCurrency(summary.kpis.cpa) : null} />
            <Kpi label="ROAS" value={summary.kpis.roas !== null ? formatRoas(summary.kpis.roas) : null} />
          </div>
          {summary.discarded_rows > 0 && (
            <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
              {summary.discarded_rows} 筆數字不合理（點擊比曝光還多、負數）已被系統擱置不列入計算。
            </p>
          )}
          {reading && (
            <div className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={reading.status === "scale_candidate" ? "success" : reading.status === "pause_candidate" ? "danger" : "neutral"}>{reading.status_label}</Badge>
                <span className="text-xs text-muted-foreground">{reading.statistical_level_label}</span>
              </div>
              <p className="mt-2 text-sm text-foreground">{reading.llm_explanation}</p>
              <details className="mt-2 text-xs text-muted-foreground">
                <summary className="cursor-pointer text-primary">判讀依據</summary>
                <ul className="mt-1 list-disc pl-4">
                  {reading.reasons.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              </details>
            </div>
          )}
        </>
      )}

      <div className="rounded-lg border border-border bg-card p-4 text-sm shadow-[var(--shadow-card)]">
        <p className="font-medium text-foreground">本期判讀可信度</p>
        <p className="mt-1 text-muted-foreground">{confidence}</p>
        <button type="button" onClick={() => setNotice("這一段還沒有建置：對帳三題、蝦皮期別碼、營收校準這些資料操作子頁。")} className="mt-1 text-xs text-primary hover:underline">
          去資料操作子頁
        </button>
        {notice && <p className="mt-1 text-xs text-muted-foreground">{notice}</p>}
      </div>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3 text-center shadow-[var(--shadow-card)]">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold text-foreground">{value ?? "資料不足"}</p>
    </div>
  );
}
