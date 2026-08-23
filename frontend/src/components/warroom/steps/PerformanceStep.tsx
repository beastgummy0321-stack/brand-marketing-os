import { useEffect, useState } from "react";
import { formatCurrency, formatPercent, formatRelativeHours, formatRoas, formatSyncTime, formatUsd } from "@/lib/format";
import { triggerImmediateSync } from "@/lib/api";
import { useFormSubmit } from "@/lib/useFormSubmit";
import {
  deletePerformanceBatch, fetchHealthLights, fetchPerformance, fetchPerformanceBatches, importPerformanceCsv,
  simulatePerformance, submitManualPerformance,
  type AssetBreakdownRow, type BottleneckResult, type Cycle, type CsvImportResult, type HealthLights,
  type PerformanceBatch, type PerformanceSummary, type ReadingResult,
} from "@/lib/warroomApi";
import { HealthLightsRow } from "../shared/HealthLightsRow";
import { Badge } from "../shared/Badge";

// app/ads/performance.py import_rows()：source 只有這兩種真人來源（'simulated' 已被
// performance_batches.list_batches() 排除，不會出現在這份清單）。
const IMPORT_SOURCE_LABELS: Record<string, string> = { csv: "CSV", manual: "手填" };

/** 成效（S8R.20-22 重設計，吸收舊 `S8.51-58`）：最上方一排健康燈號（S8R.20，全綠收合成一行，
 * 異常才展開），底下 KPI 表格／判讀結論卡完整細節不變（漸進揭露，S8R.22）。期中檢查點
 * （原本掛在本步驟開頭）已依 S8R.19 併回「交接」區塊，本步驟不再重複顯示。資料操作子頁
 * （CSV／手動填寫／蝦皮期別碼／對帳三題／營收校準）契約明講「入口只寫『點下去去這個子頁』，
 * 內部長相不屬本頁」，這裡只留入口訊息，不做死連結（跟 S7「開新檔期」同一慣例）。 */
export function PerformanceStep({ brandId, cycle }: { brandId: string; cycle: Cycle }) {
  const [summary, setSummary] = useState<PerformanceSummary | null | undefined>(undefined);
  const [reading, setReading] = useState<ReadingResult | null>(null);
  const [bottleneck, setBottleneck] = useState<BottleneckResult | null>(null);
  const [confidence, setConfidence] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [lights, setLights] = useState<HealthLights | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [batches, setBatches] = useState<PerformanceBatch[] | null>(null);
  const [estimatedRerunCost, setEstimatedRerunCost] = useState(0);

  function load() {
    fetchPerformance(brandId, cycle.id).then((res) => {
      setSummary(res.summary);
      setReading(res.reading);
      setBottleneck(res.bottleneck);
      setConfidence(res.confidence_label);
      setLastSyncedAt(res.last_synced_at ?? null);
    });
  }
  function loadBatches() {
    fetchPerformanceBatches(brandId, cycle.id).then((res) => {
      setBatches(res.items);
      setEstimatedRerunCost(res.estimated_rerun_cost);
    });
  }
  useEffect(load, [brandId, cycle.id]);
  useEffect(loadBatches, [brandId, cycle.id]);
  useEffect(() => {
    fetchHealthLights(brandId, cycle.id).then(setLights);
  }, [brandId, cycle.id]);

  // 匯入（CSV／手填）成功後總計跟「最近匯入」清單都要跟著動；撤銷一批後總計跟清單也是
  // 同一套要重抓的東西，兩邊共用同一顆函式，不寫兩份幾乎一樣的 reload 邏輯。
  function refreshAfterPerformanceChange() {
    load();
    loadBatches();
  }

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
              <AssetBreakdownTable rows={reading.asset_breakdown} />
            </div>
          )}
          {bottleneck && (
            <div className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
              <p className="text-sm font-medium text-foreground">錢卡在哪一關</p>
              <BottleneckBody bottleneck={bottleneck} />
            </div>
          )}
        </>
      )}

      {cycle.status === "CLOSED" && (
        <p className="rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
          這期已經收帳了。現在補進去的數字，系統會重新算一次結論，並告訴你哪裡變了。
        </p>
      )}
      <ManualCsvPanel brandId={brandId} cycleId={cycle.id} onImported={refreshAfterPerformanceChange} />

      <RecentImportsPanel
        brandId={brandId}
        cycleId={cycle.id}
        batches={batches}
        estimatedRerunCost={estimatedRerunCost}
        onChanged={refreshAfterPerformanceChange}
      />

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

/** 票 S1-01：最近匯入＋整批撤銷（最近 5 批，新到舊；已排除模擬資料，後端
 * `performance_batches.list_batches()` 保證）。撤銷一批走 `window.confirm`（沿用
 * `ProposalBook.tsx:172` 同一種一鍵確認框寫法）。 */
function RecentImportsPanel({
  brandId, cycleId, batches, estimatedRerunCost, onChanged,
}: {
  brandId: string;
  cycleId: string;
  batches: PerformanceBatch[] | null;
  estimatedRerunCost: number;
  onChanged: () => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 text-sm shadow-[var(--shadow-card)]">
      <p className="font-medium text-foreground">最近匯入</p>
      {batches === null ? (
        <p className="mt-1 text-xs text-muted-foreground">讀取中…</p>
      ) : batches.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">還沒有匯入過成效。</p>
      ) : (
        <ul className="mt-2 flex flex-col gap-2">
          {batches.map((b) => (
            <BatchRow key={b.batch_id} brandId={brandId} cycleId={cycleId} batch={b} estimatedRerunCost={estimatedRerunCost} onChanged={onChanged} />
          ))}
        </ul>
      )}
    </div>
  );
}

function BatchRow({
  brandId, cycleId, batch, estimatedRerunCost, onChanged,
}: {
  brandId: string;
  cycleId: string;
  batch: PerformanceBatch;
  estimatedRerunCost: number;
  onChanged: () => void;
}) {
  const [message, setMessage] = useState<string | null>(null);
  const undoForm = useFormSubmit(async () => {
    const result = await deletePerformanceBatch(brandId, cycleId, batch.batch_id);
    setMessage(result.message);
    onChanged();
  });

  function onClick() {
    const confirmed = window.confirm(
      `撤銷後這批數字會消失，要重新上傳才能找回。結論會自動重算，最多花費 ${formatUsd(estimatedRerunCost)}。確定撤銷？`,
    );
    if (!confirmed) return;
    void undoForm.submit();
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-2 text-xs">
      <span className="text-foreground">
        {formatSyncTime(batch.imported_at)}　{IMPORT_SOURCE_LABELS[batch.source] ?? batch.source}　寫入 {batch.rows} 筆
        {batch.quarantined > 0 && `（${batch.quarantined} 筆擱在一旁）`}　花費 {formatCurrency(batch.spend)}
      </span>
      <button
        type="button"
        onClick={onClick}
        disabled={undoForm.saving}
        className="rounded-md border border-danger/40 px-2 py-1 text-xs font-medium text-danger hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {undoForm.saving ? "撤銷中…" : "撤銷這批"}
      </button>
      {undoForm.error && <p className="w-full text-danger">{undoForm.error}</p>}
      {message && <p className="w-full text-success">{message}</p>}
    </li>
  );
}

/** 素材層成效表（契約 C／D4 第 3 點）：一支廣告一列，ROAS 最低的那支標成「拖累檔期」——
 * 使用者不必自己比數字就知道是哪支在賠錢。陣列空的（沒有對得回素材的成效列）就整段不畫，
 * 不畫空表格、不湊一列假資料（鐵則 16）。 */
function AssetBreakdownTable({ rows }: { rows: AssetBreakdownRow[] | undefined }) {
  if (!rows || rows.length === 0) return null;
  const roasValues = rows.map((r) => r.kpis.roas).filter((v): v is number => v !== null);
  const worstRoas = roasValues.length > 0 ? Math.min(...roasValues) : null;

  return (
    <div className="mt-3 overflow-x-auto border-t border-border pt-3">
      <table className="w-full min-w-[480px] text-xs">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="py-1 pr-2 font-medium">廣告</th>
            <th className="py-1 pr-2 font-medium">ROAS</th>
            <th className="py-1 pr-2 font-medium">CTR</th>
            <th className="py-1 pr-2 font-medium">CPA</th>
            <th className="py-1 pr-2 font-medium">花費</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isWorst = worstRoas !== null && row.kpis.roas === worstRoas;
            return (
              <tr key={row.pkg_id} className="border-t border-border/60">
                <td className="py-1.5 pr-2 text-foreground">
                  <span className="flex flex-wrap items-center gap-1.5">
                    {row.asset_name}
                    {isWorst && <Badge tone="danger">拖累檔期</Badge>}
                  </span>
                </td>
                <td className="py-1.5 pr-2 text-foreground">{row.kpis.roas !== null ? formatRoas(row.kpis.roas) : "資料不足"}</td>
                <td className="py-1.5 pr-2 text-foreground">{row.kpis.ctr !== null ? formatPercent(row.kpis.ctr) : "資料不足"}</td>
                <td className="py-1.5 pr-2 text-foreground">{row.kpis.cpa !== null ? formatCurrency(row.kpis.cpa) : "資料不足"}</td>
                <td className="py-1.5 pr-2 text-foreground">{formatCurrency(row.spend)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** 票 C2-01：CPA 恆等式拆解結果——一行主結論＋每個因子的貢獻度，跟判讀狀態並列
 * （不是取代它）。`reliable: false` 時只講一句話，不列任何因子（樣本太少，不硬猜）。 */
function BottleneckBody({ bottleneck }: { bottleneck: BottleneckResult }) {
  if (!bottleneck.reliable) {
    return <p className="mt-2 text-sm text-muted-foreground">{bottleneck.reason_unreliable}</p>;
  }
  const primaryFactor = bottleneck.factors.find((f) => f.key === bottleneck.primary);
  const pctWorse = bottleneck.cpa_ratio !== null ? Math.round((bottleneck.cpa_ratio - 1) * 100) : null;
  return (
    <div className="mt-2 space-y-2 text-sm">
      {bottleneck.underspend && <p className="text-warning">這期預算沒花完，量本身就不夠。</p>}
      <p className="text-foreground">
        {primaryFactor
          ? `主要卡在：${primaryFactor.label}${pctWorse !== null ? `（下面三項合起來，讓每筆成交成本比你自己的過去多 ${pctWorse}%）` : ""}`
          : bottleneck.cpa_ratio !== null && bottleneck.factors.every((f) => f.share === null)
            ? "有幾項變化不小，但一好一壞互相抵銷，整體每筆成交成本跟你自己的過去差不多。"
            : "沒有特別突出的瓶頸，這期的表現都在你自己的正常範圍內。"}
      </p>
      <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
        {bottleneck.factors.map((f) => (
          <li key={f.key}>
            <span className="font-medium text-foreground">{f.label}：</span>
            {f.detail}
            {f.share !== null &&
              (f.share >= 0
                ? `（貢獻約 ${Math.round(f.share * 100)}%）`
                : `（這項其實比過去好，反而抵銷了約 ${Math.round(Math.abs(f.share) * 100)}%）`)}
            {f.sub === "audience_too_narrow" && "——很可能是受眾圈得太窄，同一批人被打太多次。"}
          </li>
        ))}
      </ul>
      {bottleneck.reference && (
        <p className="text-xs text-muted-foreground">
          旁邊參考：{bottleneck.reference.label}的點擊率約 {formatPercent(bottleneck.reference.ctr)}（不是你的同業數字，只供參考，不影響判定）。
        </p>
      )}
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
  const [manualResult, setManualResult] = useState<CsvImportResult | null>(null);
  const manualForm = useFormSubmit(async () => {
    setManualResult(await submitManualPerformance(brandId, cycleId, fields));
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
          {manualResult && (
            <p className="text-xs text-success">
              {manualResult.imported > 0 ? `記下 ${manualResult.imported} 筆成效資料。` : "這筆沒有記下新資料。"}
              {manualResult.skipped > 0 && `${manualResult.skipped} 筆重複略過。`}
            </p>
          )}
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
