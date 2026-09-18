import { ExternalCampaignPanel } from "./ExternalCampaignPanel";
import { useEffect, useState } from "react";
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
import { fetchCoordinates, type Coordinate } from "@/lib/coordinatesApi";
import {
  currentBudgetTotal,
  deleteAd,
  deleteGroup,
  dispatchPack,
  getCampaign,
  type AdRow,
  type CampaignDetail,
  type DeliveryGroupRow,
} from "@/lib/adsApi";
import { fetchChannels, type Channel } from "@/lib/adsLaunchApi";
import { Disclosure, JudgmentBand, KpiStrip, type KpiCell } from "./patterns";
import { nextStep, NextStepButton, StepButton, type StepTarget } from "./nextStep";
import { ROLE_LABEL, GroupPanel, AdPanel, AddGroupDialog, AddAdDialog } from "./DeliveryEditors";

import { ManualSettings } from "./ManualSettings";

const LOCAL_STATE_LABEL: Record<string, string> = {
  unbound: "未綁定",
  bound: "已綁定",
  detached: "已解除",
  retired: "已停用",
};

type SelectedKey = `group:${string}` | `ad:${string}`;

/** ISO 日期（`YYYY-MM-DD`）→ `MM/DD`，只給這個分頁的日期 KPI 格用（同 `StrategyTab.tsx::mmdd`，
 * 各自一份短函式，不為此拉共用模組）。 */
function mmdd(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${m}/${d}`;
}

/** 投放結構 tab（F06-I02）：長得跟策略頁一樣——判斷帶＋數字條＋整寬主要按鈕，樹與編輯面板
 * 收進「調整結構（進階）」（ARCHITECTURE.md §6.2 決議 16）。主要按鈕讀 `nextStep()`：沒有廣告
 * 給「新增廣告」，有廣告還沒交棒給「開始做素材」，其餘照規則走（永遠不交棒第二次）。 */
function LegacyDeliveryTab({
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
  const { scope: draftScope } = useWorkspace();
  const [selected, setSelected] = useState<SelectedKey | null>(null);
  const [vocabulary, setVocabulary] = useState<Coordinate[]>([]);
  const [channelInfo, setChannelInfo] = useState<Channel[]>([]);
  const [addGroupOpen, setAddGroupOpen] = useState(false);
  const [addAdOpen, setAddAdOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<
    { kind: "group"; row: DeliveryGroupRow } | { kind: "ad"; row: AdRow } | null
  >(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [dispatchError, setDispatchError] = useState<string | null>(null);
  const [editorDirty, setEditorDirty] = useState(false);
  const [manualSettingsDirty, setManualSettingsDirty] = useState(false);
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
      setManualSettingsDirty(false);
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

  useEffect(() => {
    fetchCoordinates(brandId).then(setVocabulary).catch(() => setVocabulary([]));
    // F05-I05：通路清單／連線狀態一律讀 app/ads/channels.py，不再繞去 /api/meta/accounts
    // （§0「不預設」：畫面不准自己判斷哪個通路查得到連線狀態）。
    fetchChannels(brandId)
      .then(setChannelInfo)
      .catch(() => setChannelInfo([]));
  }, [brandId]);

  function replaceGroup(next: DeliveryGroupRow) {
    onCampaignChange({
      ...c,
      groups: c.groups.map((g) => (g.id === next.id ? { ...next, ads: g.ads } : g)),
    });
  }

  function replaceAd(next: AdRow) {
    onCampaignChange({
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
        onCampaignChange({ ...c, groups: c.groups.filter((g) => g.id !== deleteTarget.row.id) });
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
  async function handleDispatch() {
    setDispatching(true);
    setDispatchError(null);
    try {
      await dispatchPack(brandId, c.id);
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

  if (c.groups.length === 0) {
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

  const t = currentBudgetTotal(c);
  const diff = t.total !== null && c.budget_planned !== null ? t.total - c.budget_planned : null;
  const adCount = c.groups.reduce((sum, g) => sum + g.ads.length, 0);
  // 同 `PublishPage.tsx` 的判斷：已投放過 or 已經有一筆 campaign 層級的發布動作，兩種都算「綁定過」。
  const published =
    ["live", "ended", "closed"].includes(c.status) ||
    c.actions.some((a) => a.kind === "publish" && a.target_kind === "campaign");

  const kpiCells: KpiCell[] = [
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
      label: "每日合計",
      value: formatCurrency(t.dailySum),
      caption: t.total !== null ? `共 ${t.days} 天，總計 ${formatCurrency(t.total)}` : "還沒設定投放起訖日",
    },
    {
      icon: Calendar,
      label: "投放期間",
      value: c.start_date && c.end_date ? `${mmdd(c.start_date)} – ${mmdd(c.end_date)}` : "未設定",
      caption: "投放組沒另設日期就跟活動同期間",
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <JudgmentBand
        icon={Layers}
        sentence="系統已經照策略建好投放結構"
        facts="不用改也可以；想微調再打開下面的「調整結構（進階）」。"
      />

      <div className="surface">
        <div className="surface-body">
          <KpiStrip cells={kpiCells} />
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        {step.id === "add_ad" ? (
          <StepButton onClick={() => setAddAdOpen(true)}>新增廣告 →</StepButton>
        ) : step.id === "dispatch" ? (
          <StepButton onClick={() => { if (confirmDiscard()) void handleDispatch(); }} disabled={dispatching}>
            {dispatching ? "交棒中…" : "開始做素材 →"}
          </StepButton>
        ) : (
          <NextStepButton step={step} onChangeTab={requestTabChange} />
        )}
        {dispatchError && <p className="text-sm text-danger">{dispatchError}</p>}
      </div>

      <ManualSettings key={`${draftScope}:${brandId}:${c.id}`} draftScope={draftScope} brandId={brandId} campaign={c}
        onSaved={onCampaignChange} onDirtyChange={setManualSettingsDirty} />

      <Disclosure label={`調整結構（進階）${editorDirty ? " · 有未儲存變更" : ""}`}>
        <div className="flex flex-col gap-4">
          <div className="surface">
            <div className="surface-header">
              <h2>預算（這個 Campaign）</h2>
            </div>
            <div className="surface-body grid grid-cols-3 gap-4">
              <div>
                <div className="text-xs text-muted-foreground">目前投放組合計</div>
                <p className="metric-number">{t.total !== null ? formatCurrency(t.total) : "尚未設定"}</p>
                <div className="text-xs text-muted-foreground">
                  {t.total !== null
                    ? `各投放組日預算 ${formatCurrency(t.dailySum)}／天 × ${t.days} 天（${c.start_date} ~ ${c.end_date}）`
                    : "還沒設定投放起訖日，算不出總預算"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">採用時的計畫</div>
                <p className="metric-number">
                  {c.budget_planned !== null ? formatCurrency(c.budget_planned) : "尚未設定"}
                </p>
                <div className="text-xs text-muted-foreground">
                  {c.budget_planned !== null
                    ? `採用策略時的情境金額${c.budget_scenario ? `（${c.budget_scenario}）` : ""}，不會跟著日預算改`
                    : "還沒採用預算情境"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">差額</div>
                <p className="metric-number">
                  {diff === null
                    ? "算不出來"
                    : diff === 0
                      ? "持平"
                      : diff > 0
                        ? `＋${formatCurrency(diff)}`
                        : `－${formatCurrency(Math.abs(diff))}`}
                </p>
                <div className="text-xs text-muted-foreground">
                  {diff !== null ? "目前投放組合計 − 採用時的計畫" : "兩邊都有金額才算得出差額"}
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-[minmax(260px,0.9fr)_minmax(0,1.4fr)] items-start gap-4">
            <div className="surface">
              <div className="surface-header">
                <h2>投放結構</h2>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" aria-label="新增節點">
                      <Plus size={16} />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => setAddGroupOpen(true)}>新增投放組</DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={c.groups.length === 0}
                      onSelect={() => setAddAdOpen(true)}
                    >
                      新增廣告
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
                {c.groups.map((g) => (
                  <div key={g.id}>
                    <button
                      type="button"
                      onClick={() => selectNode(`group:${g.id}`)}
                      className={`flex w-full items-center gap-2 rounded-md py-1.5 pl-6 pr-2 text-left text-sm ${
                        selected === `group:${g.id}` ? "bg-accent" : "hover:bg-muted"
                      }`}
                    >
                      <Folder size={13} className="shrink-0 text-muted-foreground" />
                      <span className="flex-1 truncate">{g.name}</span>
                      {published && (
                        <Badge variant={g.local_state === "bound" ? "default" : "outline"}>
                          {LOCAL_STATE_LABEL[g.local_state]}
                        </Badge>
                      )}
                    </button>
                    {g.ads.map((a) => (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() => selectNode(`ad:${a.id}`)}
                        className={`flex w-full items-center gap-2 rounded-md py-1.5 pl-12 pr-2 text-left text-sm ${
                          selected === `ad:${a.id}` ? "bg-accent" : "hover:bg-muted"
                        }`}
                      >
                        <FileText size={12} className="shrink-0 text-muted-foreground" />
                        <span className="flex-1 truncate">{a.name}</span>
                        {published && (
                          <Badge variant={a.local_state === "bound" ? "default" : "outline"}>
                            {LOCAL_STATE_LABEL[a.local_state]}
                          </Badge>
                        )}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            </div>

            {selectedGroup ? (
              <GroupPanel
                key={`${draftScope}:${brandId}:${c.id}:${selectedGroup.id}`}
                brandId={brandId}
                group={selectedGroup}
                channels={channelInfo}
                campaignStartDate={c.start_date}
                campaignEndDate={c.end_date}
                onSaved={replaceGroup}
                onDelete={() => setDeleteTarget({ kind: "group", row: selectedGroup })}
                onDirtyChange={setEditorDirty}
                draftKey={`brand-os:ads:group-draft:v1:${draftScope}:${brandId}:${c.id}:${selectedGroup.id}`}
              />
            ) : selectedAd ? (
              <AdPanel
                key={`${draftScope}:${brandId}:${c.id}:${selectedAd.id}`}
                brandId={brandId}
                ad={selectedAd}
                vocabulary={vocabulary}
                campaignStatus={c.status}
                onSaved={replaceAd}
                onDelete={() => setDeleteTarget({ kind: "ad", row: selectedAd })}
                onDirtyChange={setEditorDirty}
                draftKey={`brand-os:ads:ad-draft:v1:${draftScope}:${brandId}:${c.id}:${selectedAd.id}`}
              />
            ) : (
              <div className="surface">
                <div className="surface-body py-10 text-center text-sm text-muted-foreground">
                  點左邊的投放組或廣告來調整。
                </div>
              </div>
            )}
          </div>
        </div>
      </Disclosure>

      {addGroupOpen && (
        <AddGroupDialog
          brandId={brandId}
          campaignId={c.id}
          onClose={() => setAddGroupOpen(false)}
          onCreated={(group) => {
            onCampaignChange({ ...c, groups: [...c.groups, { ...group, ads: [] }] });
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
          defaultGroupId={selectedGroup?.id ?? c.groups[0].id}
          vocabulary={vocabulary}
          onClose={() => setAddAdOpen(false)}
          onCreated={(ad) => {
            onCampaignChange({
              ...c,
              groups: c.groups.map((g) => (g.id === ad.group_id ? { ...g, ads: [...g.ads, ad] } : g)),
            });
            setSelected(`ad:${ad.id}`);
            setAddAdOpen(false);
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
            <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              取消
            </Button>
            <Button type="button" variant="destructive" onClick={() => void handleDelete()} disabled={deleting}>
              {deleting ? "刪除中…" : "確認刪除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function DeliveryTab(props: Parameters<typeof LegacyDeliveryTab>[0]) {
  return props.campaign.origin === "imported" ? <ExternalCampaignPanel {...props} /> : <LegacyDeliveryTab {...props} />;
}
