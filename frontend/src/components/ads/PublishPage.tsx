import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronLeft } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { CopyIconButton } from "@/components/layout/CopyIconButton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/layout/ui/dialog";
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
}: {
  brandId: string;
  campaign: CampaignDetail;
  adapter: AdapterKey;
  onCampaignChange: (campaign: CampaignDetail) => void;
  onClose: () => void;
  onViewPerformance: () => void;
}) {
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "ready"; describe: PublishDescribe }
  >({ status: "loading" });

  const load = useCallback(() => {
    setState({ status: "loading" });
    // 手動發布第一次進來要順便落地一次核准＋操作紀錄（決策：「使用者確認手動發布」就是打開
    // 這個進階選單項目本身），已經發布過（`actions` 已有一列 publish）就只讀，不重複寫。
    const alreadyPublished = c.actions.some(
      (a) => a.kind === "publish" && a.target_kind === "campaign",
    );
    const request =
      adapter === "manual" && !alreadyPublished
        ? publishCampaign(brandId, c.id, "manual")
        : getPublish(brandId, c.id, adapter).then((res) => res.describe);
    request
      .then((describe) => setState({ status: "ready", describe }))
      .catch((err: unknown) =>
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取發布方式失敗。" }),
      );
  }, [brandId, c.actions, c.id, adapter]);

  useEffect(load, [load]);

  const title = adapter === "manual" ? "手動發布（進階）" : adapter === "simulated" ? "模擬發布（演練用）" : "發布 Campaign";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 text-sm">
        <button type="button" onClick={onClose} className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
          <ChevronLeft size={14} /> {c.name}
        </button>
        <span className="text-muted-foreground">/</span>
        <span className="font-semibold">{title}</span>
      </div>

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
          <div className="surface-body py-10 text-center text-sm text-muted-foreground">
            {state.describe.message ?? "自動發布未接上"}
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
  const [binding, setBinding] = useState(false);
  const [bindError, setBindError] = useState<string | null>(null);
  const [bindMessage, setBindMessage] = useState<string | null>(null);
  const [attempted, setAttempted] = useState(false);

  const counts = bindCounts(c);
  const allBound = attempted && bindMessage === null && counts.matched === counts.total;

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
      {describe.checklist.map((node) => (
        <NodeCard key={`${node.level}:${node.id}`} node={node} />
      ))}

      <div className="surface">
        <div className="surface-body flex flex-col items-center gap-2 py-6 text-center">
          {bindError && <p className="text-sm text-danger">{bindError}</p>}
          {!attempted ? (
            <Button onClick={() => void handleBind()} disabled={binding}>
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
              <Button onClick={() => void handleBind()} disabled={binding}>
                {binding ? "配對中…" : "重新配對"}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SimulatedPublish({
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
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handleConfirm() {
    setPublishing(true);
    setError(null);
    try {
      await publishCampaign(brandId, c.id, "simulated");
      const fresh = await getCampaign(brandId, c.id);
      onCampaignChange(fresh);
      setDone(true);
      setConfirmOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "模擬發布失敗，請稍後再試。");
    } finally {
      setPublishing(false);
    }
  }

  const counts = bindCounts(c);

  return (
    <div className="flex flex-col gap-3">
      <div className="surface">
        <div className="surface-body flex flex-col items-center gap-3 py-8 text-center">
          {done ? (
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
            <>
              <Badge variant="outline">演練用</Badge>
              <p className="max-w-md text-sm text-muted-foreground">{describe.message}</p>
              {error && <p className="text-sm text-danger">{error}</p>}
              <Button onClick={() => setConfirmOpen(true)} disabled={publishing}>
                {publishing ? "產生中…" : "模擬發布"}
              </Button>
            </>
          )}
        </div>
      </div>

      <Dialog open={confirmOpen} onOpenChange={(open) => !open && setConfirmOpen(false)}>
        <DialogContent>
          <DialogTitle>模擬發布</DialogTitle>
          <DialogDescription>{describe.message}</DialogDescription>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirmOpen(false)} disabled={publishing}>
              取消
            </Button>
            <Button type="button" onClick={() => void handleConfirm()} disabled={publishing}>
              {publishing ? "產生中…" : "確認模擬發布"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
