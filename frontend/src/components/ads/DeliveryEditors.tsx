import { useEffect, useState } from "react";
import { Folder, FileText } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogTitle,
} from "@/components/layout/ui/dialog";
import { COORDINATE_DIMENSIONS, type Coordinate, type CoordinateDimension } from "@/lib/coordinatesApi";
import {
  createAd,
  createGroup,
  patchAd,
  patchGroup,
  type AdCoordinates,
  type AdRow,
  type CampaignStatus,
  type CreateAdInput,
  type DeliveryGroupRow,
  type StrategyRole,
} from "@/lib/adsApi";
import type { Channel } from "@/lib/adsLaunchApi";

// F06-I06：從 DeliveryTab.tsx 原樣搬出的「調整結構（進階）」編輯零件，行為、文案、測試都不動——
// 純粹為了讓 DeliveryTab.tsx 回到單檔 800 行上限以內（ARCHITECTURE.md §2、§7）。
export const ROLE_LABEL: Record<StrategyRole, string> = { new: "新客", retarget: "再行銷", explore: "探索" };

function selectClassName() {
  return "h-9 rounded-md border border-input bg-transparent px-3 text-sm";
}

function BoundNotice({ localState }: { localState: string }) {
  if (localState !== "bound") return null;
  return (
    <p className="text-xs text-warning">
      這個節點已經配對到平台，這裡的變更之後還要到平台後台手動同步一次。
    </p>
  );
}

export function GroupPanel({
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

export function AdPanel({
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

export function AddGroupDialog({
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

export function AddAdDialog({
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
