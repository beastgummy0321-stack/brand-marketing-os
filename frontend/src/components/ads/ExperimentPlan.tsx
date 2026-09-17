import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import {
  confirmComparison,
  readComparison,
  saveComparisonSettings,
  type ComparisonOverrides,
  type ComparisonSettings,
  type ComparisonState,
} from "@/lib/adsExperimentApi";
import { Disclosure } from "./patterns";

type SettingKey = keyof ComparisonSettings["effective"];
type SettingsDraft = {
  min_days: string;
  min_conversions_each: string;
  relative_difference: string;
  windowStart: string;
  windowEnd: string;
};
type StoredComparisonDraft = {
  base: ComparisonSettings;
  draft: SettingsDraft;
  resetKeys: SettingKey[];
};

function readStoredDraft(key: string): StoredComparisonDraft | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) ?? "null") as StoredComparisonDraft | null;
    if (value?.base?.revision && value.draft && Array.isArray(value.resetKeys)) return value;
  } catch { /* An unavailable store cannot promise restoration. */ }
  return null;
}

function saveStoredDraft(key: string, value: StoredComparisonDraft) {
  try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* Keep the mounted draft only. */ }
}

function clearStoredDraft(key: string) {
  try { sessionStorage.removeItem(key); } catch { /* Storage unavailable. */ }
}

function draftFrom(settings: ComparisonSettings): SettingsDraft {
  return {
    min_days: String(settings.effective.min_days),
    min_conversions_each: String(settings.effective.min_conversions_each),
    relative_difference: String(settings.effective.relative_difference),
    windowStart: settings.effective.window.start ?? "",
    windowEnd: settings.effective.window.end ?? "",
  };
}

function draftDiffers(draft: SettingsDraft | null, settings?: ComparisonSettings) {
  if (!draft || !settings) return false;
  return draft.min_days !== String(settings.effective.min_days)
    || draft.min_conversions_each !== String(settings.effective.min_conversions_each)
    || draft.relative_difference !== String(settings.effective.relative_difference)
    || draft.windowStart !== (settings.effective.window.start ?? "")
    || draft.windowEnd !== (settings.effective.window.end ?? "");
}

export function ExperimentPlan({ draftScope, brandId, campaignId, hasSavedComparison, refreshToken, onViewPlan }: {
  draftScope: string;
  brandId: string;
  campaignId: string;
  hasSavedComparison: boolean;
  refreshToken?: string | number;
  onViewPlan: () => void;
}) {
  const storageKey = `brand-os:ads:comparison-draft:v1:${draftScope}:${brandId}:${campaignId}`;
  const stored = useRef(readStoredDraft(storageKey));
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<ComparisonState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [draft, setDraft] = useState<SettingsDraft | null>(stored.current?.draft ?? null);
  const [editBase, setEditBase] = useState<ComparisonSettings | null>(stored.current?.base ?? null);
  const [resetKeys, setResetKeys] = useState<Set<SettingKey>>(new Set(stored.current?.resetKeys ?? []));
  const [restored, setRestored] = useState(Boolean(stored.current));
  const [refreshNotice, setRefreshNotice] = useState<string | null>(null);
  const shouldLoad = open || hasSavedComparison || restored;
  const dirty = draftDiffers(draft, editBase ?? undefined) || resetKeys.size > 0;
  const remoteChanged = Boolean(editBase && state?.settings && editBase.revision !== state.settings.revision);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const editBaseRef = useRef(editBase);
  editBaseRef.current = editBase;

  const startEditing = useCallback((settings: ComparisonSettings) => {
    setEditBase(settings);
    setDraft(draftFrom(settings));
    setResetKeys(new Set());
    setRefreshNotice(null);
    setRestored(false);
    clearStoredDraft(storageKey);
  }, [storageKey]);

  useEffect(() => {
    if (!dirty) return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);

  useEffect(() => {
    if (dirty && editBase && draft) {
      saveStoredDraft(storageKey, { base: editBase, draft, resetKeys: [...resetKeys] });
    } else if (!dirty) {
      clearStoredDraft(storageKey);
    }
  }, [dirty, draft, editBase, resetKeys, storageKey]);

  useEffect(() => {
    if (!shouldLoad) return;
    let cancelled = false;
    setError(null);
    setChecked(false);
    setRefreshNotice(null);
    readComparison(brandId, campaignId)
      .then((next) => {
        if (cancelled) return;
        const preserveDraft = dirtyRef.current;
        setState(next);
        if (next.settings && !preserveDraft) {
          startEditing(next.settings);
        } else if (preserveDraft) {
          setRefreshNotice(next.settings?.revision !== editBaseRef.current?.revision
            ? "伺服器設定已有新版本；草稿仍以原版本保留。請取消草稿採用新版本，再重新修改。"
            : "已讀到最新資料；未覆蓋尚未儲存的設定。");
        }
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "讀取失敗。");
      });
    return () => { cancelled = true; };
  }, [brandId, campaignId, refreshToken, reload, shouldLoad, startEditing]);

  function adopt(next: ComparisonState) {
    setState(next);
    setChecked(false);
    setRefreshNotice(null);
    setRestored(false);
    clearStoredDraft(storageKey);
    if (next.settings) startEditing(next.settings);
  }

  async function confirm() {
    if (!state?.proposal || !checked) return;
    setBusy(true);
    setError(null);
    try {
      adopt(await confirmComparison(brandId, campaignId, state.proposal.fingerprint));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "確認失敗。");
    } finally {
      setBusy(false);
    }
  }

  function changeDraft(key: keyof SettingsDraft, value: string, settingKey: SettingKey) {
    setDraft((current) => current ? { ...current, [key]: value } : current);
    setResetKeys((current) => {
      if (!current.has(settingKey)) return current;
      const next = new Set(current);
      next.delete(settingKey);
      return next;
    });
  }

  function resetSetting(key: SettingKey) {
    const settings = editBase;
    if (!settings) return;
    setDraft((current) => {
      if (!current) return current;
      if (key === "window") {
        return {
          ...current,
          windowStart: settings.defaults.window.start ?? "",
          windowEnd: settings.defaults.window.end ?? "",
        };
      }
      return { ...current, [key]: String(settings.defaults[key]) };
    });
    setResetKeys((current) => new Set(current).add(key));
  }

  function cancelSettings() {
    if (!state?.settings) return;
    startEditing(state.settings);
    setError(null);
  }

  async function saveSettings() {
    const settings = editBase;
    if (!settings || !draft) return;
    if (remoteChanged) {
      setError("伺服器設定已有新版本；請先取消草稿採用最新版本，再重新修改。");
      return;
    }
    const minDays = Number(draft.min_days);
    const minConversions = Number(draft.min_conversions_each);
    const difference = Number(draft.relative_difference);
    if (!Number.isInteger(minDays) || minDays <= 0 || !Number.isInteger(minConversions) || minConversions <= 0
        || !Number.isFinite(difference) || difference <= 0 || difference > 1) {
      setError("最少天數與轉換數須為正整數；差異門檻須大於 0 且不超過 1。");
      return;
    }
    const overrides: ComparisonOverrides = { ...settings.overrides };
    for (const key of resetKeys) delete overrides[key];
    if (!resetKeys.has("min_days") && draft.min_days !== String(settings.effective.min_days)) overrides.min_days = minDays;
    if (!resetKeys.has("min_conversions_each") && draft.min_conversions_each !== String(settings.effective.min_conversions_each)) {
      overrides.min_conversions_each = minConversions;
    }
    if (!resetKeys.has("relative_difference") && draft.relative_difference !== String(settings.effective.relative_difference)) {
      overrides.relative_difference = difference;
    }
    if (!resetKeys.has("window") && (draft.windowStart !== (settings.effective.window.start ?? "")
        || draft.windowEnd !== (settings.effective.window.end ?? ""))) {
      overrides.window = { start: draft.windowStart, end: draft.windowEnd };
    }
    setBusy(true);
    setError(null);
    try {
      adopt(await saveComparisonSettings(brandId, campaignId, settings.revision, overrides));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "儲存失敗，已保留輸入。");
    } finally {
      setBusy(false);
    }
  }

  const proposal = state?.proposal;
  const summary = restored
    ? "已恢復未儲存的比較設定草稿；展開後確認最新版本。"
    : dirty
      ? "有未儲存的比較設定；展開後可繼續編輯。"
      : state?.confirmed
        ? `${state.stale ? "原確認已過期" : "已確認"}；目前判讀：${state.result.verdict}`
        : hasSavedComparison && !state
      ? error ? "已保存的比較目前讀取失敗；展開後可重試。" : "正在讀取已保存的比較狀態…"
        : "需要時再使用，不影響成效整理、結案或其他流程。";

  return (
    <section className="flex flex-col gap-2" aria-label="素材比較（選用）">
      <p className="text-sm text-muted-foreground">{summary}</p>
      <Disclosure label="素材比較（選用）" open={open} onOpenChange={setOpen}>
        <div className="flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">
            這是觀察性比較；打開只會讀取提案，不會確認、改預算、產生素材或對外投放。
          </p>
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          {restored && <p role="status" className="text-sm text-warning">
            已恢復未儲存草稿；草稿保留原始設定版本，不會自動覆蓋伺服器新值。
          </p>}
          {refreshNotice && <p role="status" className="text-sm text-warning">{refreshNotice}</p>}
          {!state && !error && <p role="status">讀取比較提案中…</p>}
          {state?.stale && <p role="status" className="text-sm text-warning">
            原確認已過期：條件、素材或設定有變更；原紀錄保留，重新核對後才能確認新提案。
          </p>}
          {state?.missing && <div className="flex flex-col items-start gap-2">
            <p className="text-sm">{state.missing}</p>
            <Button variant="outline" onClick={onViewPlan}>前往投放結構補對照</Button>
          </div>}
          {proposal && <>
            <div className="surface p-3 flex flex-col gap-3">
              <p className="text-sm font-medium">{proposal.hypothesis}</p>
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {proposal.variants.map((variant, index) => <div key={variant.ad_id} className="rounded-md border border-border p-3 text-sm">
                  <span className="font-medium">{index === 0 ? "A 對照" : "B 比較"}：{variant.name}</span>
                  <p>唯一變因「{proposal.variable}」：{variant.value}</p>
                </div>)}
              </div>
              <p className="text-sm">觀察期間：{proposal.window.start} ～ {proposal.window.end}；指標：{proposal.metric_label}。</p>
              <p className="text-sm">共同條件：{proposal.shared.group}／{proposal.shared.audience}／{proposal.shared.channel}；每日預算 {proposal.shared.daily_budget.toLocaleString()}。</p>
              <div className="rounded-md bg-muted p-3 text-sm">
                <p className="font-medium">結果：{state.result.verdict}</p>
                <p>{state.result.reason}</p>
                {state.result.values.map((value) => <p key={value.ad_id}>
                  {value.name}：{value.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </p>)}
              </div>
            </div>
            {(!state.confirmed || state.stale) && !state.closed && <div className="flex flex-col items-start gap-2">
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={checked} disabled={busy}
                  onChange={(event) => setChecked(event.target.checked)} />
                我已逐一核對：A 與 B 使用實際選定素材，且受眾、平台、預算與期間相同；只有「{proposal.variable}」不同。
              </label>
              {dirty && <p className="text-xs text-warning">請先儲存或取消進階判讀設定，再確認比較計畫。</p>}
              <Button disabled={!checked || busy || dirty} onClick={() => void confirm()}>
                {busy ? "確認中…" : "確認這份比較計畫"}
              </Button>
            </div>}
          </>}
          {editBase && draft && <SettingsEditor settings={editBase} draft={draft}
            resetKeys={resetKeys} closed={state?.closed ?? false} busy={busy} dirty={dirty}
            remoteChanged={remoteChanged}
            onChange={changeDraft} onReset={resetSetting} onCancel={cancelSettings}
            onSave={() => void saveSettings()} />}
          {state?.confirmed && <details>
            <summary className="cursor-pointer text-sm">公式、識別碼與完整確認紀錄{state.stale ? "（已過期）" : ""}</summary>
            <div className="mt-2 flex flex-col gap-1 text-xs text-muted-foreground">
              <p>{state.confirmed.hypothesis}</p>
              <p>提案指紋：<code className="break-all">{state.confirmed.fingerprint}</code></p>
              {state.confirmed.variants.map((variant) => <p key={variant.ad_id}>{variant.name}：<code>{variant.ad_id}</code></p>)}
              <p>{state.confirmed.confirmed_at} · {state.confirmed.confirmed_by}</p>
              <p>{state.confirmed.timing === "retrospective"
                ? "已有成效後才確認：事後觀察，不是事前實驗。"
                : "尚無回收資料時確認；不代表已完成隨機分流。"}</p>
              <p>{state.confirmed.limitation}</p>
            </div>
          </details>}
          {state?.simulation && <p className="text-sm font-medium">隔離模擬，非市場實證。</p>}
          <Button variant="ghost" className="self-start" disabled={busy}
            onClick={() => setReload((current) => current + 1)}>重新讀取比較提案</Button>
        </div>
      </Disclosure>
    </section>
  );
}

function SettingsEditor({ settings, draft, resetKeys, closed, busy, dirty, remoteChanged, onChange, onReset, onCancel, onSave }: {
  settings: ComparisonSettings;
  draft: SettingsDraft;
  resetKeys: Set<SettingKey>;
  closed: boolean;
  busy: boolean;
  dirty: boolean;
  remoteChanged: boolean;
  onChange: (key: keyof SettingsDraft, value: string, settingKey: SettingKey) => void;
  onReset: (key: SettingKey) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  const source = (key: SettingKey) => resetKeys.has(key)
    ? "待恢復系統預設"
    : settings.customized.includes(key) ? "已自訂" : "系統預設";
  return <div className="flex flex-col gap-2">
    <div className="rounded-md bg-muted p-3">
      <h4 className="text-sm font-medium">比較設定</h4>
      <p className="text-xs text-muted-foreground">
        生效值：至少 {settings.effective.min_days} 天、每則 {settings.effective.min_conversions_each} 次轉換、
        相對差異 {(settings.effective.relative_difference * 100).toLocaleString()}%；
        {settings.effective.window.start ?? "未設定"} ～ {settings.effective.window.end ?? "未設定"}。
      </p>
      <p className="text-xs text-muted-foreground">作用範圍：這個 Campaign；版本 {settings.revision}；
        {settings.customized.length ? `已自訂 ${settings.customized.length} 項` : "全部使用系統預設"}{dirty && "；有未儲存變更"}。
      </p>
      {closed && <p className="text-xs text-warning">活動已結案，設定唯讀。</p>}
      {remoteChanged && <p className="text-xs text-warning">伺服器已有新版本；目前草稿不能直接儲存。</p>}
    </div>
    <Disclosure label="進階判讀設定">
      <div className="flex flex-col gap-3">
    <SettingRow label="最少觀察天數" source={source("min_days")} disabled={closed || busy} canReset={settings.customized.includes("min_days") || resetKeys.has("min_days")}
      onReset={() => onReset("min_days")}>
      <Input aria-label="最少觀察天數" type="number" min="1" step="1" value={draft.min_days}
        disabled={closed || busy} onChange={(event) => onChange("min_days", event.target.value, "min_days")} />
    </SettingRow>
    <SettingRow label="每則最少轉換數" source={source("min_conversions_each")} disabled={closed || busy} canReset={settings.customized.includes("min_conversions_each") || resetKeys.has("min_conversions_each")}
      onReset={() => onReset("min_conversions_each")}>
      <Input aria-label="每則最少轉換數" type="number" min="1" step="1" value={draft.min_conversions_each}
        disabled={closed || busy} onChange={(event) => onChange("min_conversions_each", event.target.value, "min_conversions_each")} />
    </SettingRow>
    <SettingRow label="相對差異門檻" source={source("relative_difference")} disabled={closed || busy} canReset={settings.customized.includes("relative_difference") || resetKeys.has("relative_difference")}
      onReset={() => onReset("relative_difference")}>
      <Input aria-label="相對差異門檻" type="number" min="0.01" max="1" step="0.01" value={draft.relative_difference}
        disabled={closed || busy} onChange={(event) => onChange("relative_difference", event.target.value, "relative_difference")} />
      <span className="text-xs text-muted-foreground">0.1 代表 10%</span>
    </SettingRow>
    <SettingRow label="觀察期間" source={source("window")} disabled={closed || busy} canReset={settings.customized.includes("window") || resetKeys.has("window")}
      onReset={() => onReset("window")}>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Input aria-label="觀察開始日" type="date" value={draft.windowStart} disabled={closed || busy}
          onChange={(event) => onChange("windowStart", event.target.value, "window")} />
        <Input aria-label="觀察結束日" type="date" value={draft.windowEnd} disabled={closed || busy}
          onChange={(event) => onChange("windowEnd", event.target.value, "window")} />
      </div>
    </SettingRow>
    {dirty && !closed && <div className="flex flex-wrap gap-2">
      <Button disabled={busy || remoteChanged} onClick={onSave}>{busy ? "儲存中…" : "儲存比較設定"}</Button>
      <Button variant="outline" disabled={busy} onClick={onCancel}>取消設定變更</Button>
    </div>}
      </div>
    </Disclosure>
  </div>;
}

function SettingRow({ label, source, canReset, disabled = false, onReset, children }: {
  label: string;
  source: string;
  canReset: boolean;
  onReset: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return <div className="grid grid-cols-1 gap-2 rounded-md border border-border p-3 md:grid-cols-[minmax(10rem,0.7fr)_minmax(0,1fr)_auto] md:items-center">
    <div>
      <p className="text-sm font-medium">{label}</p>
      <p className="text-xs text-muted-foreground">來源：{source}</p>
    </div>
    <div>{children}</div>
    <Button type="button" variant="ghost" size="sm" disabled={disabled || !canReset} onClick={onReset}>恢復此項預設</Button>
  </div>;
}
