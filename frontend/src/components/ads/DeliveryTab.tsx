import { campaignPath } from "@/lib/adsRoutes";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { NativeCreativeView } from "./NativeCreativeView";
import { Plus, Folder, FileText, Layers, Wallet, Calendar } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { EmptyState } from "@/components/layout/EmptyState";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { formatCurrency } from "@/lib/format";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/layout/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/layout/ui/dropdown-menu";
import { fetchCoordinates } from "@/lib/coordinatesApi";
import {
  deleteAd,
  deleteGroup,
  dispatchPack,
  getCampaign,
  type AdRow,
  type CampaignDetail,
  type DeliveryGroupRow,
} from "@/lib/adsApi";
import { fetchChannels } from "@/lib/adsLaunchApi";
import { useApiRead } from "@/lib/useApiRead";
import { ActionBar, Disclosure, KpiStrip, ReadFailed, formatAmount, type KpiCell } from "./patterns";
import { nextStep, NextStepButton, StepButton, type StepTarget } from "./nextStep";
import { ROLE_LABEL, GroupPanel, AdPanel, AddGroupDialog, AddAdDialog, CarriedChip } from "./DeliveryEditors";
import { ManualSettings } from "./ManualSettings";
import { StructureTab } from "./workspace/StructureTab";

const LOCAL_STATE_LABEL: Record<string, string> = {
  unbound: "未綁定",
  bound: "已綁定",
  detached: "已解除",
  retired: "已停用",
};

type SelectedKey = `group:${string}` | `ad:${string}` | `native:${string}`;

/** ISO 日期（`YYYY-MM-DD`）→ `MM/DD`，只給這個分頁的日期 KPI 格用（同 `StrategyTab.tsx::mmdd`，
 * 各自一份短函式，不為此拉共用模組）。 */
function mmdd(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${m}/${d}`;
}

/** v10 (F30-I08) the workspace's 投放結構 tab (prototype `tabStructure()`): the tree card (`StructureTab`: campaign →
 * ad groups → ads with grades and cost per result) and the back bar. Everything the prototype does not show stays on
 * this tab, folded (CLAUDE.md three-layer rule): each plan group's 「進階：編輯這一組」 holds its node editors and
 * its manual launch settings; the campaign-wide 「調整結構（進階）」 (the pre-v10 label, kept: e2e specs open it)
 * holds the in-fold next-step button (`nextStep()` for 新增廣告 and the strategy steps), the old numbers strip, the budget summary, channel status, 新增節點 and — on an imported campaign — the read-only
 * platform entity tree. The material hand-off (`dispatch` → 「開始做素材 →」, never dispatching twice; `make_assets` → 「前往素材 →」)
 * is the bar's primary (F35 ruling 3). A campaign with no groups keeps the old empty state and its next step. */
export function DeliveryTab({
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
  const owner = `${brandId}:${c.id}`;
  const currentOwner = useRef(owner);
  currentOwner.current = owner;
  const readGeneration = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; readGeneration.current += 1; };
  }, [owner]);
  const nativeEntities = c.external_view?.entities ?? [];
  const nativeCampaign = nativeEntities.find((row) => row.native_kind === "campaign");
  const nativeGroups = nativeEntities.filter((row) => row.native_kind === "adset");
  const nativeAds = nativeEntities.filter((row) => row.native_kind === "ad");
  const orderedNative = [
    ...nativeEntities.filter((row) => row.native_kind === "campaign"),
    ...nativeGroups.flatMap((group) => [group, ...nativeAds.filter((ad) => ad.parent_native_id === group.native_id && ad.platform === group.platform && ad.source_account === group.source_account)]),
    ...nativeAds.filter((ad) => !nativeGroups.some((group) => group.native_id === ad.parent_native_id && group.platform === ad.platform && group.source_account === ad.source_account)),
    ...nativeEntities.filter((row) => !["campaign", "adset", "ad"].includes(row.native_kind)),
  ];
  const readonlyReason = c.capabilities?.unavailable.budget ?? "平台結構目前只支援查看，不會修改平台設定。";
  const { scope: draftScope } = useWorkspace();
  const [selected, setSelected] = useState<SelectedKey | null>(null);
  const selectedNative = nativeEntities.find((row) => `native:${row.id}` === selected);
  // Contract K: a failed read is said out loud (ReadFailed + 重試) — never an empty vocabulary or channel list.
  const vocabularyRead = useApiRead(() => fetchCoordinates(brandId), [brandId]);
  // F05-I05：通路清單／連線狀態一律讀 app/ads/channels.py，不再繞去 /api/meta/accounts
  // （§0「不預設」：畫面不准自己判斷哪個通路查得到連線狀態）。
  const channelRead = useApiRead(() => fetchChannels(brandId), [brandId]);
  const vocabulary = vocabularyRead.data ?? [];
  const channelInfo = channelRead.data ?? [];
  const failedReads = [
    vocabularyRead.status === "error" ? "座標選項" : null,
    channelRead.status === "error" ? "通路連線狀態" : null,
  ].filter((x): x is string => x !== null);
  function retryFailedReads() {
    if (vocabularyRead.status === "error") vocabularyRead.reload();
    if (channelRead.status === "error") channelRead.reload();
  }
  const [addGroupOpen, setAddGroupOpen] = useState(false);
  const [addAdOpen, setAddAdOpen] = useState(false);
  const [addAdGroupId, setAddAdGroupId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<
    { kind: "group"; row: DeliveryGroupRow } | { kind: "ad"; row: AdRow } | null
  >(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [dispatchError, setDispatchError] = useState<string | null>(null);
  const [nothingToPrepare, setNothingToPrepare] = useState(false);
  const [editorDirty, setEditorDirty] = useState(false);
  // One manual-settings panel per group fold; each reports its own dirty state.
  const [manualDirty, setManualDirty] = useState<Record<string, boolean>>({});
  const setGroupManualDirty = useCallback((groupId: string, dirty: boolean) => {
    setManualDirty((current) => (Boolean(current[groupId]) === dirty ? current : { ...current, [groupId]: dirty }));
  }, []);
  const manualSettingsDirty = Object.values(manualDirty).some(Boolean);
  const hasUnsavedDraft = editorDirty || manualSettingsDirty;

  useEffect(() => {
    if (!hasUnsavedDraft) return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [hasUnsavedDraft]);

  function confirmDiscard() {
    if (!hasUnsavedDraft) return true;
    const confirmed = window.confirm("還有未儲存的變更，確定要離開嗎？");
    if (confirmed) {
      setEditorDirty(false);
      setManualDirty({});
    }
    return confirmed;
  }

  function requestTabChange(target: StepTarget) {
    if (confirmDiscard()) onChangeTab(target);
  }

  function selectNode(next: SelectedKey) {
    if (selected === next) return;
    if (editorDirty && !window.confirm("目前節點有未儲存的變更，確定要切換嗎？")) return;
    setEditorDirty(false);
    setSelected(next);
  }

  /** F48 Contract M: after a group's budget or dates change the tab re-reads the campaign (one GET) — the period
   * total, the capacity and the strategy's amounts are the server's, never recomputed here. A failed re-read keeps
   * the saved group in place (its numbers refresh on the next read). */
  async function reread(local: CampaignDetail) {
    if (!mounted.current || currentOwner.current !== owner) return;
    const generation = ++readGeneration.current;
    onCampaignChange(local);
    try {
      const fresh = await getCampaign(brandId, c.id);
      if (mounted.current && currentOwner.current === owner && readGeneration.current === generation) {
        onCampaignChange(fresh);
      }
    } catch {
      // The saved row already shows; the totals catch up on the next read.
    }
  }

  function replaceGroup(next: DeliveryGroupRow) {
    void reread({
      ...c,
      groups: c.groups.map((g) => (g.id === next.id ? { ...next, ads: g.ads } : g)),
    });
  }

  function replaceAd(next: AdRow) {
    void reread({
      ...c,
      groups: c.groups.map((g) =>
        g.id === next.group_id ? { ...g, ads: g.ads.map((a) => (a.id === next.id ? next : a)) } : g,
      ),
    });
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      if (deleteTarget.kind === "group") {
        await deleteGroup(brandId, deleteTarget.row.id);
        void reread({ ...c, groups: c.groups.filter((g) => g.id !== deleteTarget.row.id) });
      } else {
        await deleteAd(brandId, deleteTarget.row.id);
        onCampaignChange({
          ...c,
          groups: c.groups.map((g) =>
            g.id === deleteTarget.row.group_id
              ? { ...g, ads: g.ads.filter((a) => a.id !== deleteTarget.row.id) }
              : g,
          ),
        });
      }
      setSelected(null);
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "刪除失敗，請稍後再試。");
    } finally {
      setDeleting(false);
    }
  }

  // §6.2 決議 15：交棒只用 dispatchPack + getCampaign，永遠不交棒第二次。失敗先重讀一次，
  // 發現別處已經交棒（pack_id 已存在）就當作成功繼續走，不比對錯誤文字。
  // F49 Contract T: a pack route that answers `nothing_to_prepare` (pack_id null — every ad carries last period's
  // material) is an outcome, not an error: the bar says so and offers the next step instead of leaving the tab.
  async function handleDispatch() {
    setDispatching(true);
    setDispatchError(null);
    setNothingToPrepare(false);
    try {
      const packId = await dispatchPack(brandId, c.id);
      if (packId === null) {
        setNothingToPrepare(true);
        try { onCampaignChange(await getCampaign(brandId, c.id)); } catch { /* the step below still leads on */ }
        return;
      }
      onCampaignChange(await getCampaign(brandId, c.id));
      onChangeTab("assets");
    } catch (err) {
      try {
        const fresh = await getCampaign(brandId, c.id);
        onCampaignChange(fresh);
        if (fresh.asset_readiness.pack_id) {
          onChangeTab("assets");
        } else {
          setDispatchError(err instanceof Error ? err.message : "交棒素材工作檯失敗，請稍後再試。");
        }
      } catch {
        setDispatchError(err instanceof Error ? err.message : "交棒素材工作檯失敗，請稍後再試。");
      }
    } finally {
      setDispatching(false);
    }
  }

  const step = nextStep(c);
  // F35 ruling 3: the material hand-off is the bar's primary on a planned campaign, not a button in the 進階 fold.
  // 「開始做素材 →」 dispatches the pack once; after that 「前往素材 →」. An imported campaign keeps the plain bar.
  const barStep = !imported && !nothingToPrepare && (step.id === "dispatch" || step.id === "make_assets") ? step.id : null;
  // After `nothing_to_prepare` the bar's primary is the campaign's next step (publish once every ad is ready); a read
  // that still says "dispatch" leads to the 素材 tab, never to a second hand-off.
  const carriedStep: { target: StepTarget; label: string } | null = !nothingToPrepare ? null
    : step.id === "dispatch" ? { target: "assets", label: "前往素材 →" } : { target: step.target, label: step.label };

  if (!imported && c.groups.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <EmptyState title="這個 Campaign 還沒有投放結構" description={step.sentence} />
        <NextStepButton step={step} onChangeTab={requestTabChange} />
      </div>
    );
  }

  const channelKeys = [...new Set(c.groups.map((g) => g.channel_key))];
  const selectedGroup = selected?.startsWith("group:")
    ? c.groups.find((g) => `group:${g.id}` === selected) ?? null
    : null;
  const selectedAd = selected?.startsWith("ad:")
    ? c.groups.flatMap((g) => g.ads).find((a) => `ad:${a.id}` === selected) ?? null
    : null;
  // The tree re-reads when the plan behind it changes (a group or ad added, renamed, removed, re-budgeted).
  const planKey = JSON.stringify([c.groups, c.budget_basis_json?.strategy?.decision?.revision]);

  const adCount = c.groups.reduce((sum, g) => sum + g.ads.length, 0);
  // 同 `PublishPage.tsx` 的判斷：已投放過 or 已經有一筆 campaign 層級的發布動作，兩種都算「綁定過」。
  // F49 Contract L: on a platform = the served lifecycle is past draft (never the stored status).
  const published =
    (c.lifecycle !== undefined && c.lifecycle.state !== "draft") ||
    c.actions.some((a) => a.kind === "publish" && a.target_kind === "campaign");

  function nativeBudget(row: typeof nativeCampaign) {
    if (!row || row.budget_amount === null || !row.currency) return "未知";
    return `${row.currency} ${row.budget_amount.toLocaleString()}${row.budget_type === "daily" ? "／天" : row.budget_type === "lifetime" ? "（總額）" : `（${row.budget_type}）`}`;
  }
  const kpiCells: KpiCell[] = imported ? [
    { icon: Folder, label: "投放組", value: nativeEntities.length ? `${nativeGroups.length} 個` : "尚未讀回", caption: "目前已讀回的平台結構" },
    { icon: FileText, label: "廣告", value: nativeEntities.length ? `${nativeAds.length} 則` : "尚未讀回", caption: "目前已讀回的廣告" },
    { icon: Wallet, label: "活動預算", value: nativeBudget(nativeCampaign), caption: "各層級預算分開呈現，不加總" },
    { icon: Calendar, label: "投放期間", value: `${nativeCampaign?.start_date ?? "開始未知"} – ${nativeCampaign?.end_date ?? "結束未知"}`, caption: "平台讀回日期" },
  ] : [
    {
      icon: Folder,
      label: "投放組",
      value: `${c.groups.length} 個`,
      caption: c.groups.map((g) => ROLE_LABEL[g.role]).join("・"),
    },
    {
      icon: FileText,
      label: "廣告",
      value: `${adCount} 則`,
      caption: "每則廣告要一組文案與圖片",
    },
    {
      icon: Wallet,
      label: "這期總預算",
      value: c.budget_total !== null ? formatCurrency(c.budget_total) : "尚未設定",
      caption: c.budget_total !== null ? "各投放組每日預算 × 投放天數" : "還沒有投放組預算或起訖日",
    },
    {
      icon: Calendar,
      label: "投放期間",
      value: c.start_date && c.end_date ? `${mmdd(c.start_date)} – ${mmdd(c.end_date)}` : "未設定",
      caption: "投放組沒另設日期就跟活動同期間",
    },
  ];

  const placeholder = (
    <div className="surface">
      <div className="surface-body py-10 text-center text-sm text-muted-foreground">
        {imported ? "點左邊的投放組或廣告查看明細。" : "點左邊的投放組或廣告來調整。"}
      </div>
    </div>
  );
  const nodeButton = (key: SelectedKey, indent: string, icon: ReactNode, name: string, badge: ReactNode) => (
    <button key={key} type="button" onClick={() => selectNode(key)}
      className={`flex w-full items-center gap-2 rounded-md py-1.5 ${indent} pr-2 text-left text-sm ${selected === key ? "bg-accent" : "hover:bg-muted"}`}>
      {icon}
      <span className="flex-1 truncate">{name}</span>
      {badge}
    </button>
  );
  const bindBadge = (state: DeliveryGroupRow["local_state"]) => published
    ? <Badge variant={state === "bound" ? "default" : "outline"}>{LOCAL_STATE_LABEL[state]}</Badge> : null;

  // One fold per plan group: its node editors and its manual launch settings.
  const groupFolds = !imported && c.groups.map((g) => {
    const ownsSelection = selectedGroup?.id === g.id || selectedAd?.group_id === g.id;
    const dirty = (editorDirty && ownsSelection) || manualDirty[g.id];
    return (
      <Disclosure key={g.id} label={`進階：編輯這一組（${g.name}）${dirty ? " · 有未儲存變更" : ""}`}>
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-[minmax(220px,0.8fr)_minmax(0,1.4fr)] items-start gap-4">
            <div className="surface">
              <div className="surface-body flex flex-col">
                {nodeButton(`group:${g.id}`, "pl-2", <Folder size={13} className="shrink-0 text-muted-foreground" />, g.name, bindBadge(g.local_state))}
                {g.ads.map((a) => nodeButton(`ad:${a.id}`, "pl-8", <FileText size={12} className="shrink-0 text-muted-foreground" />, a.name,
                  <>{a.carried_label && <CarriedChip ad={a} />}{bindBadge(a.local_state)}</>))}
                <Button variant="outline" size="sm" className="mt-2 w-fit" onClick={() => { setAddAdGroupId(g.id); setAddAdOpen(true); }}>
                  <Plus size={14} /> 在這一組新增廣告
                </Button>
              </div>
            </div>
            {selectedGroup?.id === g.id ? (
              <GroupPanel
                key={`${draftScope}:${brandId}:${c.id}:${selectedGroup.id}`}
                brandId={brandId}
                group={selectedGroup}
                channels={channelInfo}
                campaignStartDate={c.start_date}
                campaignEndDate={c.end_date}
                onSaved={replaceGroup}
                onDelete={() => setDeleteTarget({ kind: "group", row: selectedGroup })}
                isLastGroup={c.groups.length === 1}
                onDirtyChange={setEditorDirty}
                draftKey={`brand-os:ads:group-draft:v1:${draftScope}:${brandId}:${c.id}:${selectedGroup.id}`}
              />
            ) : selectedAd?.group_id === g.id ? (
              <AdPanel
                key={`${draftScope}:${brandId}:${c.id}:${selectedAd.id}`}
                brandId={brandId}
                ad={selectedAd}
                vocabulary={vocabulary}
                menu={c.menu}
                campaignStatus={c.status}
                onSaved={replaceAd}
                onDelete={() => setDeleteTarget({ kind: "ad", row: selectedAd })}
                onDirtyChange={setEditorDirty}
                draftKey={`brand-os:ads:ad-draft:v1:${draftScope}:${brandId}:${c.id}:${selectedAd.id}`}
              />
            ) : placeholder}
          </div>
          <ManualSettings key={`${draftScope}:${brandId}:${c.id}:${g.id}`} draftScope={draftScope} brandId={brandId} campaign={c}
            groupId={g.id} onSaved={onCampaignChange} onDirtyChange={(dirty) => setGroupManualDirty(g.id, dirty)} />
        </div>
      </Disclosure>
    );
  });

  return (
    <div className="flex flex-col gap-4">
      <StructureTab brandId={brandId} campaign={c} planKey={planKey} />
      {c.capacity && (
        // F48 Contract C: what this period's daily budget carries, as served (`plan.served`).
        <p data-slot="plan-capacity" className="-mt-2 px-1 text-[13px] text-muted-foreground">
          每天 {formatAmount(c.capacity.daily)}，撐得起 {c.capacity.can_support} 則，另加一則探索（這期最多 {c.capacity.ceiling} 則
          {c.capacity.carried != null && c.capacity.carried > 0 && `，其中 ${c.capacity.carried} 則沿用上一期`}）
        </p>
      )}

      {failedReads.length > 0 && (
        <ReadFailed what={`${failedReads.join("、")}讀取失敗，下方的結構編輯可能缺少選項。`} onRetry={retryFailedReads} />
      )}

      {groupFolds}

      <Disclosure label="調整結構（進階）">
        <div className="flex flex-col gap-4">
          {!barStep && (
            <div className="flex flex-col gap-1.5">
              {step.id === "add_ad" ? (
                <StepButton onClick={() => setAddAdOpen(true)}>新增廣告 →</StepButton>
              ) : (
                <NextStepButton step={step} onChangeTab={requestTabChange} />
              )}
            </div>
          )}

          {imported && (
            <p className="text-sm text-muted-foreground">
              {nativeEntities.length ? `平台投放結構已載入 ${nativeEntities.length} 筆` : "尚未讀回平台投放結構"}。{readonlyReason}
            </p>
          )}
          <KpiStrip cells={kpiCells} />

          {!imported && <div className="surface">
            <div className="surface-header">
              <h2>預算（這個 Campaign）</h2>
            </div>
            <div className="surface-body">
              <div className="text-xs text-muted-foreground">這期總預算</div>
              <p className="metric-number">{c.budget_total !== null ? formatCurrency(c.budget_total) : "尚未設定"}</p>
              <div className="text-xs text-muted-foreground">
                {c.budget_total !== null
                  ? `各投放組每日預算 × 投放天數（${c.start_date} ~ ${c.end_date}）`
                  : "還沒有投放組預算或起訖日，算不出總預算"}
              </div>
            </div>
          </div>}

          <div className="grid grid-cols-[minmax(260px,0.9fr)_minmax(0,1.4fr)] items-start gap-4">
            <div className="surface">
              <div className="surface-header">
                <h2>投放結構</h2>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" aria-label="新增節點" disabledReason={imported ? readonlyReason : undefined}>
                      <Plus size={16} />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => setAddGroupOpen(true)}>新增投放組</DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={c.groups.length === 0}
                      onSelect={() => setAddAdOpen(true)}
                    >
                      新增廣告{c.groups.length === 0 && <span className="text-xs">（先新增一個廣告組）</span>}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              <div className="surface-body flex flex-col">
                <div className="flex items-center gap-2 py-2 text-sm font-semibold">
                  <Layers size={14} /> {c.name}
                </div>
                {channelKeys.map((key) => {
                  const info = channelInfo.find((c2) => c2.key === key);
                  return (
                    <div key={key} className="flex items-center gap-2 py-1.5 pl-4 text-sm text-muted-foreground">
                      <span>{info?.label ?? key}</span>
                      {info && (
                        <Badge variant={info.connected ? "default" : "outline"}>{info.state_text}</Badge>
                      )}
                    </div>
                  );
                })}
                {imported && orderedNative.map((entity) => nodeButton(
                  `native:${entity.id}`,
                  entity.native_kind === "ad" ? "pl-12" : entity.native_kind === "adset" ? "pl-6" : "pl-2",
                  entity.native_kind === "ad" ? <FileText size={12} /> : <Folder size={13} />,
                  entity.name ?? entity.native_id,
                  <Badge variant="outline">{entity.delivery_label ?? "平台狀態不明"}</Badge>,
                ))}
                {!imported && c.groups.map((g) => (
                  <div key={g.id} className="flex items-center gap-2 py-1.5 pl-6 text-sm">
                    <Folder size={13} className="shrink-0 text-muted-foreground" />
                    <span className="flex-1 truncate">{g.name}</span>
                    <span className="text-xs text-muted-foreground">{g.ads.length} 則</span>
                  </div>
                ))}
              </div>
            </div>

            {selectedNative ? (
              <div className="surface">
                <div className="surface-header"><h2>{selectedNative.name ?? selectedNative.native_id}</h2></div>
                <div className="surface-body flex flex-col gap-3 text-sm">
                  <p>平台 ID：{selectedNative.native_id}</p>
                  <p>上層 ID：{selectedNative.parent_native_id ?? "無"}</p>
                  <p>狀態：{selectedNative.delivery_label ?? "平台狀態不明"}</p>
                  <p>預算：{nativeBudget(selectedNative)}</p>
                  {Object.keys(selectedNative.budget_raw ?? {}).length > 0 && <p>平台原始預算（未換算）：{JSON.stringify(selectedNative.budget_raw)}</p>}
                  <p>期間：{selectedNative.start_date ?? "開始未知"} – {selectedNative.end_date ?? "結束未知"}</p>
                  {selectedNative.sync_error && <p role="alert" className="text-danger">同步狀態：{selectedNative.sync_error}</p>}
                  <p>最近成功：{selectedNative.last_success_at ?? "尚無成功紀錄"}</p>
                  <NativeCreativeView creative={selectedNative.creative} />
                  <p className="text-muted-foreground">{readonlyReason}</p>
                  <Button disabledReason={readonlyReason}>儲存</Button>
                </div>
              </div>
            ) : imported ? placeholder : (
              <div className="surface">
                <div className="surface-body py-10 text-center text-sm text-muted-foreground">
                  每一組的設定在上面的「進階：編輯這一組」裡調整。
                </div>
              </div>
            )}
          </div>
        </div>
      </Disclosure>

      <ActionBar back={{ label: "總覽", to: campaignPath(brandId, c.id) }}
        hint={barStep === "dispatch" ? "交棒後工作檯替每則廣告寫文案和圖片提示詞；圖仍由你上傳" : barStep === "make_assets" ? "工作檯做好的文案會出現在素材頁的格子裡" : undefined}>
        {barStep === "dispatch" && (
          <>
            {dispatchError && <p role="alert" className="text-sm text-danger">{dispatchError}</p>}
            <Button onClick={() => { if (confirmDiscard()) void handleDispatch(); }} busy={dispatching}>
              {dispatching ? "交棒中…" : "開始做素材 →"}
            </Button>
          </>
        )}
        {barStep === "make_assets" && <Button onClick={() => requestTabChange("assets")}>前往素材 →</Button>}
        {carriedStep && (
          <>
            <p role="status" className="text-sm">這期的素材都沿用上一期，不用準備</p>
            <Button onClick={() => requestTabChange(carriedStep.target)}>{carriedStep.label}</Button>
          </>
        )}
      </ActionBar>

      {addGroupOpen && (
        <AddGroupDialog
          brandId={brandId}
          campaignId={c.id}
          onClose={() => setAddGroupOpen(false)}
          onCreated={(group) => {
            void reread({ ...c, groups: [...c.groups, { ...group, ads: [] }] });
            setSelected(`group:${group.id}`);
            setAddGroupOpen(false);
          }}
        />
      )}
      {addAdOpen && (
        <AddAdDialog
          brandId={brandId}
          campaignId={c.id}
          groups={c.groups}
          defaultGroupId={addAdGroupId ?? selectedGroup?.id ?? selectedAd?.group_id ?? c.groups[0].id}
          vocabulary={vocabulary}
          menu={c.menu}
          onClose={() => { setAddAdOpen(false); setAddAdGroupId(null); }}
          onCreated={(ad) => {
            onCampaignChange({
              ...c,
              groups: c.groups.map((g) => (g.id === ad.group_id ? { ...g, ads: [...g.ads, ad] } : g)),
            });
            setSelected(`ad:${ad.id}`);
            setAddAdOpen(false);
            setAddAdGroupId(null);
          }}
        />
      )}

      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogTitle>{deleteTarget?.kind === "group" ? "刪除投放組" : "刪除廣告"}</DialogTitle>
          <DialogDescription>
            {deleteTarget?.kind === "group"
              ? `刪除「${deleteTarget.row.name}」會一併刪除底下所有廣告，這個動作無法復原。`
              : `刪除「${deleteTarget?.row.name}」無法復原。`}
          </DialogDescription>
          {deleteError && <p className="text-sm text-danger">{deleteError}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)} busy={deleting}>
              取消
            </Button>
            <Button type="button" variant="destructive" onClick={() => void handleDelete()} busy={deleting}>
              {deleting ? "刪除中…" : "確認刪除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
