import { useEffect, useState } from "react";
import {
  activatePackage,
  buildHandoffPackages,
  createAllMetaPackages,
  fetchHandoff,
  fetchMetaStatus,
  generateCodes,
  publishAllMetaPackages,
  verifyCodes,
  type AccountStructure,
  type CodeAssignment,
  type HandoffPackage,
  type MetaCreateAllResult,
  type MetaMcpStatus,
  type MetaPublishAllResult,
} from "@/lib/warroomApi";
import { AccountStructureCard } from "../PlanStep";
import { Badge } from "../../shared/Badge";

/** Meta 廣告管理員連結（票 M1-01）：後端 `activate_cycle()` 回應沒有帶 url 欄位，前端照
 * `app/ads/meta_mcp.py:ads_manager_url()` 同一套規則（去掉 `act_` 前綴）自己組，不必多打
 * 一次 API 只為了拿一條固定格式的連結。 */
function adsManagerUrl(accountId: string): string {
  const raw = accountId.startsWith("act_") ? accountId.slice(4) : accountId;
  return `https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=${raw}`;
}

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="text-muted-foreground">{label}：<span className="text-foreground">{value}</span></span>
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard?.writeText(value).catch(() => {});
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
        className="shrink-0 text-primary hover:underline"
      >
        {copied ? "已複製" : "複製"}
      </button>
    </div>
  );
}

/** 期別配碼＋交接包本體（S8.37-46，吸收 `ads_handoff.html`）。一鍵建到 Meta／發布全部
 * （票 M1-01）也放在這裡，不拆另一個檔：兩顆按鈕成功後都要重讀 `data`（讓包的 mapping
 * 徽章更新），跟這裡既有的 `load()` 是同一份重讀邏輯，拆檔只會多繞一手 props 回呼。 */
export function PackagesSection({ brandId, cycleId, endDate }: { brandId: string; cycleId: string; endDate: string }) {
  const [data, setData] = useState<{ packages: HandoffPackage[]; codes: CodeAssignment[]; codes_verify_mismatch: string[] | null; account_structure: AccountStructure } | null>(null);
  const [building, setBuilding] = useState(false);
  const [verifyResult, setVerifyResult] = useState<string[] | null>(null);
  const [reportMsg, setReportMsg] = useState<string | null>(null);
  const [metaStatus, setMetaStatus] = useState<MetaMcpStatus | null>(null);
  const [creatingMeta, setCreatingMeta] = useState(false);
  const [publishingMeta, setPublishingMeta] = useState(false);
  const [createResult, setCreateResult] = useState<MetaCreateAllResult | null>(null);
  const [publishResult, setPublishResult] = useState<MetaPublishAllResult | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);

  function load() {
    fetchHandoff(brandId, cycleId).then(setData);
  }
  useEffect(load, [brandId, cycleId]);
  useEffect(() => {
    fetchMetaStatus(brandId, cycleId).then(setMetaStatus);
  }, [brandId, cycleId]);

  async function build() {
    setBuilding(true);
    try {
      await buildHandoffPackages(brandId, cycleId);
      load();
    } finally {
      setBuilding(false);
    }
  }

  async function activate(pkg: HandoffPackage) {
    const metaId = window.prompt(`輸入 Meta 給的行銷活動編號，確認「${pkg.campaign_name}」已經在 Meta 建好也開始跑了`);
    if (!metaId) return;
    await activatePackage(brandId, cycleId, pkg.id, metaId);
    load();
  }

  if (!data) return <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">讀取中…</div>;

  async function createAllMeta() {
    setCreatingMeta(true);
    setMetaError(null);
    setCreateResult(null);
    try {
      const result = await createAllMetaPackages(brandId, cycleId);
      setCreateResult(result);
      load();
    } catch (err) {
      setMetaError(err instanceof Error ? err.message : "建立失敗，請稍後再試。");
    } finally {
      setCreatingMeta(false);
    }
  }

  async function publishAllMeta() {
    const totalDailyBudget = (data?.packages ?? []).filter((p) => p.mapping).reduce((sum, p) => sum + p.daily_budget, 0);
    const confirmed = window.confirm(
      `會開始花錢：每天最多 NT$${totalDailyBudget.toLocaleString("zh-TW")}（各包日預算加總），跑到 ${endDate}。確定發布？`,
    );
    if (!confirmed) return;
    setPublishingMeta(true);
    setMetaError(null);
    setPublishResult(null);
    try {
      const result = await publishAllMetaPackages(brandId, cycleId);
      setPublishResult(result);
      load();
    } catch (err) {
      setMetaError(err instanceof Error ? err.message : "發布失敗，請稍後再試。");
    } finally {
      setPublishingMeta(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <AccountStructureCard structure={data.account_structure} />

      <div className="rounded-lg border border-border bg-card p-4 text-sm shadow-[var(--shadow-card)]">
        <p className="font-medium text-foreground">其他要設定</p>
        <p className="mt-1 text-muted-foreground">轉換事件：Purchase／歸因視窗：7 天點擊、1 天瀏覽／異業合作：無</p>
      </div>

      <div id="handoff-codes" className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        <div className="flex items-center justify-between">
          <p className="font-medium text-foreground">期別配碼</p>
          {data.codes.length === 0 && (
            <button type="button" onClick={() => void generateCodes(brandId, cycleId, 15).then(load)} className="rounded-md border border-primary px-3 py-1 text-xs font-medium text-primary hover:bg-primary/10">
              產出配碼
            </button>
          )}
        </div>
        {data.codes.length > 0 && (
          <>
            <table className="mt-2 w-full text-left text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-1">類型</th><th>字碼</th><th>折數</th><th>上限</th><th>效期</th>
                </tr>
              </thead>
              <tbody>
                {data.codes.map((c) => (
                  <tr key={c.code} className="border-t border-border text-foreground">
                    <td className="py-1">{c.kind_label}</td><td>{c.code}</td><td>{c.discount_pct}%</td><td>{c.usage_cap}</td><td>{c.valid_until}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button
              type="button"
              onClick={() => void verifyCodes(brandId, cycleId).then((res) => setVerifyResult(res.mismatches))}
              className="mt-2 rounded-md border border-border px-3 py-1 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
            >
              上線前校驗（比對 EasyStore 後台）
            </button>
            {verifyResult && (
              <div className="mt-2">
                {verifyResult.length === 0 ? (
                  <Badge tone="success">校驗一致</Badge>
                ) : (
                  verifyResult.map((m, i) => (
                    <p key={i} className="text-xs text-warning">
                      <Badge tone="warning">不符</Badge> {m}
                    </p>
                  ))
                )}
              </div>
            )}
          </>
        )}
      </div>

      <div id="handoff-packages" className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        <div className="flex items-center justify-between">
          <p className="font-medium text-foreground">交接包</p>
          {data.packages.length > 0 && (
            <button type="button" onClick={() => void build()} disabled={building} className="rounded-md border border-border px-3 py-1 text-xs font-medium text-foreground hover:border-primary hover:text-primary">
              {building ? "重新產出中…" : "重出一份交接包"}
            </button>
          )}
        </div>
        {metaStatus?.ok && (
          <div className="mt-3 flex flex-col gap-2 border-t border-border pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => void createAllMeta()}
                disabled={creatingMeta || publishingMeta}
                className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creatingMeta ? "建立中…" : "一鍵建到 Meta（暫停）"}
              </button>
              <span className="text-xs text-muted-foreground">建好的廣告先暫停，你按「發布」才會開始花錢。</span>
            </div>
            {createResult && (
              <div className="text-sm">
                <p className="text-foreground">{createResult.created} 包已建到 Meta（暫停）。</p>
                {createResult.failed.map((f) => (
                  <p key={f.package_id} className="text-xs text-danger">「{f.package_name}」：{f.reason}</p>
                ))}
              </div>
            )}
            <div>
              <button
                type="button"
                onClick={() => void publishAllMeta()}
                disabled={creatingMeta || publishingMeta}
                className="rounded-md border border-primary px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {publishingMeta ? "發布中…" : "發布全部"}
              </button>
            </div>
            {publishResult && (
              <div className="text-sm">
                {publishResult.activated > 0 && (
                  <p className="text-success">
                    已開始投放。{" "}
                    {metaStatus.account_id && (
                      <a
                        href={adsManagerUrl(metaStatus.account_id)}
                        target="_blank"
                        rel="noreferrer"
                        className="text-primary hover:underline"
                      >
                        到 Meta 後台看
                      </a>
                    )}
                  </p>
                )}
                {publishResult.failed.map((f) => (
                  <p key={f.package_id} className="text-xs text-danger">{f.reason}</p>
                ))}
              </div>
            )}
            {metaError && <p className="text-sm text-danger">{metaError}</p>}
          </div>
        )}
        {metaStatus && !metaStatus.ok && (
          <p className="mt-3 border-t border-border pt-3 text-sm text-muted-foreground">{metaStatus.reason}</p>
        )}
        {data.packages.length === 0 ? (
          <div className="mt-2 flex flex-col items-start gap-2">
            <p className="text-sm text-muted-foreground">這期交接包還沒產生。</p>
            <button type="button" onClick={() => void build()} disabled={building} className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50">
              {building ? "產出中…" : "產出交接包"}
            </button>
          </div>
        ) : (
          <div className="mt-2 flex flex-col gap-3">
            {data.packages.map((pkg) => (
              <div key={pkg.id} className="flex flex-col gap-1 rounded-md border border-border p-3">
                <p className="break-all text-sm font-medium text-foreground">{pkg.campaign_name}</p>
                <CopyField label="行銷活動" value={pkg.campaign_name} />
                <CopyField label="廣告組合" value={pkg.adset_name} />
                <CopyField label="廣告" value={pkg.ad_name} />
                {pkg.full_url && <CopyField label="到達網址" value={pkg.full_url} />}
                <p className="text-xs text-muted-foreground">日預算 NT$ {pkg.daily_budget.toLocaleString("zh-TW")}・{pkg.schedule_text}</p>
                {pkg.image_prompts.length > 0 && (
                  <details className="text-xs text-muted-foreground">
                    <summary className="cursor-pointer text-primary">圖片提示詞</summary>
                    <ul className="mt-1 list-disc pl-4">
                      {pkg.image_prompts.map((p, i) => <li key={i}>{p}</li>)}
                    </ul>
                  </details>
                )}
                {pkg.mapping ? (
                  <Badge tone="success">已建到 Meta（{pkg.mapping.meta_campaign_id}）</Badge>
                ) : (
                  <button type="button" onClick={() => void activate(pkg)} className="self-start rounded-md border border-primary px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10">
                    具名投放授權
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        <button type="button" onClick={() => setReportMsg("已記下這次回報，感謝協助盤點。")} className="mt-2 text-xs text-muted-foreground hover:underline">
          找不到這欄位？回報一個欄位缺漏
        </button>
        {reportMsg && <p className="text-xs text-success">{reportMsg}</p>}
      </div>
    </div>
  );
}
