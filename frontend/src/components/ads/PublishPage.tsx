import { useCallback, useEffect, useState } from "react";
import { AlertCircle, AlertTriangle, ArrowRight, CheckCircle2, ChevronLeft } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { CopyIconButton } from "@/components/layout/CopyIconButton";
import {
  bindCampaign,
  getCampaign,
  getPublish,
  publishCampaign,
  type AdapterKey,
  type CampaignDetail,
  type PublishChecklistNode,
  type PublishDescribe,
} from "@/lib/adsApi";
import { StepButton } from "./nextStep";

/** 逐節點是否已經全部綁定——用來算「配對完成：n／m」，不去解析後端訊息字串
 * （§0「the browser must not re-word it」，訊息只能原樣印）。 */
function bindCounts(c: CampaignDetail): { matched: number; total: number } {
  let total = 1;
  let matched = c.local_state === "bound" ? 1 : 0;
  for (const g of c.groups) {
    total += 1 + g.ads.length;
    if (g.local_state === "bound") matched += 1;
    matched += g.ads.filter((a) => a.local_state === "bound").length;
  }
  return { matched, total };
}

function NodeCard({ node }: { node: PublishChecklistNode }) {
  return (
    <div className="surface" style={node.level === "ad" ? { marginLeft: 24 } : undefined}>
      <div className="surface-header">
        <h3 className="text-sm font-semibold">{node.name}</h3>
      </div>
      <div className="surface-body flex flex-col gap-2">
        {node.level !== "campaign" && (
          <p className="flex items-center gap-1.5 text-xs text-warning">
            <AlertTriangle size={12} /> 名稱要一字不差，配對靠它
          </p>
        )}
        {node.fields.map((f) => (
          <div key={f.label} className="flex items-center gap-2 border-t border-border py-1.5 first:border-t-0">
            <span className="w-24 shrink-0 text-xs text-muted-foreground">{f.label}</span>
            <span className="flex-1 truncate text-sm">{String(f.value)}</span>
            <CopyIconButton ariaLabel={`複製${f.label}`} getText={() => String(f.value)} />
          </div>
        ))}
      </div>
    </div>
  );
}

/** 發布畫面（F03-I16）：一般路徑只顯示 `describe.message`（例如自動發布未接上，決策 1
 * 「從來不是拒絕，是還沒接」）；手動／模擬兩個進階路徑各自的流程見下方兩個子元件。
 * 不新增路由（票只准動 CampaignWorkspace／這個檔），發布畫面是 CampaignWorkspace 裡的一個
 * 內嵌畫面，用 `onClose` 換回原本的分頁。 */
export function PublishPage({
  brandId,
  campaign: c,
  adapter,
  onCampaignChange,
  onClose,
  onViewPerformance,
  onChangeAdapter,
  onGoToAssets,
}: {
  brandId: string;
  campaign: CampaignDetail;
  adapter: AdapterKey;
  onCampaignChange: (campaign: CampaignDetail) => void;
  onClose: () => void;
  onViewPerformance: () => void;
  onChangeAdapter: (adapter: AdapterKey) => void;
  onGoToAssets: () => void;
}) {
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "ready"; describe: PublishDescribe }
  >({ status: "loading" });

  const load = useCallback(() => {
    setState({ status: "loading" });
    const request = getPublish(brandId, c.id, adapter).then((res) => res.describe);
    request
      .then((describe) => setState({ status: "ready", describe }))
      .catch((err: unknown) =>
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取發布方式失敗。" }),
      );
  }, [brandId, c.id, adapter]);

  useEffect(load, [load]);

  const title = adapter === "manual" ? "手動上架準備" : adapter === "simulated" ? "模擬發布（演練）" : "選擇上架方式";
  const missing = c.asset_readiness.total - c.asset_readiness.ready_count;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 text-sm">
        <button type="button" onClick={onClose} className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
          <ChevronLeft size={14} /> {c.name}
        </button>
        <span className="text-muted-foreground">/</span>
        <span className="font-semibold">{title}</span>
      </div>

      {adapter !== "simulated" && missing > 0 && (
        <div className="flex items-center justify-between gap-3 rounded-md border border-danger/30 bg-danger/5 p-4">
          <div className="flex items-start gap-3">
            <AlertCircle size={18} className="mt-0.5 shrink-0 text-danger" />
            <div className="flex flex-col gap-0.5">
              <p className="font-semibold text-danger">還有 {missing} 則廣告沒有素材</p>
              <p className="text-sm text-muted-foreground">現在照清單建，這幾則會是空廣告。</p>
            </div>
          </div>
          <Button onClick={onGoToAssets}>回到素材</Button>
        </div>
      )}

      {state.status === "loading" ? (
        <div className="surface">
          <div className="surface-body py-10 text-center text-sm text-muted-foreground">讀取中…</div>
        </div>
      ) : state.status === "error" ? (
        <div className="surface">
          <div className="surface-body py-10 text-center text-sm text-danger">{state.message}</div>
        </div>
      ) : adapter === "manual" ? (
        <ManualPublish
          brandId={brandId}
          campaign={c}
          describe={state.describe}
          onCampaignChange={onCampaignChange}
          onViewPerformance={onViewPerformance}
        />
      ) : adapter === "simulated" ? (
        <SimulatedPublish
          brandId={brandId}
          campaign={c}
          describe={state.describe}
          onCampaignChange={onCampaignChange}
          onViewPerformance={onViewPerformance}
        />
      ) : (
        <div className="surface">
          <div className="surface-body flex flex-col gap-4 py-10">
            <p className="text-center text-sm text-muted-foreground">
              {state.describe.message ?? "自動發布未接上"}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <StepButton onClick={() => onChangeAdapter("manual")}>手動上架準備</StepButton>
                <p className="text-center text-xs text-muted-foreground">照清單自己在平台上建好，再回來配對</p>
              </div>
              <div className="flex flex-col gap-1">
                <StepButton variant="outline" onClick={() => onChangeAdapter("simulated")}>
                  模擬發布（演練）
                </StepButton>
                <p className="text-center text-xs text-muted-foreground">演練用，產生示意成效，不會真的投放</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ManualPublish({
  brandId,
  campaign: c,
  describe,
  onCampaignChange,
  onViewPerformance,
}: {
  brandId: string;
  campaign: CampaignDetail;
  describe: PublishDescribe;
  onCampaignChange: (campaign: CampaignDetail) => void;
  onViewPerformance: () => void;
}) {
  const [confirmed, setConfirmed] = useState(c.actions.some(a =>
    a.kind === "publish" && a.target_kind === "campaign" && a.after_json.adapter === "manual"));
  const [confirming, setConfirming] = useState(false);
  const [binding, setBinding] = useState(false);
  const [bindError, setBindError] = useState<string | null>(null);
  const [bindMessage, setBindMessage] = useState<string | null>(null);
  const [attempted, setAttempted] = useState(false);

  const counts = bindCounts(c);
  const allBound = attempted && bindMessage === null && counts.matched === counts.total;

  async function confirmPreparation() {
    setConfirming(true);
    setBindError(null);
    try {
      await publishCampaign(brandId, c.id, "manual");
      setConfirmed(true);
      onCampaignChange(await getCampaign(brandId, c.id));
    } catch (err) {
      setBindError(err instanceof Error ? err.message : "確認失敗，請稍後再試。");
    } finally { setConfirming(false); }
  }

  async function handleBind() {
    setBinding(true);
    setBindError(null);
    try {
      const result = await bindCampaign(brandId, c.id);
      onCampaignChange(result.campaign);
      setBindMessage(result.message);
      setAttempted(true);
    } catch (err) {
      setBindError(err instanceof Error ? err.message : "配對失敗，請稍後再試。");
    } finally {
      setBinding(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="surface p-4 text-sm space-y-2">
        <p className="font-semibold">確認手動上架準備</p>
        <p>只在本系統記錄手動上架意圖與預算核准，不會在 Meta 建立廣告或花費廣告費，也不代表已上線。</p>
        <p>平台：Meta；此步驟不選擇或寫入任何廣告帳戶。之後配對會查詢這個品牌已綁定的帳戶。</p>
        <p>期間：{c.start_date || "未設定"} ～ {c.end_date || "未設定"}；每日預算合計：{c.groups.reduce((sum, g) => sum + g.daily_budget, 0).toLocaleString()}；期間總預算：{c.budget_total?.toLocaleString() ?? "未設定"}。</p>
        <p>確認後，本系統會以目前預算作為後續調整的核准上限。</p>
        {!confirmed ? <Button disabled={confirming} onClick={() => void confirmPreparation()}>{confirming ? "記錄中…" : "確認並記錄手動上架準備"}</Button> : <p role="status">已記錄手動上架準備；請在平台完成設定後再配對。</p>}
      </div>
      {describe.checklist.map((node) => (
        <NodeCard key={`${node.level}:${node.id}`} node={node} />
      ))}

      <div className="surface">
        <div className="surface-body flex flex-col items-center gap-2 py-6 text-center">
          {bindError && <p className="text-sm text-danger">{bindError}</p>}
          {!attempted ? (
            <Button onClick={() => void handleBind()} disabled={binding || !confirmed}>
              {binding ? "配對中…" : "我已在 Meta 建好，開始配對"}
            </Button>
          ) : allBound ? (
            <>
              <p className="flex items-center gap-1.5 text-success">
                <CheckCircle2 size={18} /> 配對完成：{counts.matched}／{counts.total} 個節點對上
              </p>
              <p className="text-sm text-muted-foreground">Campaign 已上線，狀態更新為投放中。</p>
              <Button variant="outline" onClick={onViewPerformance}>
                查看成效 <ArrowRight size={13} />
              </Button>
            </>
          ) : (
            <div className="flex w-full flex-col gap-2 text-left">
              <p className="flex items-center gap-1.5 text-warning">
                <AlertTriangle size={16} /> 配對完成：{counts.matched}／{counts.total} 個節點對上
              </p>
              {bindMessage && (
                <div className="field-card">
                  <p className="text-sm">{bindMessage}</p>
                </div>
              )}
              <Button onClick={() => void handleBind()} disabled={binding || !confirmed}>
                {binding ? "配對中…" : "重新配對"}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SimulatedPublish({ onViewPerformance }: {
  brandId: string;
  campaign: CampaignDetail;
  describe: PublishDescribe;
  onCampaignChange: (campaign: CampaignDetail) => void;
  onViewPerformance: () => void;
}) {
  return <div className="surface p-6 flex flex-col items-start gap-3">
    <Badge variant="outline">演練用</Badge>
    <p className="text-sm">隔離演練會使用測試品牌與模擬數字，不會對外投放。到成效頁確認隔離範圍，再逐日輸入成效。</p>
    <Button onClick={onViewPerformance}>前往隔離模擬回收</Button>
  </div>;
}
