import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import { saveManualSettings, type ManualHandoff } from "@/lib/adsLaunchApi";
import { Disclosure } from "./patterns";

type FocusRequest = { key: string; token: number } | null;
const manualDraftCache = new Map<string, Record<string, string>>();

function readManualDraft(key: string): Record<string, string> | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (value && typeof value === "object" && Object.values(value).every((item) => typeof item === "string")) {
      return value as Record<string, string>;
    }
    return null;
  } catch { return manualDraftCache.get(key) ?? null; }
}

function saveManualDraft(key: string, values: Record<string, string>) {
  manualDraftCache.set(key, values);
  try { sessionStorage.setItem(key, JSON.stringify(values)); } catch { /* Memory fallback. */ }
}

function clearManualDraft(key: string) {
  manualDraftCache.delete(key);
  try { sessionStorage.removeItem(key); } catch { /* Storage unavailable. */ }
}

export function ManualSettings({ draftScope, brandId, campaign, onSaved, onDirtyChange, embedded = false }: {
  draftScope: string;
  brandId: string;
  campaign: Pick<CampaignDetail, "id" | "status" | "manual_handoff">;
  onSaved: (c: CampaignDetail) => void;
  onDirtyChange?: (dirty: boolean) => void;
  /** F29 Unresolved 5: inside the launch settings' 「進階設定」 fold (publish list stage) — the per-ad-set free-text
   * fields only, without this panel's own surface, summary and outer fold (the host's fold is the one fold). */
  embedded?: boolean;
}) {
  const handoff = campaign.manual_handoff;
  const [open, setOpen] = useState(false);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  const [dirtyGroups, setDirtyGroups] = useState<Record<string, boolean>>(() => Object.fromEntries(
    (handoff?.groups ?? []).map((group) => {
      const stored = readManualDraft(`brand-os:ads:manual-draft:v1:${draftScope}:${brandId}:${campaign.id}:${group.id}`);
      return [group.id, Boolean(stored && JSON.stringify(stored) !== JSON.stringify(group.values))];
    }),
  ));
  const [focusRequests, setFocusRequests] = useState<Record<string, FocusRequest>>({});
  const dirty = Object.values(dirtyGroups).some(Boolean);

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const setGroupDirty = useCallback((groupId: string, next: boolean) => {
    setDirtyGroups((current) => current[groupId] === next ? current : { ...current, [groupId]: next });
  }, []);

  if (!handoff?.groups.length) return null;

  function missingField(group: ManualHandoff["groups"][number]) {
    return handoff!.fields.find((field) => field.required && !group.values[field.key]?.trim())
      ?? handoff!.fields.find((field) => group.missing.some((label) => label === field.label));
  }

  function focusMissing(group: ManualHandoff["groups"][number]) {
    const field = missingField(group);
    if (!field) return;
    setOpen(true);
    setOpenGroups((current) => ({ ...current, [group.id]: true }));
    setFocusRequests((current) => ({
      ...current,
      [group.id]: { key: field.key, token: (current[group.id]?.token ?? 0) + 1 },
    }));
  }

  const groupFolds = (
    <div className="flex flex-col gap-4">
      {handoff.groups.map((group) => (
        <Disclosure key={group.id} label={`${group.name} · ${dirtyGroups[group.id] ? "有未儲存變更" : group.status}`}
          open={Boolean(openGroups[group.id])}
          onOpenChange={(next) => setOpenGroups((current) => ({ ...current, [group.id]: next }))}>
          <GroupSettings brandId={brandId} campaignId={campaign.id} fields={handoff.fields} group={group}
            locked={campaign.status === "closed"} onSaved={onSaved}
            draftKey={`brand-os:ads:manual-draft:v1:${draftScope}:${brandId}:${campaign.id}:${group.id}`}
            focusRequest={focusRequests[group.id] ?? null}
            onDirtyChange={(next) => setGroupDirty(group.id, next)} />
        </Disclosure>
      ))}
    </div>
  );
  const fillButtons = handoff.groups.filter((group) => group.missing.length > 0).map((group) => (
    <Button key={group.id} type="button" size="sm" variant="outline" onClick={() => focusMissing(group)}>
      補齊{group.name}設定
    </Button>
  ));

  if (embedded) {
    return (
      <div className="flex flex-col gap-3" aria-label="各廣告組的其他設定" role="group">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            各廣告組的其他設定：{handoff.pending_count ? `${handoff.pending_count} 組待補` : "已填齊"}
            {dirty && <span className="ml-1 font-medium text-warning">有尚未儲存的變更。</span>}
          </p>
          <div className="flex flex-wrap gap-2">{fillButtons}</div>
        </div>
        {groupFolds}
      </div>
    );
  }

  return (
    <div className="surface">
      <div className="surface-body flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            人工上架：{handoff.pending_count ? `${handoff.pending_count} 組設定待補` : "設定已填齊，仍需到平台核對"}。
            再行銷需確認受眾池；這裡儲存設定，不會對外發布或更動預算。
            {dirty && <span className="ml-1 font-medium text-warning">有尚未儲存的變更。</span>}
          </p>
          {fillButtons}
        </div>
        <div className="flex flex-col gap-1" aria-label="人工上架設定摘要">
          {handoff.groups.map((group) => {
            const effective = Object.entries(group.values)
              .filter(([, value]) => value.trim())
              .map(([key, value]) => `${handoff.fields.find((field) => field.key === key)?.label ?? key}＝${value}`)
              .join("、");
            return <p key={group.id} className="text-xs text-muted-foreground">
              {group.name}：{effective || "尚未自訂"}；作用於這個投放組；
              {dirtyGroups[group.id] ? "有未儲存變更" : Object.keys(group.values).length ? "已自訂" : "使用預設值"}。
            </p>;
          })}
        </div>
        <Disclosure label={`人工上架設定與平台對應 · ${dirty ? "有未儲存變更" : `作用於這個 Campaign 的 ${handoff.groups.length} 組`}`}
          open={open} onOpenChange={setOpen}>
          {groupFolds}
        </Disclosure>
      </div>
    </div>
  );
}

function GroupSettings({ brandId, campaignId, fields, group, locked, onSaved, draftKey, focusRequest, onDirtyChange }: {
  brandId: string;
  campaignId: string;
  fields: ManualHandoff["fields"];
  group: ManualHandoff["groups"][number];
  locked: boolean;
  onSaved: (c: CampaignDetail) => void;
  draftKey: string;
  focusRequest: FocusRequest;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const restoredValues = useRef((() => {
    const stored = readManualDraft(draftKey);
    return stored && JSON.stringify(stored) !== JSON.stringify(group.values) ? stored : null;
  })());
  const [values, setValues] = useState({ ...(restoredValues.current ?? group.values) });
  const [baseline, setBaseline] = useState({ ...group.values });
  const [restored, setRestored] = useState(Boolean(restoredValues.current));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const requestedField = fields.find((field) => field.key === focusRequest?.key);
  const [section, setSection] = useState(requestedField?.section ?? fields[0]?.section ?? "受眾");
  const fieldRefs = useRef<Record<string, HTMLInputElement | HTMLTextAreaElement | null>>({});
  const fieldPrefix = useId();
  const incomingSignature = JSON.stringify(group.values);
  const dirty = JSON.stringify(values) !== JSON.stringify(baseline);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  useEffect(() => {
    if (!dirtyRef.current) {
      setValues({ ...group.values });
      setBaseline({ ...group.values });
    }
  }, [incomingSignature, group.values]);

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  useEffect(() => {
    if (dirty) saveManualDraft(draftKey, values);
    else clearManualDraft(draftKey);
  }, [dirty, draftKey, values]);

  // A focus request is consumed once (by its token): the jump switches the section a single time, and the user can
  // switch sections afterwards without being dragged back. A new 補齊 click carries a new token and jumps again.
  const handledFocusToken = useRef<number | null>(null);
  useEffect(() => {
    if (!focusRequest || !requestedField || handledFocusToken.current === focusRequest.token) return;
    if (section !== requestedField.section) {
      setSection(requestedField.section);
      return;
    }
    const timer = window.setTimeout(() => {
      handledFocusToken.current = focusRequest.token;
      fieldRefs.current[focusRequest.key]?.focus();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [focusRequest, requestedField, section]);

  async function save() {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await saveManualSettings(brandId, campaignId, group.id, values);
      clearManualDraft(draftKey);
      setBaseline({ ...values });
      setRestored(false);
      onSaved(await getCampaign(brandId, campaignId));
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "儲存失敗，已填內容保留在此。");
    } finally {
      setBusy(false);
    }
  }

  function cancel() {
    setValues({ ...group.values });
    setBaseline({ ...group.values });
    setError(null);
    setSaved(false);
    setRestored(false);
    clearManualDraft(draftKey);
  }

  return (
    <div className="flex flex-col gap-3">
      {group.missing.length > 0 && <p className="text-sm text-warning">待補：{group.missing.join("、")}</p>}
      {restored && <p role="status" className="text-sm text-warning">
        已恢復未儲存草稿；最新已保存值可能已變更，請確認後再儲存。
      </p>}
      <p className="text-xs text-muted-foreground">
        生效範圍：{group.name}；目前 {Object.keys(group.values).length ? "已自訂" : "尚未自訂"}。
      </p>
      <div className="flex flex-wrap gap-2" aria-label="設定分類">
        {[...new Set(fields.map((f) => f.section))].map((name) => (
          <Button key={name} type="button" size="sm" variant={section === name ? "default" : "outline"}
            onClick={() => setSection(name)}>{name}</Button>
        ))}
      </div>
      {section === "上架紀錄" && (
        <div className="text-sm text-muted-foreground">
          <p>手動填入的 ID 尚未經平台配對驗證，不會改變同步狀態。</p>
          {group.ads.map((ad) => <p key={ad.id}>{ad.name}：<code>{ad.id}</code></p>)}
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {fields.filter((f) => f.section === section).map((field) => {
          const id = `${fieldPrefix}-${field.key}`;
          return (
            <label key={field.key} htmlFor={id} className="flex flex-col gap-1 text-sm">
              {field.label}{field.required ? " *" : ""}
              {field.key === "ad_platform_ids" || field.key === "execution_notes" ? (
                <Textarea id={id} ref={(node) => { fieldRefs.current[field.key] = node; }}
                  value={values[field.key] ?? ""} maxLength={2000} disabled={busy || locked}
                  onChange={(e) => { setSaved(false); setValues({ ...values, [field.key]: e.target.value }); }} />
              ) : (
                <Input id={id} ref={(node) => { fieldRefs.current[field.key] = node; }}
                  value={values[field.key] ?? ""} maxLength={2000} disabled={busy || locked}
                  onChange={(e) => { setSaved(false); setValues({ ...values, [field.key]: e.target.value }); }} />
              )}
            </label>
          );
        })}
      </div>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {(saved || group.saved_at || dirty) && <p role="status" className="text-sm text-muted-foreground">
        {dirty ? "有尚未儲存的變更" : "設定已儲存"}
      </p>}
      <div className="flex flex-wrap gap-2">
        <Button className="w-fit" disabled={busy || locked || !dirty} onClick={() => void save()}>
          {busy ? "儲存中…" : "儲存這組設定"}
        </Button>
        {dirty && <Button type="button" variant="outline" disabled={busy} onClick={cancel}>取消變更</Button>}
      </div>
    </div>
  );
}
