import { useEffect, useState } from "react";
import { Plus, Folder, FileText, Layers, Wallet, Calendar } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { Input } from "@/components/layout/ui/input";
import { EmptyState } from "@/components/layout/EmptyState";
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
import { COORDINATE_DIMENSIONS, fetchCoordinates, type Coordinate, type CoordinateDimension } from "@/lib/coordinatesApi";
import {
  adoptStrategy,
  createAd,
  createGroup,
  currentBudgetTotal,
  deleteAd,
  deleteGroup,
  dispatchPack,
  getCampaign,
  patchAd,
  patchGroup,
  type AdCoordinates,
  type AdRow,
  type CampaignDetail,
  type CampaignStatus,
  type CreateAdInput,
  type DeliveryGroupRow,
  type StrategyRole,
} from "@/lib/adsApi";
import { fetchChannels, type Channel } from "@/lib/adsLaunchApi";
import { Disclosure, JudgmentBand, KpiStrip, type KpiCell } from "./patterns";
import { nextStep, NextStepButton, StepButton, type StepTarget } from "./nextStep";

const ROLE_LABEL: Record<StrategyRole, string> = { new: "新客", retarget: "再行銷", explore: "探索" };
const LOCAL_STATE_LABEL: Record<string, string> = {
  unbound: "未綁定",
  bound: "已綁定",
  detached: "已解除",
  retired: "已停用",
};

type SelectedKey = `group:${string}` | `ad:${string}`;

function selectClassName() {
  return "h-9 rounded-md border border-input bg-transparent px-3 text-sm";
}

/** ISO 日期（`YYYY-MM-DD`）→ `MM/DD`，只給這個分頁的日期 KPI 格用（同 `StrategyTab.tsx::mmdd`，
 * 各自一份短函式，不為此拉共用模組）。 */
function mmdd(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${m}/${d}`;
}

/** 投放結構 tab（F06-I02）：長得跟策略頁一樣——判斷帶＋數字條＋整寬主要按鈕，樹與編輯面板
 * 收進「調整結構（進階）」（ARCHITECTURE.md §6.2 決議 16）。主要按鈕讀 `nextStep()`：沒有廣告
 * 給「新增廣告」，有廣告還沒交棒給「開始做素材」，其餘照規則走（永遠不交棒第二次）。 */
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
  const [adopting, setAdopting] = useState(false);
  const [adoptError, setAdoptError] = useState<string | null>(null);
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

  useEffect(() => {
    fetchCoordinates(brandId).then(setVocabulary).catch(() => setVocabulary([]));
    // F05-I05：通路清單／連線狀態一律讀 app/ads/channels.py，不再繞去 /api/meta/accounts
    // （§0「不預設」：畫面不准自己判斷哪個通路查得到連線狀態）。
    fetchChannels(brandId)
      .then(setChannelInfo)
      .catch(() => setChannelInfo([]));
  }, [brandId]);

  async function handleAdopt() {
    setAdopting(true);
    setAdoptError(null);
    try {
      onCampaignChange(await adoptStrategy(brandId, c.id));
    } catch (err) {
      setAdoptError(err instanceof Error ? err.message : "建立投放結構失敗，請稍後再試。");
    } finally {
      setAdopting(false);
    }
  }

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

  if (c.groups.length === 0) {
    if (!c.budget_basis_json.strategy) {
      return (
        <EmptyState
          title="這個 Campaign 還沒有投放結構"
          description="先在策略頁採用一個策略，系統會自動建立投放組與廣告。"
          actionLabel="前往策略"
          actionHref={`/brands/${brandId}/ads/campaigns/${c.id}?tab=strategy`}
          actionInternal
        />
      );
    }
    return (
      <EmptyState
        title="這個 Campaign 還沒有投放結構"
        description={adoptError ?? "已經有策略了，採用後會自動建立投放組與廣告。"}
        actionLabel={adopting ? "建立中…" : "採用策略（建立投放結構）"}
        onAction={handleAdopt}
        actionDisabled={adopting}
      />
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
  const step = nextStep(c);
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
          <StepButton onClick={() => void handleDispatch()} disabled={dispatching}>
            {dispatching ? "交棒中…" : "開始做素材 →"}
          </StepButton>
        ) : (
          <NextStepButton step={step} onChangeTab={onChangeTab} />
        )}
        {dispatchError && <p className="text-sm text-danger">{dispatchError}</p>}
      </div>

      <Disclosure label="調整結構（進階）">
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
                      onClick={() => setSelected(`group:${g.id}`)}
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
                        onClick={() => setSelected(`ad:${a.id}`)}
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
                brandId={brandId}
                group={selectedGroup}
                channels={channelInfo}
                campaignStartDate={c.start_date}
                campaignEndDate={c.end_date}
                onSaved={replaceGroup}
                onDelete={() => setDeleteTarget({ kind: "group", row: selectedGroup })}
              />
            ) : selectedAd ? (
              <AdPanel
                brandId={brandId}
                ad={selectedAd}
                vocabulary={vocabulary}
                campaignStatus={c.status}
                onSaved={replaceAd}
                onDelete={() => setDeleteTarget({ kind: "ad", row: selectedAd })}
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

function BoundNotice({ localState }: { localState: string }) {
  if (localState !== "bound") return null;
  return (
    <p className="text-xs text-warning">
      這個節點已經配對到平台，這裡的變更之後還要到平台後台手動同步一次。
    </p>
  );
}

function GroupPanel({
  brandId,
  group: g,
  channels,
  campaignStartDate,
  campaignEndDate,
  onSaved,
  onDelete,
}: {
  brandId: string;
  group: DeliveryGroupRow;
  channels: Channel[];
  campaignStartDate: string | null;
  campaignEndDate: string | null;
  onSaved: (group: DeliveryGroupRow) => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(g.name);
  const [role, setRole] = useState<StrategyRole>(g.role);
  const [dailyBudget, setDailyBudget] = useState(String(g.daily_budget));
  const [startDate, setStartDate] = useState(g.start_date ?? "");
  const [endDate, setEndDate] = useState(g.end_date ?? "");
  const [customDates, setCustomDates] = useState(Boolean(g.start_date || g.end_date));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setName(g.name);
    setRole(g.role);
    setDailyBudget(String(g.daily_budget));
    setStartDate(g.start_date ?? "");
    setEndDate(g.end_date ?? "");
    setCustomDates(Boolean(g.start_date || g.end_date));
    setError(null);
  }, [g]);

  const dirty =
    name !== g.name ||
    role !== g.role ||
    Number(dailyBudget) !== g.daily_budget ||
    (startDate || null) !== g.start_date ||
    (endDate || null) !== g.end_date;

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      onSaved(
        await patchGroup(brandId, g.id, {
          name,
          role,
          daily_budget: Number(dailyBudget),
          start_date: startDate || null,
          end_date: endDate || null,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新投放組失敗，請稍後再試。");
    } finally {
      setSaving(false);
    }
  }

  const sameAsCampaignText =
    campaignStartDate && campaignEndDate ? `跟活動同期間（${campaignStartDate} ~ ${campaignEndDate}）` : "跟活動同期間";

  return (
    <div className="surface">
      <div className="surface-header">
        <h2 className="flex items-center gap-1.5">
          <Folder size={15} /> {g.name}
        </h2>
        <Button variant="ghost" size="sm" onClick={onDelete} disabled={g.local_state === "bound"}>
          刪除
        </Button>
      </div>
      <div className="surface-body flex flex-col gap-4">
        <BoundNotice localState={g.local_state} />
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-sm">
            名稱
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            角色
            <select className={selectClassName()} value={role} onChange={(e) => setRole(e.target.value as StrategyRole)}>
              {(Object.keys(ROLE_LABEL) as StrategyRole[]).map((key) => (
                <option key={key} value={key}>
                  {ROLE_LABEL[key]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            每日預算
            <Input type="number" step={100} value={dailyBudget} onChange={(e) => setDailyBudget(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            投放平台
            <span className="flex h-9 items-center text-sm text-muted-foreground">
              {channels.find((c2) => c2.key === g.channel_key)?.label ?? g.channel_key}
            </span>
          </label>
          <div className="col-span-2 flex flex-col gap-1.5 text-sm">
            投放期間
            {customDates ? (
              <div className="flex flex-wrap items-center gap-2">
                <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
                <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setStartDate("");
                    setEndDate("");
                    setCustomDates(false);
                  }}
                >
                  改回跟活動同期間
                </Button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-muted-foreground">{sameAsCampaignText}</span>
                <Button type="button" variant="ghost" size="sm" onClick={() => setCustomDates(true)}>
                  自訂日期
                </Button>
              </div>
            )}
          </div>
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
        {(dirty || saving) && (
          <div>
            <Button onClick={() => void handleSave()} disabled={saving}>
              {saving ? "儲存中…" : "儲存變更"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function AdPanel({
  brandId,
  ad: a,
  vocabulary,
  campaignStatus,
  onSaved,
  onDelete,
}: {
  brandId: string;
  ad: AdRow;
  vocabulary: Coordinate[];
  campaignStatus: CampaignStatus;
  onSaved: (ad: AdRow) => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(a.name);
  const [coords, setCoords] = useState<AdCoordinates>(coordinatesFromAd(a));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setName(a.name);
    setCoords(coordinatesFromAd(a));
    setError(null);
  }, [a]);

  const baseline = coordinatesFromAd(a);
  const dirty =
    name !== a.name ||
    (Object.keys(coords) as (keyof AdCoordinates)[]).some((dim) => coords[dim] !== baseline[dim]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      onSaved(await patchAd(brandId, a.id, { name, coordinates: coords }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新廣告失敗，請稍後再試。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="surface">
      <div className="surface-header">
        <h2 className="flex items-center gap-1.5">
          <FileText size={15} /> {a.name}
        </h2>
        <Button variant="ghost" size="sm" onClick={onDelete} disabled={a.local_state === "bound"}>
          刪除
        </Button>
      </div>
      <div className="surface-body flex flex-col gap-4">
        <BoundNotice localState={a.local_state} />
        <label className="flex flex-col gap-1 text-sm">
          名稱
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          {COORDINATE_DIMENSIONS.map(([dim, label]) => (
            <CoordinateSelect
              key={dim}
              dimension={dim}
              label={label}
              value={coords[dim]}
              vocabulary={vocabulary}
              onChange={(next) => setCoords((prev) => ({ ...prev, [dim]: next }))}
            />
          ))}
        </div>
        <div className="flex flex-col gap-1 text-sm">
          <span className="text-xs text-muted-foreground">實際花費占比（觀察值）</span>
          {/* ponytail: 花費占比的單一出處是成效分頁的表（F03-I16），這一頁不重算、也不再多一支請求。 */}
          {campaignStatus === "live" || campaignStatus === "ended" || campaignStatus === "closed" ? (
            <span>在成效分頁看得到每則廣告的花費占比</span>
          ) : (
            <span>還沒發布，沒有花費可以分。</span>
          )}
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
        {(dirty || saving) && (
          <div>
            <Button onClick={() => void handleSave()} disabled={saving}>
              {saving ? "儲存中…" : "儲存變更"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function coordinatesFromAd(a: AdRow): AdCoordinates {
  return {
    audience: a.audience_key ?? "",
    pain: a.pain_key ?? "",
    angle: a.angle_key ?? "",
    hook: a.hook_key ?? "",
    proof: a.proof_key ?? "",
    offer: a.offer_key ?? "",
    format: a.format_key ?? "",
  };
}

function CoordinateSelect({
  dimension,
  label,
  value,
  vocabulary,
  onChange,
}: {
  dimension: CoordinateDimension;
  label: string;
  value: string;
  vocabulary: Coordinate[];
  onChange: (next: string) => void;
}) {
  const options = vocabulary.filter((v) => v.dimension === dimension && !v.disabled_at && !v.rejected);
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <select className={selectClassName()} value={value} onChange={(e) => onChange(e.target.value)}>
        {value && !options.some((o) => o.key === value) && <option value={value}>{value}</option>}
        <option value="">未設定</option>
        {options.map((o) => (
          <option key={o.id} value={o.key}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function AddGroupDialog({
  brandId,
  campaignId,
  onClose,
  onCreated,
}: {
  brandId: string;
  campaignId: string;
  onClose: () => void;
  onCreated: (group: DeliveryGroupRow) => void;
}) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<StrategyRole>("new");
  const [dailyBudget, setDailyBudget] = useState("1000");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate() {
    setSaving(true);
    setError(null);
    try {
      onCreated(await createGroup(brandId, campaignId, { name, role, daily_budget: Number(dailyBudget) }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "新增投放組失敗，請稍後再試。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>新增投放組</DialogTitle>
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm">
            名稱
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            角色
            <select className={selectClassName()} value={role} onChange={(e) => setRole(e.target.value as StrategyRole)}>
              {(Object.keys(ROLE_LABEL) as StrategyRole[]).map((key) => (
                <option key={key} value={key}>
                  {ROLE_LABEL[key]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            每日預算
            <Input type="number" step={100} value={dailyBudget} onChange={(e) => setDailyBudget(e.target.value)} />
          </label>
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button type="button" onClick={() => void handleCreate()} disabled={saving || !name.trim()}>
            {saving ? "新增中…" : "新增"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AddAdDialog({
  brandId,
  campaignId,
  groups,
  defaultGroupId,
  vocabulary,
  onClose,
  onCreated,
}: {
  brandId: string;
  campaignId: string;
  groups: DeliveryGroupRow[];
  defaultGroupId: string;
  vocabulary: Coordinate[];
  onClose: () => void;
  onCreated: (ad: AdRow) => void;
}) {
  const [groupId, setGroupId] = useState(defaultGroupId);
  const [name, setName] = useState("");
  const [coords, setCoords] = useState<AdCoordinates>({
    audience: "",
    pain: "",
    angle: "",
    hook: "",
    proof: "",
    offer: "",
    format: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const complete = name.trim() && Object.values(coords).every((v) => v.trim());

  async function handleCreate() {
    setSaving(true);
    setError(null);
    try {
      const input: CreateAdInput = { group_id: groupId, name, coordinates: coords };
      onCreated(await createAd(brandId, campaignId, input));
    } catch (err) {
      setError(err instanceof Error ? err.message : "新增廣告失敗，請稍後再試。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>新增廣告</DialogTitle>
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm">
            投放組
            <select className={selectClassName()} value={groupId} onChange={(e) => setGroupId(e.target.value)}>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            名稱
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            {COORDINATE_DIMENSIONS.map(([dim, label]) => (
              <CoordinateSelect
                key={dim}
                dimension={dim}
                label={label}
                value={coords[dim]}
                vocabulary={vocabulary}
                onChange={(next) => setCoords((prev) => ({ ...prev, [dim]: next }))}
              />
            ))}
          </div>
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button type="button" onClick={() => void handleCreate()} disabled={saving || !complete}>
            {saving ? "新增中…" : "新增"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
