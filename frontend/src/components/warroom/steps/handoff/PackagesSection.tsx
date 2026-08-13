import { useEffect, useState } from "react";
import {
  activatePackage,
  buildHandoffPackages,
  fetchHandoff,
  generateCodes,
  verifyCodes,
  type AccountStructure,
  type CodeAssignment,
  type HandoffPackage,
} from "@/lib/warroomApi";
import { AccountStructureCard } from "../PlanStep";
import { Badge } from "../../shared/Badge";

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

/** 期別配碼＋交接包本體（S8.37-46，吸收 `ads_handoff.html`）。 */
export function PackagesSection({ brandId, cycleId }: { brandId: string; cycleId: string }) {
  const [data, setData] = useState<{ packages: HandoffPackage[]; codes: CodeAssignment[]; codes_verify_mismatch: string[] | null; account_structure: AccountStructure } | null>(null);
  const [building, setBuilding] = useState(false);
  const [verifyResult, setVerifyResult] = useState<string[] | null>(null);
  const [reportMsg, setReportMsg] = useState<string | null>(null);

  function load() {
    fetchHandoff(brandId, cycleId).then(setData);
  }
  useEffect(load, [brandId, cycleId]);

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
                  <Badge tone="success">已授權投放（{pkg.mapping.meta_campaign_id}）</Badge>
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
