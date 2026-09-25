import { NativeCreativeView } from "./NativeCreativeView";
import { UserAssetPlacements } from "./UserAssetPlacements";
import { ManualHandoffPanel } from "./ManualHandoffPanel";
import { MaterialTasksPanel } from "./MaterialTasksPanel";
import { PlannedMaterialAssignments } from "./PlannedMaterialAssignments";
import { Disclosure, ReadFailed } from "./patterns";
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
  getAssets,
  getCampaign,
  setAssetReady,
  type AssetReadinessRow,
  type AssetReadinessState,
  type CampaignDetail,
} from "@/lib/adsApi";
import { nextStep, NextStepButton, StepButton, type StepTarget } from "./nextStep";
import { AssetsBody } from "./workspace/AssetsBody";

/** The workbench／manual progress of a planned ad — a progress note only. Whether the ad can go out is
 * `material_ready` (Done #7: `ready_count` counts confirmed material only), so no note says 已就位. */
const PROGRESS_NOTE: Record<AssetReadinessState, string> = {
  ready_workbench: "工作檯已完成",
  ready_manual: "已手動標記",
  in_progress: "製作中",
  not_started: "未開始",
};

/** `GET …/assets` rows carry `material_ready` (the launch rule); the shared row type does not declare it. */
type ReadinessRow = AssetReadinessRow & { material_ready?: boolean };

/** 素材 tab（F03-I15）：一列一支廣告，讀 F03-I08 的就緒狀態，派工到工作檯或手動勾
 * 「素材已就位」。不擋發布（決策 8／10），這裡只是誠實顯示現況。 */
function LegacyAssetsTab({
  brandId,
  campaign: c,
  onCampaignChange,
  onChangeTab,
}: {
  brandId: string;
  campaign: CampaignDetail;
  onCampaignChange: (campaign: CampaignDetail) => void;
  onChangeTab: (target: StepTarget) => void;
}) {
  const imported = c.origin === "imported";
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "ready"; rows: ReadinessRow[]; readyCount: number; total: number }
  >({ status: "loading" });
  const [confirmAd, setConfirmAd] = useState<{ id: string; name: string; next: boolean } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const load = useCallback(() => {
    if (imported) { setState({ status: "ready", rows: [], readyCount: 0, total: 0 }); return; }
    setState({ status: "loading" });
    getAssets(brandId, c.id)
      .then((data) => setState({ status: "ready", rows: data.assets, readyCount: data.ready_count, total: data.total }))
      .catch((err: unknown) =>
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取素材就緒狀態失敗。" }),
      );
  }, [brandId, c.id, imported]);

  useEffect(load, [load]);

  const entities = c.external_view?.entities ?? [];
  const ads = imported
    ? entities.filter(e => e.native_kind === "ad").map(native => ({
        ad: { id: native.id, name: native.name ?? native.native_id },
        groupName: entities.find(e => e.platform === native.platform && e.source_account === native.source_account && e.native_id === native.parent_native_id)?.name ?? "投放組名稱未知",
        native,
      }))
    : c.groups.flatMap(g => g.ads.map(ad => ({ ad, groupName: g.name, native: undefined })));
  const step = nextStep(c);

  if (ads.length === 0) {
    return (
      <EmptyState
        title={imported ? "尚未讀回廣告素材" : "這個 Campaign 還沒有廣告"}
        description={imported ? "可在上方加入自帶素材，完成內部確認與手動交接；平台素材未讀回不代表不存在。" : `自帶素材可在上方完成確認與手動交接。如需系統產生廣告素材：${step.sentence}`}
        actionLabel={imported ? "查看投放結構" : step.label}
        onAction={() => onChangeTab(imported ? "structure" : step.target)}
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
    return <ReadFailed what={`舊版素材就位清單讀不到：${state.message}`} onRetry={load} />;
  }

  const rowsByAdId = new Map(state.rows.map((r) => [r.ad_id, r]));
  const packId = imported ? null : c.asset_readiness.pack_id ?? null;

  async function handleConfirmReady() {
    if (!confirmAd) return;
    setConfirmBusy(true);
    try {
      await setAssetReady(brandId, confirmAd.id, confirmAd.next);
      onCampaignChange(await getCampaign(brandId, c.id));
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
          <h2>{imported ? `${ads.length} 則平台廣告` : `${state.readyCount}／${state.total} 則素材已備妥`}</h2>
          {packId && (
            <Button variant="outline" size="sm" asChild>
              <Link to={`/brands/${brandId}/workbench/packs/${packId}`}>查看素材任務包</Link>
            </Button>
          )}
        </div>
        <div className="surface-body flex flex-col gap-3">
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
                {ads.map(({ ad, groupName, native }) => {
                  const row = rowsByAdId.get(ad.id);
                  const rowState = row?.state ?? "not_started";
                  return (
                    <tr key={ad.id} className="border-t border-border">
                      <td className="px-3 py-2">{groupName}</td>
                      <td className="px-3 py-2">{ad.name}</td>
                      <td className="px-3 py-2">
                        {native
                          ? <Badge variant="secondary">{native.native_status ?? "平台狀態未知"}</Badge>
                          : <Badge variant={row?.material_ready ? "default" : "outline"}>{row?.material_ready ? "素材已備妥" : "還不能上架"}</Badge>}
                        {!native && <span className="ml-2 text-xs text-muted-foreground">{PROGRESS_NOTE[rowState]}</span>}
                        {native?.sync_error && <p className="text-xs text-warning">{native.sync_error}</p>}
                        {row?.by && (
                          <span className="ml-2 text-xs text-muted-foreground">
                            {row.by} 於 {row.at}
                          </span>
                        )}
                        {packId && !row?.brief_id && rowState !== "ready_manual" && rowState !== "ready_workbench" && (
                          <p className="mt-1 text-xs text-muted-foreground">
                            交棒之後才新增的，不在素材任務包裡；做好後勾「素材已就位」。
                          </p>
                        )}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">{native ? (native.last_success_at ?? "尚未成功讀回") : (row?.at ?? "－")}</td>
                      <td className="px-3 py-2 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {native && <details className="max-w-lg text-left"><summary className="cursor-pointer text-primary">查看素材</summary><NativeCreativeView creative={native.creative} /></details>}
                          {row?.pack_id && row.brief_id && (
                            <Button variant="ghost" size="sm" asChild>
                              <Link to={`/brands/${brandId}/workbench/packs/${row.pack_id}/sets/${row.brief_id}`}>
                                素材組
                              </Link>
                            </Button>
                          )}
                          {!imported && rowState !== "ready_workbench" && (
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

      {imported ? <StepButton onClick={() => onChangeTab("performance")}>查看成效 →</StepButton> : step.id === "make_assets" ? (
        <StepButton asChild>
          <Link to={`/brands/${brandId}/workbench/packs/${c.asset_readiness.pack_id}`}>前往素材工作檯 →</Link>
        </StepButton>
      ) : (
        <NextStepButton step={step} onChangeTab={onChangeTab} />
      )}

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

/** Deep links that land inside the folded panels: a material request (`?material=`, `?material_new=1`), a review
 * hand-off (`?review=`, `?recommendation=`) and the placement list (`#material-placements`). */
const FOLD_PARAMS = ["material", "material_new", "review", "recommendation"];
const PLACEMENTS_HASH = "#material-placements";

/** v10 (F30-I11) 素材 tab: the new body (`workspace/AssetsBody`: 素材需求, slots, the draft bar) over the old panels,
 * folded under 「進階」 — the material requests editor, 自帶素材安排 and manual hand-off, and the old readiness list.
 * Nothing is deleted; every deep link above opens the fold (and the placement list for its hash) on arrival. */
export function AssetsTab(props: Parameters<typeof LegacyAssetsTab>[0]) {
  const [params] = useSearchParams();
  const linked = FOLD_PARAMS.some((key) => params.has(key));
  const [materialRefresh, setMaterialRefresh] = useState(0);
  const [placementRefresh, setPlacementRefresh] = useState(0);
  // A file put into a slot is a new placement: the placement list re-reads (a remount), the slots already have it.
  const [slotUploads, setSlotUploads] = useState(0);
  // A request cancelled from the 素材需求 card: the folded request list re-reads (its own saves update it in place).
  const [requestsRefresh, setRequestsRefresh] = useState(0);
  const [placementsOpen, setPlacementsOpen] = useState(() => window.location.hash === PLACEMENTS_HASH);
  const [advancedOpen, setAdvancedOpen] = useState(() => linked || window.location.hash === PLACEMENTS_HASH);
  const [scrollTick, setScrollTick] = useState(() => (window.location.hash === PLACEMENTS_HASH ? 1 : 0));
  const openPlacements = useCallback(() => { setAdvancedOpen(true); setPlacementsOpen(true); setScrollTick((n) => n + 1); }, []);
  // A deep link that arrives while the tab is open (e.g. 「新增素材需求」 from another screen) opens the fold once.
  useEffect(() => { if (linked) setAdvancedOpen(true); }, [linked]);
  useEffect(() => {
    const open = () => { if (window.location.hash === PLACEMENTS_HASH) openPlacements(); };
    window.addEventListener("hashchange", open);
    return () => window.removeEventListener("hashchange", open);
  }, [openPlacements]);
  // Scroll once per request, after the fold has rendered its content.
  useEffect(() => { if (scrollTick > 0) document.getElementById("material-placements")?.scrollIntoView?.({ block: "start" }); }, [scrollTick]);

  const imported = props.campaign.origin === "imported";
  const advanced = (
    <Disclosure label="進階：素材需求、自帶素材與人工交接" open={advancedOpen} onOpenChange={setAdvancedOpen}>
      <div className="flex flex-col gap-4">
        <MaterialTasksPanel brandId={props.brandId} campaignId={props.campaign.id} refreshKey={requestsRefresh}
          onSaved={() => setMaterialRefresh((value) => value + 1)} />
        <div id="material-placements"><Disclosure label="素材安排與人工交接" open={placementsOpen} onOpenChange={setPlacementsOpen}>
          <UserAssetPlacements key={`${props.brandId}:${props.campaign.id}:${materialRefresh}:${slotUploads}`} brandId={props.brandId} campaign={props.campaign} onChanged={() => setPlacementRefresh((value) => value + 1)} />
          {!imported && <PlannedMaterialAssignments brandId={props.brandId} campaignId={props.campaign.id} refreshKey={materialRefresh + placementRefresh} />}
          <ManualHandoffPanel brandId={props.brandId} campaignId={props.campaign.id} mode="new-ad" refreshKey={materialRefresh + placementRefresh} />
        </Disclosure></div>
        <Disclosure label="原有任務包與平台素材"><LegacyAssetsTab {...props} /></Disclosure>
      </div>
    </Disclosure>
  );
  return (
    <AssetsBody brandId={props.brandId} campaign={props.campaign} refreshKey={materialRefresh + placementRefresh + requestsRefresh}
      advanced={advanced}
      onPlacementChanged={() => setSlotUploads((value) => value + 1)}
      onRequestsChanged={() => setRequestsRefresh((value) => value + 1)}
      onOpenPlacements={openPlacements} />
  );
}
