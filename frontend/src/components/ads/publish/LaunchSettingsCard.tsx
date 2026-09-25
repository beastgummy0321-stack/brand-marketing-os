import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import type { CampaignDetail } from "@/lib/adsApi";
import {
  getLaunchSettings, saveLaunchSettings,
  type LaunchSettingsError, type LaunchSettingsValues, type LaunchSettingsView, type PlacementPosition,
} from "@/lib/adsLaunchSettingsApi";
import { useApiRead } from "@/lib/useApiRead";
import { cn } from "@/lib/utils";
import { ManualSettings } from "../ManualSettings";
import { Disclosure, ReadFailed, Segmented, SettingField, SettingsGrid } from "../patterns";

/** F29-I16 list stage (prototype v10 `setCard()` inside `pubList()`, hash `pub/fall/list`): the launch settings every
 * ad set uses, as choice fields. Each field carries its one plain note line and 「建議」 while it still holds the
 * program-recommended value (「你改的」 once changed). A change is saved at once (UTM and a typed pixel ID after a
 * short pause); a failed save keeps the edit on screen with 重試. UTM and the per-ad-set free-text fields sit in
 * 「進階設定」. After approval the card is read only. Nothing here writes to an ad platform. */

type Values = LaunchSettingsValues;
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const SELECT = "h-10 w-full rounded-lg border border-input bg-card px-3 text-sm focus:border-primary focus:outline-none focus:ring-[3px] focus:ring-accent disabled:bg-muted disabled:text-muted-foreground";

// The live UTM check (the API applies the same rule and blocks approval on it).
const UTM = /^utm_[a-z_]+=[^\s&=]+(&utm_[a-z_]+=[^\s&=]+)*$/;
const utmValid = (v: string) => UTM.test(v.trim()) && /(^|&)utm_source=/.test(v.trim());

/** The header's short words per API error code (the full message stays at the field). */
const SHORT: Record<LaunchSettingsError["code"], string> = {
  utm_format: "UTM 格式不對", utm_source_missing: "UTM 格式不對", age_range: "年齡範圍不對",
  countries_empty: "地區至少選一個", positions_empty: "手動版位至少選一個", pixel_unknown: "像素不在帳號的清單裡",
};

export function LaunchSettingsCard({ brandId, campaign, locked, onSaved, onCampaignSaved, onBlockerChange }: {
  brandId: string;
  campaign: Pick<CampaignDetail, "id" | "status" | "manual_handoff">;
  /** The launch is approved: every field is read only. */
  locked: boolean;
  /** A save landed (the launch content, and so its approval hash, changed). */
  onSaved: () => void;
  onCampaignSaved: (campaign: CampaignDetail) => void;
  /** What keeps 核准上架清單 disabled right now, or null. */
  onBlockerChange?: (blocker: string | null) => void;
}) {
  const { scope } = useWorkspace();
  const read = useApiRead((signal) => getLaunchSettings(brandId, campaign.id, signal), [brandId, campaign.id]);
  const [view, setView] = useState<LaunchSettingsView | null>(null);
  const [draft, setDraft] = useState<Values | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const latest = useRef<Values | null>(null);
  const inFlight = useRef(false);
  const again = useRef(false);
  const timer = useRef<number | undefined>(undefined);
  const alive = useRef(true);
  const saved = useRef(onSaved);
  saved.current = onSaved;
  useEffect(() => { alive.current = true; return () => { alive.current = false; window.clearTimeout(timer.current); }; }, []);

  useEffect(() => {
    if (read.status !== "ready") return;
    setView(read.data); setDraft(read.data.values); latest.current = read.data.values; setSaveError(null);
  }, [read.status, read.data]);

  async function flush() {
    window.clearTimeout(timer.current);
    const sent = latest.current;
    if (!sent) return;
    if (inFlight.current) { again.current = true; return; }
    inFlight.current = true; setSaving(true); setSaveError(null);
    try {
      const next = await saveLaunchSettings(brandId, campaign.id, sent);
      if (!alive.current) return;
      setView(next);
      if (latest.current === sent) { latest.current = next.values; setDraft(next.values); }
      saved.current();
    } catch (err) {
      if (alive.current && latest.current === sent) setSaveError(err instanceof Error ? err.message : "儲存失敗。");
    } finally {
      inFlight.current = false;
      if (alive.current) {
        if (again.current && latest.current !== sent) { again.current = false; void flush(); }
        else { again.current = false; setSaving(false); }
      }
    }
  }

  function change(next: Values, delay = 0) {
    setDraft(next); latest.current = next;
    window.clearTimeout(timer.current);
    if (delay) timer.current = window.setTimeout(() => void flush(), delay);
    else void flush();
  }

  const pending = Boolean(view && draft && draft !== view.values);
  const utmBad = draft ? !utmValid(draft.utm) : false;
  const serverErrors = (view?.errors ?? []).filter((e) => e.field !== "utm");
  const headerError = utmBad ? "UTM 格式不對" : serverErrors[0] ? SHORT[serverErrors[0].code] : null;
  const blocker = read.status === "error" ? "投放設定讀不到，先按重試"
    : !view || !draft ? "投放設定還在讀取"
    : headerError ? `${headerError}，先在「投放設定」改好`
    : saveError ? "投放設定還沒存好，先按重試"
    : pending || saving ? "投放設定還在儲存" : null;
  const report = useRef(onBlockerChange);
  report.current = onBlockerChange;
  useEffect(() => { report.current?.(blocker); }, [blocker]);

  const header = (right?: string, tone?: "error") => (
    <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-base font-semibold">投放設定</h2>
      {right && <span className={cn("text-sm", tone === "error" ? "text-danger" : "text-muted-foreground")}>{right}</span>}
    </div>
  );

  if (read.status === "error") {
    return <section aria-label="投放設定" className="surface px-[22px] py-5">{header()}
      <ReadFailed what={`投放設定讀不到：${read.error}。先不要核准，重試後再看一次。`} onRetry={read.reload} /></section>;
  }
  if (!view || !draft) {
    return <section aria-label="投放設定" className="surface px-[22px] py-5">{header()}<p role="status" className="text-sm text-muted-foreground">讀取投放設定…</p></section>;
  }

  const { options: o, recommended: r } = view;
  const tag = (mine: unknown, rec: unknown) => (same(mine, rec) ? "recommended" as const : "edited" as const);
  const rec = (isRec: boolean) => (isRec ? "（建議）" : "");
  const nMine = (["optimization_event", "bid_strategy", "placement", "audience", "pixel_id"] as const).filter((k) => !same(draft[k], r[k])).length;
  const right = locked ? "核准後已定下來；想改，改完再核准一次"
    : headerError ?? (nMine ? `你改了 ${nMine} 項・每個廣告組都用這組` : "每個廣告組都用這組・都是建議值");
  const audience = (patch: Partial<Values["audience"]>) => change({ ...draft, audience: { ...draft.audience, ...patch } });
  const positionsError = serverErrors.find((e) => e.field === "placement.positions");
  const pixelError = serverErrors.find((e) => e.field === "pixel_id");
  const pending_count = campaign.manual_handoff?.pending_count ?? 0;
  const foldLabel = `進階設定${utmBad ? "・UTM 格式不對" : ""}${pending_count ? `・${pending_count} 組設定待補` : ""}`;

  return (
    <section aria-label="投放設定" data-slot="launch-settings-card" className="surface px-[22px] py-5">
      {header(right, !locked && headerError ? "error" : undefined)}
      <fieldset disabled={locked} className="contents">
        <SettingsGrid>
          <SettingField label="優化事件" htmlFor="set-optimization_event" tag={tag(draft.optimization_event, r.optimization_event)}
            note={o.optimization_event.find((x) => x.value === draft.optimization_event)?.note}>
            <select id="set-optimization_event" className={SELECT} value={draft.optimization_event}
              onChange={(e) => change({ ...draft, optimization_event: e.target.value as Values["optimization_event"] })}>
              {o.optimization_event.map((x) => <option key={x.value} value={x.value}>{x.label}{rec(x.value === r.optimization_event)}</option>)}
            </select>
          </SettingField>
          <SettingField label="出價方式" htmlFor="set-bid_strategy" tag={tag(draft.bid_strategy, r.bid_strategy)}
            note={o.bid_strategy.find((x) => x.value === draft.bid_strategy)?.note}>
            <select id="set-bid_strategy" className={SELECT} value={draft.bid_strategy}
              onChange={(e) => change({ ...draft, bid_strategy: e.target.value as Values["bid_strategy"] })}>
              {o.bid_strategy.map((x) => <option key={x.value} value={x.value}>{x.label}{rec(x.value === r.bid_strategy)}</option>)}
            </select>
          </SettingField>
          <SettingField label="版位" tag={tag(draft.placement, r.placement)} note={o.placement_modes.find((x) => x.value === draft.placement.mode)?.note}>
            <Segmented label="版位" value={draft.placement.mode}
              options={o.placement_modes.map((x) => ({ value: x.value, label: `${x.label}${rec(x.value === r.placement.mode)}` }))}
              onChange={(mode) => change({ ...draft, placement: { mode, positions: mode === "auto" ? [] : draft.placement.positions } })} />
            {draft.placement.mode === "manual" && (
              <div className="mt-2 flex flex-wrap gap-x-3.5 gap-y-1.5 text-[13px]">
                {o.positions.map((x) => (
                  <label key={x.value} className="flex items-center gap-1.5">
                    <input type="checkbox" checked={draft.placement.positions.includes(x.value)} onChange={(e) => {
                      const positions: PlacementPosition[] = e.target.checked
                        ? [...draft.placement.positions, x.value]
                        : draft.placement.positions.filter((p) => p !== x.value);
                      change({ ...draft, placement: { mode: "manual", positions } });
                    }} />{x.label}
                  </label>
                ))}
              </div>
            )}
            {positionsError && draft.placement.mode === "manual" && <p className="mt-1 text-xs text-danger">{positionsError.message}</p>}
          </SettingField>
          <SettingField label="受眾" htmlFor="set-age_min" wide tag={tag(draft.audience, r.audience)} note={o.field_notes.audience}>
            <div className="flex flex-wrap items-center gap-1.5">
              <select id="set-age_min" aria-label="最小年齡" className={cn(SELECT, "w-auto")} value={draft.audience.age_min}
                onChange={(e) => audience({ age_min: Number(e.target.value) })}>
                {o.ages.slice(0, -1).map((a) => <option key={a} value={a}>{a}{rec(a === r.audience.age_min)}</option>)}
              </select>
              <span className="text-muted-foreground">到</span>
              <select aria-label="最大年齡" className={cn(SELECT, "w-auto")} value={draft.audience.age_max}
                onChange={(e) => audience({ age_max: Number(e.target.value) })}>
                {o.ages.slice(1).map((a) => <option key={a} value={a}>{a === 65 ? "65+" : a}{rec(a === r.audience.age_max)}</option>)}
              </select>
              <span className="text-muted-foreground">歲</span>
              <select aria-label="性別" className={cn(SELECT, "w-auto")} value={draft.audience.gender}
                onChange={(e) => audience({ gender: e.target.value as Values["audience"]["gender"] })}>
                {o.genders.map((x) => <option key={x.value} value={x.value}>{x.label}{rec(x.value === r.audience.gender)}</option>)}
              </select>
              <select aria-label="地區" className={cn(SELECT, "w-auto")} value={draft.audience.countries[0] ?? ""}
                onChange={(e) => audience({ countries: e.target.value ? [e.target.value] : [] })}>
                {draft.audience.countries.length === 0 && <option value="">還沒選</option>}
                {o.countries.map((x) => <option key={x.value} value={x.value}>{x.label}{rec(r.audience.countries.includes(x.value))}</option>)}
              </select>
            </div>
            {serverErrors.filter((e) => e.field.startsWith("audience.")).map((e) => <p key={e.code} className="mt-1 text-xs text-danger">{e.message}</p>)}
          </SettingField>
          <PixelField view={view} draft={draft} tagValue={tag(draft.pixel_id, r.pixel_id)} error={pixelError?.message}
            onPick={(pixel_id) => change({ ...draft, pixel_id })} onType={(pixel_id) => change({ ...draft, pixel_id }, 700)} />
        </SettingsGrid>
      </fieldset>
      {saveError && (
        <div role="alert" className="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-danger/10 px-4 py-2.5 text-sm">
          <span className="min-w-0 flex-1">儲存失敗：{saveError}。你改的內容還在，按「重試」再存一次。</span>
          <Button size="sm" variant="outline" onClick={() => void flush()}>重試</Button>
        </div>
      )}
      {!locked && <p className="mt-3 text-sm font-semibold text-accent-foreground">都照建議就能送出；不確定的不用改</p>}
      <div className="mt-3.5">
        <Disclosure label={foldLabel}>
          <fieldset disabled={locked} className="flex min-w-0 flex-col gap-4">
            <SettingField label="UTM 追蹤參數" htmlFor="set-utm" tag={same(draft.utm, r.utm) ? null : "edited"} note={o.field_notes.utm}>
              <Input id="set-utm" value={draft.utm} spellCheck={false} autoComplete="off"
                onChange={(e) => change({ ...draft, utm: e.target.value }, 700)} onBlur={() => { if (pending) void flush(); }} />
              <p className={cn("mt-1 text-sm", utmBad ? "text-danger" : "text-success")}>
                {utmBad ? "格式不對：要像 utm_source=來源&utm_campaign=名稱，要有 utm_source，不能有空格" : "✓ 格式正確"}
              </p>
            </SettingField>
            <ManualSettings embedded draftScope={scope} brandId={brandId} campaign={campaign} onSaved={onCampaignSaved} />
          </fieldset>
        </Disclosure>
      </div>
    </section>
  );
}

/** 像素: the account's pixels as choices; when the list could not be read, its reason and a typed pixel ID (nothing
 * preselected or guessed). */
function PixelField({ view, draft, tagValue, error, onPick, onType }: {
  view: LaunchSettingsView; draft: Values; tagValue: "recommended" | "edited"; error?: string;
  onPick: (id: string | null) => void; onType: (id: string | null) => void;
}) {
  const { pixels, pixels_error, field_notes } = view.options;
  if (pixels === null) {
    return (
      <SettingField label="像素" htmlFor="set-pixel_id" tag={draft.pixel_id === null ? null : tagValue} note={field_notes.pixel_id}>
        <p className="mb-1.5 text-xs text-warning">{pixels_error ?? "像素清單讀不到。"}像素 ID 請手動填在下面。</p>
        <Input id="set-pixel_id" placeholder="貼上像素 ID" value={draft.pixel_id ?? ""} spellCheck={false} autoComplete="off"
          onChange={(e) => onType(e.target.value.trim() ? e.target.value.trim() : null)} />
        {error && <p className="mt-1 text-xs text-danger">{error}</p>}
      </SettingField>
    );
  }
  const known = draft.pixel_id === null || pixels.some((p) => p.id === draft.pixel_id);
  return (
    <SettingField label="像素" htmlFor="set-pixel_id" tag={tagValue} note={field_notes.pixel_id}>
      <select id="set-pixel_id" className={SELECT} value={draft.pixel_id ?? ""} onChange={(e) => onPick(e.target.value || null)}>
        {draft.pixel_id === null && <option value="">{pixels.length ? "還沒選" : "廣告帳號裡沒有像素"}</option>}
        {!known && <option value={draft.pixel_id!}>{draft.pixel_id}（不在清單裡）</option>}
        {pixels.map((p) => (
          <option key={p.id} value={p.id}>{p.name}（…{p.id.slice(-4)}）{p.id === view.recommended.pixel_id ? "（建議）" : ""}</option>
        ))}
      </select>
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
    </SettingField>
  );
}
