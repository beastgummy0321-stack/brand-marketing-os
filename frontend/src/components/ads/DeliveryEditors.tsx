import { ApiResponseError, isRejected } from "@/lib/http";
import { useEffect, useRef, useState } from "react";
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
  type PlanMenuRow,
  type StrategyRole,
} from "@/lib/adsApi";
import type { Channel } from "@/lib/adsLaunchApi";
import { Chip } from "./patterns";

type GroupDraft = {
  name: string;
  role: StrategyRole;
  dailyBudget: string;
  startDate: string;
  endDate: string;
  customDates: boolean;
};
type AdDraft = { name: string; coords: AdCoordinates };
const deliveryDraftCache = new Map<string, GroupDraft | AdDraft>();

function readGroupDraft(key: string): GroupDraft | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<GroupDraft> | null;
    if (value && typeof value.name === "string" && typeof value.role === "string" &&
        typeof value.dailyBudget === "string" && typeof value.startDate === "string" &&
        typeof value.endDate === "string" && typeof value.customDates === "boolean") return value as GroupDraft;
    return null;
  } catch { return (deliveryDraftCache.get(key) as GroupDraft | undefined) ?? null; }
}

function readAdDraft(key: string): AdDraft | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<AdDraft> | null;
    if (value && typeof value.name === "string" && value.coords && typeof value.coords === "object" &&
        Object.values(value.coords).every((item) => typeof item === "string")) return value as AdDraft;
    return null;
  } catch { return (deliveryDraftCache.get(key) as AdDraft | undefined) ?? null; }
}

function saveDeliveryDraft(key: string, value: GroupDraft | AdDraft) {
  deliveryDraftCache.set(key, value);
  try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* Memory fallback. */ }
}

function clearDeliveryDraft(key: string) {
  deliveryDraftCache.delete(key);
  try { sessionStorage.removeItem(key); } catch { /* Storage unavailable. */ }
}

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

const LAST_GROUP_REASON = "至少要留一個投放組；想換掉請先新增再刪。";

/** F48-I06: the dimensions this period's menu (`campaign.menu`) narrows — the proof the brand has, the offers this
 * sell-way can honour, the formats the brand makes. Other dimensions list the brand vocabulary as before. */
const MENU_DIMENSIONS: CoordinateDimension[] = ["proof", "offer", "format"];
/** A key the ad already holds that this period's menu leaves out: still shown so the select never lies about it. */
const NOT_THIS_PERIOD = "這期不能用";

/** Where a refused ad save's sentence belongs: `name_forbidden` beside the name, `coordinate_unavailable` beside the
 * coordinates, anything else under the form. The sentence is always the server's. */
type AdErrors = { name: string | null; coords: string | null; other: string | null };
const NO_AD_ERRORS: AdErrors = { name: null, coords: null, other: null };
function adErrorsFrom(err: unknown, fallback: string): AdErrors {
  const message = err instanceof Error ? err.message : fallback;
  const code = err instanceof ApiResponseError ? err.code : null;
  if (code === "name_forbidden") return { ...NO_AD_ERRORS, name: message };
  if (code === "coordinate_unavailable") return { ...NO_AD_ERRORS, coords: message };
  return { ...NO_AD_ERRORS, other: message };
}
const FieldError = ({ text }: { text: string | null }) =>
  text ? <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">{text}</p> : null;

/** F48 Contract K: the served 「沿用上一期」 chip of a carried ad (nothing for any other ad). */
export function CarriedChip({ ad }: { ad: AdRow }) {
  return ad.carried_label ? <Chip tone="accent">{ad.carried_label}</Chip> : null;
}

export function GroupPanel({
  brandId,
  group: g,
  channels,
  campaignStartDate,
  campaignEndDate,
  onSaved,
  onDelete,
  isLastGroup = false,
  onDirtyChange,
  draftKey,
}: {
  brandId: string;
  group: DeliveryGroupRow;
  channels: Channel[];
  campaignStartDate: string | null;
  campaignEndDate: string | null;
  onSaved: (group: DeliveryGroupRow) => void;
  onDelete: () => void;
  // The backend refuses removing a campaign's last group (ads §6.34); say why up front.
  isLastGroup?: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  draftKey: string;
}) {
  const restoredDraft = useRef((() => {
    const stored = readGroupDraft(draftKey);
    const saved = {
      name: g.name, role: g.role, dailyBudget: String(g.daily_budget),
      startDate: g.start_date ?? "", endDate: g.end_date ?? "", customDates: Boolean(g.start_date || g.end_date),
    };
    return stored && JSON.stringify(stored) !== JSON.stringify(saved) ? stored : null;
  })());
  const [name, setName] = useState(restoredDraft.current?.name ?? g.name);
  const [role, setRole] = useState<StrategyRole>(restoredDraft.current?.role ?? g.role);
  const [dailyBudget, setDailyBudget] = useState(restoredDraft.current?.dailyBudget ?? String(g.daily_budget));
  const [startDate, setStartDate] = useState(restoredDraft.current?.startDate ?? g.start_date ?? "");
  const [endDate, setEndDate] = useState(restoredDraft.current?.endDate ?? g.end_date ?? "");
  const [customDates, setCustomDates] = useState(restoredDraft.current?.customDates ?? Boolean(g.start_date || g.end_date));
  const [restored, setRestored] = useState(Boolean(restoredDraft.current));
  const [saving, setSaving] = useState(false);
  // F50 Contract I (c1-08): a group date outside the campaign is refused with the server's sentence naming the window
  // (`group_dates_outside`); it is printed under the dates, every other refusal under the form.
  const [error, setError] = useState<{ text: string; dates: boolean } | null>(null);
  const [baseline, setBaseline] = useState(g);
  const dirty =
    name !== baseline.name ||
    role !== baseline.role ||
    Number(dailyBudget) !== baseline.daily_budget ||
    (startDate || null) !== baseline.start_date ||
    (endDate || null) !== baseline.end_date;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const incomingSignature = JSON.stringify(g);

  useEffect(() => {
    if (!dirtyRef.current) reset(g);
  }, [g, incomingSignature]);

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  useEffect(() => {
    if (dirty) saveDeliveryDraft(draftKey, { name, role, dailyBudget, startDate, endDate, customDates });
    else clearDeliveryDraft(draftKey);
  }, [customDates, dailyBudget, dirty, draftKey, endDate, name, role, startDate]);
  // F47-I06: a refusal's red sentence goes as soon as a field changes (it no longer describes what is on screen).
  useEffect(() => { setError(null); }, [name, role, dailyBudget, startDate, endDate]);

  function reset(next: DeliveryGroupRow) {
    setName(next.name);
    setRole(next.role);
    setDailyBudget(String(next.daily_budget));
    setStartDate(next.start_date ?? "");
    setEndDate(next.end_date ?? "");
    setCustomDates(Boolean(next.start_date || next.end_date));
    setBaseline(next);
    setError(null);
    setRestored(false);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const next = await patchGroup(brandId, g.id, {
        name,
        role,
        daily_budget: Number(dailyBudget),
        start_date: startDate || null,
        end_date: endDate || null,
      });
      reset(next);
      clearDeliveryDraft(draftKey);
      onSaved(next);
    } catch (err) {
      setError({
        text: err instanceof Error ? err.message : "更新投放組失敗，請稍後再試。",
        dates: isRejected(err, "group_dates_outside"),
      });
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
        <Button
          variant="ghost" size="sm" onClick={onDelete}
          disabled={g.local_state === "bound" || isLastGroup}
          title={isLastGroup ? LAST_GROUP_REASON : undefined}
        >
          刪除
        </Button>
      </div>
      <div className="surface-body flex flex-col gap-4">
        <BoundNotice localState={g.local_state} />
        {isLastGroup && <p className="text-sm text-muted-foreground">{LAST_GROUP_REASON}</p>}
        {restored && <p role="status" className="text-sm text-warning">
          已恢復未儲存草稿；最新已保存值可能已變更，請確認後再儲存。
        </p>}
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
            <FieldError text={error?.dates ? error.text : null} />
          </div>
        </div>
        {error && !error.dates && <p className="text-sm text-danger">{error.text}</p>}
        {(dirty || saving) && (
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void handleSave()} disabled={saving}>
              {saving ? "儲存中…" : "儲存變更"}
            </Button>
            {dirty && <Button type="button" variant="outline" onClick={() => { clearDeliveryDraft(draftKey); reset(g); }} disabled={saving}>取消變更</Button>}
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
  menu = null,
  campaignStatus,
  onSaved,
  onDelete,
  onDirtyChange,
  draftKey,
}: {
  brandId: string;
  ad: AdRow;
  vocabulary: Coordinate[];
  /** This period's menu (`campaign.menu`); null = not known, the vocabulary is listed unfiltered. */
  menu?: PlanMenuRow[] | null;
  campaignStatus: CampaignStatus;
  onSaved: (ad: AdRow) => void;
  onDelete: () => void;
  onDirtyChange?: (dirty: boolean) => void;
  draftKey: string;
}) {
  const restoredDraft = useRef((() => {
    const stored = readAdDraft(draftKey);
    const saved = { name: a.name, coords: coordinatesFromAd(a) };
    return stored && JSON.stringify(stored) !== JSON.stringify(saved) ? stored : null;
  })());
  const [name, setName] = useState(restoredDraft.current?.name ?? a.name);
  const [coords, setCoords] = useState<AdCoordinates>(restoredDraft.current?.coords ?? coordinatesFromAd(a));
  const [restored, setRestored] = useState(Boolean(restoredDraft.current));
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<AdErrors>(NO_AD_ERRORS);
  const [baseline, setBaseline] = useState(a);
  const baselineCoords = coordinatesFromAd(baseline);
  const dirty =
    name !== baseline.name ||
    (Object.keys(coords) as (keyof AdCoordinates)[]).some((dim) => coords[dim] !== baselineCoords[dim]);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const incomingSignature = JSON.stringify(a);

  useEffect(() => {
    if (!dirtyRef.current) reset(a);
  }, [a, incomingSignature]);

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  useEffect(() => {
    if (dirty) saveDeliveryDraft(draftKey, { name, coords });
    else clearDeliveryDraft(draftKey);
  }, [coords, dirty, draftKey, name]);
  useEffect(() => { setErrors(NO_AD_ERRORS); }, [name, coords]);

  function reset(next: AdRow) {
    setName(next.name);
    setCoords(coordinatesFromAd(next));
    setBaseline(next);
    setErrors(NO_AD_ERRORS);
    setRestored(false);
  }

  async function handleSave() {
    setSaving(true);
    setErrors(NO_AD_ERRORS);
    try {
      const next = await patchAd(brandId, a.id, { name, coordinates: coords });
      reset(next);
      clearDeliveryDraft(draftKey);
      onSaved(next);
    } catch (err) {
      setErrors(adErrorsFrom(err, "更新廣告失敗，請稍後再試。"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="surface">
      <div className="surface-header">
        <h2 className="flex min-w-0 flex-wrap items-center gap-1.5">
          <FileText size={15} /> {a.name} <CarriedChip ad={a} />
        </h2>
        <Button variant="ghost" size="sm" onClick={onDelete} disabled={a.local_state === "bound"}>
          刪除
        </Button>
      </div>
      <div className="surface-body flex flex-col gap-4">
        {a.carry_note && <p data-slot="carry-note" className="text-xs text-muted-foreground">{a.carry_note}</p>}
        <BoundNotice localState={a.local_state} />
        {restored && <p role="status" className="text-sm text-warning">
          已恢復未儲存草稿；最新已保存值可能已變更，請確認後再儲存。
        </p>}
        <div className="flex flex-col gap-1">
          <label className="flex flex-col gap-1 text-sm">
            名稱
            <Input value={name} onChange={(e) => setName(e.target.value)} aria-invalid={errors.name !== null} />
          </label>
          <FieldError text={errors.name} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          {COORDINATE_DIMENSIONS.map(([dim, label]) => (
            <CoordinateSelect
              key={dim}
              dimension={dim}
              label={label}
              value={coords[dim]}
              vocabulary={vocabulary}
              menu={menu}
              onChange={(next) => setCoords((prev) => ({ ...prev, [dim]: next }))}
            />
          ))}
        </div>
        <FieldError text={errors.coords} />
        <div className="flex flex-col gap-1 text-sm">
          <span className="text-xs text-muted-foreground">實際花費占比（觀察值）</span>
          {/* ponytail: 花費占比的單一出處是成效分頁的表（F03-I16），這一頁不重算、也不再多一支請求。 */}
          {campaignStatus === "live" || campaignStatus === "ended" || campaignStatus === "closed" ? (
            <span>在成效分頁看得到每則廣告的花費占比</span>
          ) : (
            <span>還沒發布，沒有花費可以分。</span>
          )}
        </div>
        {errors.other && <p className="text-sm text-danger">{errors.other}</p>}
        {(dirty || saving) && (
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void handleSave()} disabled={saving}>
              {saving ? "儲存中…" : "儲存變更"}
            </Button>
            {dirty && <Button type="button" variant="outline" onClick={() => { clearDeliveryDraft(draftKey); reset(a); }} disabled={saving}>取消變更</Button>}
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

/** One coordinate's select. On a menu dimension the options are this period's menu (`menu`); a key the ad already
 * holds outside it stays listed, marked 「這期不能用」 (saving it again is refused by the server, which says why). */
function CoordinateSelect({
  dimension,
  label,
  value,
  vocabulary,
  menu = null,
  onChange,
}: {
  dimension: CoordinateDimension;
  label: string;
  value: string;
  vocabulary: Coordinate[];
  menu?: PlanMenuRow[] | null;
  onChange: (next: string) => void;
}) {
  const allowed = menu && MENU_DIMENSIONS.includes(dimension)
    ? new Set(menu.filter((row) => row.dimension === dimension).map((row) => row.key))
    : null;
  const options = vocabulary.filter((v) => v.dimension === dimension && !v.disabled_at && !v.rejected && (!allowed || allowed.has(v.key)));
  const held = value && !options.some((o) => o.key === value)
    ? vocabulary.find((v) => v.dimension === dimension && v.key === value) ?? null
    : null;
  const heldText = held ? held.label : value;
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <select className={selectClassName()} value={value} onChange={(e) => onChange(e.target.value)}>
        {value && !options.some((o) => o.key === value) && (
          <option value={value}>{allowed && !allowed.has(value) ? `${heldText}（${NOT_THIS_PERIOD}）` : heldText}</option>
        )}
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
  useEffect(() => { setError(null); }, [name, role, dailyBudget]);

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
          <Button type="button" onClick={() => void handleCreate()} disabled={saving || !name.trim()}
            disabledReason={!saving && !name.trim() ? "名稱還沒填" : undefined}>
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
  menu = null,
  onClose,
  onCreated,
}: {
  brandId: string;
  campaignId: string;
  groups: DeliveryGroupRow[];
  defaultGroupId: string;
  vocabulary: Coordinate[];
  /** This period's menu (`campaign.menu`), the same one the planner chose from. */
  menu?: PlanMenuRow[] | null;
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
  const [errors, setErrors] = useState<AdErrors>(NO_AD_ERRORS);

  const complete = name.trim() && Object.values(coords).every((v) => v.trim());
  // F47-I06 (V7): the greyed-out 新增 names what is still empty.
  const missing = [
    ...(name.trim() ? [] : ["名稱"]),
    ...COORDINATE_DIMENSIONS.filter(([dim]) => !coords[dim].trim()).map(([, label]) => label),
  ];
  useEffect(() => { setErrors(NO_AD_ERRORS); }, [groupId, name, coords]);

  async function handleCreate() {
    setSaving(true);
    setErrors(NO_AD_ERRORS);
    try {
      const input: CreateAdInput = { group_id: groupId, name, coordinates: coords };
      onCreated(await createAd(brandId, campaignId, input));
    } catch (err) {
      setErrors(adErrorsFrom(err, "新增廣告失敗，請稍後再試。"));
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
          <div className="flex flex-col gap-1">
            <label className="flex flex-col gap-1 text-sm">
              名稱
              <Input value={name} onChange={(e) => setName(e.target.value)} aria-invalid={errors.name !== null} />
            </label>
            <FieldError text={errors.name} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            {COORDINATE_DIMENSIONS.map(([dim, label]) => (
              <CoordinateSelect
                key={dim}
                dimension={dim}
                label={label}
                value={coords[dim]}
                vocabulary={vocabulary}
                menu={menu}
                onChange={(next) => setCoords((prev) => ({ ...prev, [dim]: next }))}
              />
            ))}
          </div>
          <FieldError text={errors.coords} />
        </div>
        {errors.other && <p className="text-sm text-danger">{errors.other}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button type="button" onClick={() => void handleCreate()} disabled={saving || !complete}
            disabledReason={!saving && missing.length ? `還沒選：${missing.join("、")}` : undefined}>
            {saving ? "新增中…" : "新增"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
