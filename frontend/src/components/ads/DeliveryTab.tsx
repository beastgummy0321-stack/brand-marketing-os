import { useEffect, useState } from "react";
import { Plus, Folder, FileText, Layers } from "lucide-react";
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
import { fetchMetaAccounts } from "@/lib/metaApi";
import { COORDINATE_DIMENSIONS, fetchCoordinates, type Coordinate, type CoordinateDimension } from "@/lib/coordinatesApi";
import {
  adoptStrategy,
  createAd,
  createGroup,
  currentBudgetTotal,
  deleteAd,
  deleteGroup,
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

const ROLE_LABEL: Record<StrategyRole, string> = { new: "新客", retarget: "再行銷", explore: "探索" };
const LOCAL_STATE_LABEL: Record<string, string> = {
  unbound: "未綁定",
  bound: "已綁定",
  detached: "已解除",
  retired: "已停用",
};
const CHANNEL_LABEL: Record<string, string> = {
  meta: "Meta",
  google_ads: "Google Ads",
  tiktok: "TikTok",
  shopee: "蝦皮",
  momo: "momo",
};

type SelectedKey = `group:${string}` | `ad:${string}`;

function selectClassName() {
  return "h-9 rounded-md border border-input bg-transparent px-3 text-sm";
}

/** 投放結構 tab（F03-I15）：Campaign → 通路 → 投放組 → 廣告，左邊樹、右邊選中節點的
 * 編輯面板。素材工作檯尚未接進來前先用 §0 settled 的最小樣式——沒有批次列、沒有發布前
 * 檢查面板、沒有搜尋框，那些是 F05／feature 3 的事。 */
export function DeliveryTab({
  brandId,
  campaign: c,
  onCampaignChange,
}: {
  brandId: string;
  campaign: CampaignDetail;
  onCampaignChange: (campaign: CampaignDetail) => void;
}) {
  const [adopting, setAdopting] = useState(false);
  const [adoptError, setAdoptError] = useState<string | null>(null);
  const [selected, setSelected] = useState<SelectedKey | null>(null);
  const [vocabulary, setVocabulary] = useState<Coordinate[]>([]);
  const [metaConnected, setMetaConnected] = useState<boolean | null>(null);
  const [addGroupOpen, setAddGroupOpen] = useState(false);
  const [addAdOpen, setAddAdOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<
    { kind: "group"; row: DeliveryGroupRow } | { kind: "ad"; row: AdRow } | null
  >(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    fetchCoordinates(brandId).then(setVocabulary).catch(() => setVocabulary([]));
    // 通路是否「已接上」只有 Meta 查得到（`app/ads/channels.py`）；沒有把它接進
    // Campaign 的 payload 裡，這裡改讀既有的 `/api/meta/accounts`（設定頁同一支），
    // 不碰 app/ads 後端。
    fetchMetaAccounts()
      .then((data) => setMetaConnected(data.accounts.some((a) => a.bound_brand_ids.includes(brandId))))
      .catch(() => setMetaConnected(null));
  }, [brandId]);

  const firstGroupId = c.groups[0]?.id;
  const effectiveSelected: SelectedKey | null = selected ?? (firstGroupId ? `group:${firstGroupId}` : null);

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

  const channels = [...new Set(c.groups.map((g) => g.channel_key))];
  const selectedGroup = effectiveSelected?.startsWith("group:")
    ? c.groups.find((g) => `group:${g.id}` === effectiveSelected) ?? null
    : null;
  const selectedAd = effectiveSelected?.startsWith("ad:")
    ? c.groups.flatMap((g) => g.ads).find((a) => `ad:${a.id}` === effectiveSelected) ?? null
    : null;

  const t = currentBudgetTotal(c);
  const diff = t.total !== null && c.budget_planned !== null ? t.total - c.budget_planned : null;

  return (
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
          {channels.map((key) => (
            <div key={key} className="flex items-center gap-2 py-1.5 pl-4 text-sm text-muted-foreground">
              <span>Ⓜ {CHANNEL_LABEL[key] ?? key}</span>
              {key === "meta" ? (
                metaConnected === null ? null : (
                  <Badge variant={metaConnected ? "default" : "outline"}>
                    {metaConnected ? "已接上" : "未接上"}
                  </Badge>
                )
              ) : (
                <Badge variant="outline">未接上</Badge>
              )}
            </div>
          ))}
          {c.groups.map((g) => (
            <div key={g.id}>
              <button
                type="button"
                onClick={() => setSelected(`group:${g.id}`)}
                className={`flex w-full items-center gap-2 rounded-md py-1.5 pl-6 pr-2 text-left text-sm ${
                  effectiveSelected === `group:${g.id}` ? "bg-accent" : "hover:bg-muted"
                }`}
              >
                <Folder size={13} className="shrink-0 text-muted-foreground" />
                <span className="flex-1 truncate">{g.name}</span>
                <Badge variant={g.local_state === "bound" ? "default" : "outline"}>
                  {LOCAL_STATE_LABEL[g.local_state]}
                </Badge>
              </button>
              {g.ads.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => setSelected(`ad:${a.id}`)}
                  className={`flex w-full items-center gap-2 rounded-md py-1.5 pl-12 pr-2 text-left text-sm ${
                    effectiveSelected === `ad:${a.id}` ? "bg-accent" : "hover:bg-muted"
                  }`}
                >
                  <FileText size={12} className="shrink-0 text-muted-foreground" />
                  <span className="flex-1 truncate">{a.name}</span>
                  <Badge variant={a.local_state === "bound" ? "default" : "outline"}>
                    {LOCAL_STATE_LABEL[a.local_state]}
                  </Badge>
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>

      {selectedGroup && (
        <GroupPanel
          brandId={brandId}
          group={selectedGroup}
          onSaved={replaceGroup}
          onDelete={() => setDeleteTarget({ kind: "group", row: selectedGroup })}
        />
      )}
      {selectedAd && (
        <AdPanel
          brandId={brandId}
          ad={selectedAd}
          vocabulary={vocabulary}
          campaignStatus={c.status}
          onSaved={replaceAd}
          onDelete={() => setDeleteTarget({ kind: "ad", row: selectedAd })}
        />
      )}
      </div>

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
  onSaved,
  onDelete,
}: {
  brandId: string;
  group: DeliveryGroupRow;
  onSaved: (group: DeliveryGroupRow) => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(g.name);
  const [role, setRole] = useState<StrategyRole>(g.role);
  const [dailyBudget, setDailyBudget] = useState(String(g.daily_budget));
  const [startDate, setStartDate] = useState(g.start_date ?? "");
  const [endDate, setEndDate] = useState(g.end_date ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setName(g.name);
    setRole(g.role);
    setDailyBudget(String(g.daily_budget));
    setStartDate(g.start_date ?? "");
    setEndDate(g.end_date ?? "");
    setError(null);
  }, [g]);

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
              {CHANNEL_LABEL[g.channel_key] ?? g.channel_key}
            </span>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            開始日期
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            結束日期
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
        <div>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving ? "儲存中…" : "儲存"}
          </Button>
        </div>
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
        <div>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving ? "儲存中…" : "儲存"}
          </Button>
        </div>
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
