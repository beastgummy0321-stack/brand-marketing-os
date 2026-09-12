import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { EmptyState } from "@/components/layout/EmptyState";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/layout/ui/dialog";
import {
  dispatchPack,
  getAssets,
  setAssetReady,
  type AssetReadinessRow,
  type AssetReadinessState,
  type CampaignDetail,
} from "@/lib/adsApi";

const STATE_LABEL: Record<AssetReadinessState, string> = {
  ready_workbench: "已就位（工作檯）",
  ready_manual: "已就位（手動）",
  in_progress: "製作中",
  not_started: "未開始",
};

const STATE_TONE: Record<AssetReadinessState, "default" | "outline" | "secondary"> = {
  ready_workbench: "default",
  ready_manual: "default",
  in_progress: "secondary",
  not_started: "outline",
};

/** 素材 tab（F03-I15）：一列一支廣告，讀 F03-I08 的就緒狀態，派工到工作檯或手動勾
 * 「素材已就位」。不擋發布（決策 8／10），這裡只是誠實顯示現況。 */
export function AssetsTab({
  brandId,
  campaign: c,
  onCampaignChange,
}: {
  brandId: string;
  campaign: CampaignDetail;
  onCampaignChange: (campaign: CampaignDetail) => void;
}) {
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "ready"; rows: AssetReadinessRow[]; readyCount: number; total: number }
  >({ status: "loading" });
  const [dispatching, setDispatching] = useState(false);
  const [dispatchError, setDispatchError] = useState<string | null>(null);
  const [confirmAd, setConfirmAd] = useState<{ id: string; name: string; next: boolean } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const load = useCallback(() => {
    setState({ status: "loading" });
    getAssets(brandId, c.id)
      .then((data) => setState({ status: "ready", rows: data.assets, readyCount: data.ready_count, total: data.total }))
      .catch((err: unknown) =>
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取素材就緒狀態失敗。" }),
      );
  }, [brandId, c.id]);

  useEffect(load, [load]);

  const ads = c.groups.flatMap((g) => g.ads.map((a) => ({ ad: a, groupName: g.name })));

  if (ads.length === 0) {
    return (
      <EmptyState
        title="這個 Campaign 還沒有素材組"
        description="先在策略頁採用一個策略，系統會自動建立投放組與素材組。"
        actionLabel="前往策略"
        actionHref={`/brands/${brandId}/ads/campaigns/${c.id}?tab=strategy`}
        actionInternal
      />
    );
  }

  if (state.status === "loading") {
    return (
      <div className="surface">
        <div className="surface-body py-10 text-center text-sm text-muted-foreground">讀取中…</div>
      </div>
    );
  }
  if (state.status === "error") {
    return <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  }

  const rowsByAdId = new Map(state.rows.map((r) => [r.ad_id, r]));
  const canDispatch = state.rows.every((r) => r.pack_id === null);
  const packId = state.rows.find((r) => r.pack_id !== null)?.pack_id ?? null;

  async function handleDispatch() {
    setDispatching(true);
    setDispatchError(null);
    try {
      await dispatchPack(brandId, c.id);
      load();
    } catch (err) {
      setDispatchError(err instanceof Error ? err.message : "交棒素材工作檯失敗，請稍後再試。");
    } finally {
      setDispatching(false);
    }
  }

  async function handleConfirmReady() {
    if (!confirmAd) return;
    setConfirmBusy(true);
    try {
      const ad = await setAssetReady(brandId, confirmAd.id, confirmAd.next);
      onCampaignChange({
        ...c,
        groups: c.groups.map((g) => ({ ...g, ads: g.ads.map((a) => (a.id === ad.id ? ad : a)) })),
      });
      setConfirmAd(null);
      load();
    } catch {
      // 錯誤沿用對話框留著讓使用者重試，不額外開一個訊息位置。
    } finally {
      setConfirmBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="surface">
        <div className="surface-header">
          <h2>{state.readyCount}／{state.total} 則已就位</h2>
          {canDispatch ? (
            <Button variant="outline" size="sm" onClick={() => void handleDispatch()} disabled={dispatching}>
              {dispatching ? "交棒中…" : "派工到素材工作檯"}
            </Button>
          ) : (
            packId && (
              <Button variant="outline" size="sm" asChild>
                <Link to={`/brands/${brandId}/workbench/packs/${packId}`}>查看素材任務包</Link>
              </Button>
            )
          )}
        </div>
        <div className="surface-body flex flex-col gap-3">
          {dispatchError && <p className="text-sm text-danger">{dispatchError}</p>}
          <div className="table-surface">
            <table className="w-full text-left text-sm">
              <thead className="bg-muted text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">投放組</th>
                  <th className="px-3 py-2 font-medium">廣告</th>
                  <th className="px-3 py-2 font-medium">狀態</th>
                  <th className="px-3 py-2 font-medium">最後同步</th>
                  <th className="px-3 py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {ads.map(({ ad, groupName }) => {
                  const row = rowsByAdId.get(ad.id);
                  const rowState = row?.state ?? "not_started";
                  return (
                    <tr key={ad.id} className="border-t border-border">
                      <td className="px-3 py-2">{groupName}</td>
                      <td className="px-3 py-2">{ad.name}</td>
                      <td className="px-3 py-2">
                        <Badge variant={STATE_TONE[rowState]}>{STATE_LABEL[rowState]}</Badge>
                        {row?.by && (
                          <span className="ml-2 text-xs text-muted-foreground">
                            {row.by} 於 {row.at}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">{row?.at ?? "－"}</td>
                      <td className="px-3 py-2 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {row?.pack_id && row.brief_id && (
                            <Button variant="ghost" size="sm" asChild>
                              <Link to={`/brands/${brandId}/workbench/packs/${row.pack_id}/sets/${row.brief_id}`}>
                                素材組
                              </Link>
                            </Button>
                          )}
                          {rowState !== "ready_workbench" && (
                            <label className="flex items-center gap-1.5 text-sm">
                              <input
                                type="checkbox"
                                checked={rowState === "ready_manual"}
                                onChange={(e) =>
                                  setConfirmAd({ id: ad.id, name: ad.name, next: e.target.checked })
                                }
                              />
                              素材已就位
                            </label>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <Dialog open={confirmAd !== null} onOpenChange={(open) => !open && setConfirmAd(null)}>
        <DialogContent>
          <DialogTitle>{confirmAd?.next ? "標記素材已就位" : "取消素材已就位"}</DialogTitle>
          <DialogDescription>
            {confirmAd?.next
              ? `確認「${confirmAd?.name}」的素材已經準備好，會記錄是誰、什麼時候勾的。`
              : `取消「${confirmAd?.name}」的素材已就位標記。`}
          </DialogDescription>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirmAd(null)} disabled={confirmBusy}>
              取消
            </Button>
            <Button type="button" onClick={() => void handleConfirmReady()} disabled={confirmBusy}>
              <RefreshCw size={14} className={confirmBusy ? "animate-spin" : "hidden"} />
              確認
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
