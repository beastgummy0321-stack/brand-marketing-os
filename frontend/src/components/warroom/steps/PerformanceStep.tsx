import { useEffect, useState } from "react";
import { formatCurrency, formatPercent, formatRelativeHours, formatRoas } from "@/lib/format";
import { triggerImmediateSync } from "@/lib/api";
import { useFormSubmit } from "@/lib/useFormSubmit";
import {
  fetchHealthLights, fetchPerformance, importPerformanceCsv, simulatePerformance, submitManualPerformance,
  type Cycle, type CsvImportResult, type HealthLights, type PerformanceSummary, type ReadingResult,
} from "@/lib/warroomApi";
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
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  function load() {
    fetchPerformance(brandId, cycle.id).then((res) => {
      setSummary(res.summary);
      setReading(res.reading);
      setConfidence(res.confidence_label);
      setLastSyncedAt(res.last_synced_at ?? null);
    });
  }
  useEffect(load, [brandId, cycle.id]);
  useEffect(() => {
    fetchHealthLights(brandId, cycle.id).then(setLights);
  }, [brandId, cycle.id]);

  async function updateNow() {
    setSyncing(true);
    setSyncError(null);
    try {
      const result = await triggerImmediateSync(brandId);
      setLastSyncedAt(result.updated_at);
      load();
      fetchHealthLights(brandId, cycle.id).then(setLights);
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : "更新失敗，請稍後再試。");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-[var(--shadow-card)]">
        <div>
          <p className="text-sm font-medium text-foreground">成效同步</p>
          <p className="text-xs text-muted-foreground">{lastSyncedAt ? `更新於 ${formatRelativeHours(lastSyncedAt)}` : "尚未更新"}</p>
        </div>
        <button type="button" onClick={() => void updateNow()} disabled={syncing} className="rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50">
          {syncing ? "更新中…" : "立刻更新"}
        </button>
      </div>
      {syncError && <p className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{syncError}</p>}
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
            <Kpi label="CTR" value={summary.kpis.ctr !== null ? formatPercent(summary.kpis.ctr) : null} />
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

      <ManualCsvPanel brandId={brandId} cycleId={cycle.id} onImported={load} />

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

const MANUAL_FIELDS: { key: string; label: string; required?: boolean }[] = [
  { key: "spend", label: "花費金額", required: true },
  { key: "impressions", label: "曝光次數" },
  { key: "clicks", label: "連結點擊次數" },
  { key: "conversions", label: "購買次數" },
  { key: "revenue", label: "購買轉換價值" },
  { key: "reach", label: "觸及人數" },
  { key: "date_start", label: "開始日期" },
  { key: "date_stop", label: "結束日期" },
];

/** 票 01：T4 清倉把使用者自己填成效／匯入 Meta CSV 的入口一起刪掉了；DECIDED——收合面板
 * 就地做，不另開 SPA 路由（舊設計指向的 Jinja 子頁已經不在了，不值得為此多開一條路由）。
 * 送出中鎖按鈕／失敗人話錯誤沿用全站共用的 `useFormSubmit`（lib/useFormSubmit.ts），
 * 不另刻一份狀態機。 */
function ManualCsvPanel({ brandId, cycleId, onImported }: { brandId: string; cycleId: string; onImported: () => void }) {
  const [fields, setFields] = useState<Record<string, string>>({});
  const manualForm = useFormSubmit(async () => {
    await submitManualPerformance(brandId, cycleId, fields);
    setFields({});
    onImported();
  });

  const [csvResult, setCsvResult] = useState<CsvImportResult | null>(null);
  const csvForm = useFormSubmit(async (file: File) => {
    setCsvResult(await importPerformanceCsv(brandId, cycleId, file));
    onImported();
  });

  return (
    <details className="rounded-lg border border-border bg-card p-4 text-sm shadow-[var(--shadow-card)]">
      <summary className="cursor-pointer font-medium text-foreground">自己填成效／匯入 Meta CSV</summary>
      <div className="mt-3 flex flex-col gap-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void manualForm.submit();
          }}
          className="flex flex-col gap-2"
        >
          <p className="text-xs text-muted-foreground">API 拉不到、CSV 也匯不進來時的最後退路，花費金額必填。</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {MANUAL_FIELDS.map((f) => (
              <label key={f.key} className="flex flex-col gap-1 text-xs text-muted-foreground">
                {f.label}{f.required ? "（必填）" : ""}
                <input
                  type="text"
                  value={fields[f.key] ?? ""}
                  onChange={(e) => setFields((prev) => ({ ...prev, [f.key]: e.target.value }))}
                  className="rounded-md border border-border bg-background px-2 py-1 text-foreground"
                />
              </label>
            ))}
          </div>
          <button type="submit" disabled={manualForm.saving || !fields.spend} className="w-fit rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50">
            {manualForm.saving ? "送出中…" : "記下這筆"}
          </button>
          {manualForm.error && <p className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{manualForm.error}</p>}
        </form>

        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <p className="text-xs text-muted-foreground">從 Meta 廣告管理員匯出的 CSV，直接上傳。</p>
          <input
            type="file"
            accept=".csv"
            disabled={csvForm.saving}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void csvForm.submit(file);
            }}
            className="text-xs text-foreground"
          />
          {csvForm.error && <p className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{csvForm.error}</p>}
          {csvResult && (
            <p className="text-xs text-success">
              匯入 {csvResult.imported} 筆成效資料，對回 {csvResult.matched_assets} 則素材。
              {csvResult.quarantined > 0 && `${csvResult.quarantined} 筆數字不合理已擱在一旁。`}
              {csvResult.skipped > 0 && `${csvResult.skipped} 筆重複略過。`}
            </p>
          )}
        </div>
      </div>
    </details>
  );
}
