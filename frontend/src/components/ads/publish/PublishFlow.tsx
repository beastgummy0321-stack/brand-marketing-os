import { createContext, useContext, type ReactNode } from "react";
import type { CampaignDetail } from "@/lib/adsApi";
import type { LaunchField, LaunchItem, LaunchItemKind, LaunchItemState, LaunchStep, LaunchView } from "@/lib/adsLaunchApi";
import type { Channel } from "@/lib/adsLaunchApi";
import { formatSyncTime } from "@/lib/format";
import { CampaignChip, Chip, FlowHeader, Legend, ProgressSegments, formatAmount, type FlowStep, type SegmentState } from "../patterns";

/** F30-I13 shared pieces of the three-step publish page (prototype v10 `pubHead()`, `pubProg()`): the URL steps and
 * which of them the launch's reported step allows, the header, the item progress, and the plain text of a launch
 * field. The page itself is `PublishPage`; each step body is `PublishList` / `PublishPlatform` / `PublishVerify`.
 * Nothing here writes to a platform. */

export type PublishUrlStep = "list" | "platform" | "verify";
const URL_STEPS: { key: PublishUrlStep; label: string }[] = [
  { key: "list", label: "確認上架清單" },
  { key: "platform", label: "到平台完成" },
  { key: "verify", label: "讀回核對" },
];

export const campaignPath = (brandId: string, campaignId: string) =>
  `/brands/${encodeURIComponent(brandId)}/ads/campaigns/${encodeURIComponent(campaignId)}`;
export const publishPath = (brandId: string, campaignId: string, step: PublishUrlStep) =>
  `${campaignPath(brandId, campaignId)}/publish/${step}`;

/** The URL a reported launch step lives at: a stale launch is decided on the platform step (prototype `pubStale()`). */
export const urlOfStep = (step: LaunchStep): PublishUrlStep => (step === "stale" ? "platform" : step);

/** Steps the user may open for a reported step: every earlier step stays reachable (the list turns read only after
 * approval; verify links back to the platform), a later one is not. Anything else redirects to `urlOfStep`. */
export function allowsStep(step: LaunchStep, requested: string | undefined): requested is PublishUrlStep {
  const open: PublishUrlStep[] = step === "list" ? ["list"] : step === "verify" ? ["list", "platform", "verify"] : ["list", "platform"];
  return open.includes(requested as PublishUrlStep);
}

export const KIND_LABEL: Record<LaunchItemKind, string> = { campaign: "活動", group: "廣告組", ad: "廣告" };

/** A launch field as the page prints it: amounts through the kit formatter, an empty value as 未設定 (never 0). */
export function fieldText(value: LaunchField["value"]): string {
  if (value === null || value === "") return "未設定";
  return typeof value === "number" ? formatAmount(value) ?? "未設定" : value;
}

const md = (iso: string | null) => (iso ? `${iso.slice(5, 7)}/${iso.slice(8, 10)}` : null);
/** 「10/01 – 10/31」; an unknown end reads as such, never a guessed date. */
export function periodText(start: string | null, end: string | null): string {
  if (!start && !end) return "投放期間尚未設定";
  return `${md(start) ?? "開始日未知"} – ${md(end) ?? "結束日未知"}`;
}

/** The list's read-only field line: start and end date read as one 期間 (prototype `pubList()`); the platform step
 * keeps them apart, full dates, for pasting into the platform's date fields. */
export function summaryFields(fields: LaunchField[]): LaunchField[] {
  const start = fields.find((f) => f.key === "start_date"), end = fields.find((f) => f.key === "end_date");
  if (!start && !end) return fields;
  const period: LaunchField = { key: "period", label: "期間", value: periodText(start?.value == null ? null : String(start.value), end?.value == null ? null : String(end.value)) };
  const at = fields.findIndex((f) => f === start || f === end);
  const rest = fields.filter((f) => f !== start && f !== end);
  return [...rest.slice(0, at), period, ...rest.slice(at)];
}

export const timeText = (iso: string | null) => (iso && !Number.isNaN(new Date(iso).getTime()) ? formatSyncTime(iso) : null);

/** The platform the batch goes to: one channel key across the campaign's groups, its label from the channel list.
 * `href` is the platform's own ads manager, opened in a new tab only (the page never writes to a platform); a channel
 * without a known manager address gets no button. */
const MANAGER_URL: Record<string, string> = { meta: "https://adsmanager.facebook.com/adsmanager/manage/campaigns" };
export interface LaunchPlatform { label: string; href: string | null }
export function launchPlatform(campaign: CampaignDetail | null, channels: Channel[] | null): LaunchPlatform {
  const keys = [...new Set(campaign?.groups.map((g) => g.channel_key) ?? [])];
  const key = keys.length === 1 ? keys[0] : null;
  const label = (key && channels?.find((c) => c.key === key)?.label) || "平台";
  return { label, href: key ? MANAGER_URL[key] ?? null : null };
}

/** F47-I06: the one name of a launch, used by the page crumb and the step chip alike — a re-approved launch is
 * 「第 N 版上架」, a campaign the create filled from the previous period (any `field_sources` value `copied`) is
 * 「這一期上架」, and only a campaign with neither reads 「首次上架」 (the second period used to be called 首次上架 too).
 * Without the campaign read it says 「上架」 rather than guess. */
export function launchLabel(campaign: CampaignDetail | null, view: LaunchView | null): string {
  if (view?.version && view.version > 1) return `第 ${view.version} 版上架`;
  const sources = Object.values(campaign?.context_json?.field_sources ?? {});
  if (sources.includes("copied")) return "這一期上架";
  return campaign ? "首次上架" : "上架";
}
/** The campaign the publish page read, for `PublishHead` (provided once by `PublishPage`, so the step bodies need not
 * pass it through). */
export const PublishCampaignContext = createContext<CampaignDetail | null>(null);

/** F47-I06: a stored failed read as one sentence with its time — 「MM/DD HH:MM 讀回時讀不到：原因」; the bare reason
 * when no time was stored. The publish verify step and the manual handoff panel both print it. */
export function readFailedText(at: string | null | undefined, reason: string): string {
  return at ? `${formatSyncTime(at)} 讀回時讀不到：${reason}` : reason;
}

/** F49 Contract B: the reason an item prints. A `built` item prints the batch readback's note; an `unknown` item only
 * its coded reason (`reason_code`, one of `READBACK_REASONS`) — without a code the stored text is the check's general
 * remark, not why the item is waiting (drill 11 printed it as a failure under every item). */
export function readbackReason(item: LaunchItem): string | null {
  if (!item.reason) return null;
  if (item.state === "built") return item.reason;
  return item.state === "unknown" && item.reason_code ? item.reason : null;
}

/** `pubHead()`: step dots (earlier steps link back), the campaign chip with 〈launchLabel〉・N 項, title, purpose. */
export function PublishHead({ brandId, campaignId, current, name, view, title, purpose, aside }: {
  brandId: string; campaignId: string; current: number; name: string; view: LaunchView; title: string; purpose: string; aside?: ReactNode;
}) {
  const campaign = useContext(PublishCampaignContext);
  const steps: FlowStep[] = URL_STEPS.map((s, i) => ({ label: s.label, to: i < current ? publishPath(brandId, campaignId, s.key) : undefined }));
  return (
    <FlowHeader steps={steps} current={current} title={title} purpose={purpose} aside={aside}
      context={<><CampaignChip objective="other" name={name} /><span>{launchLabel(campaign, view)}・{view.items.length} 項</span></>} />
  );
}

/** The kind chip and the item name (bold on the list and platform steps, medium on verify), plus any chips. */
export function ItemTitle({ item, strong = true, children }: { item: LaunchItem; strong?: boolean; children?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <Chip>{KIND_LABEL[item.kind] ?? item.kind}</Chip>
      <span className={strong ? "min-w-0 font-semibold [overflow-wrap:anywhere]" : "min-w-0 font-medium [overflow-wrap:anywhere]"}>{item.name}</span>
      {children}
    </div>
  );
}

/** Items the batch readback reads: reported and not verified (`built`), or read before without an answer (`unknown`). */
export const awaitsReadback = (state: LaunchItemState) => state === "built" || state === "unknown";

const SEGMENT: Record<LaunchItemState, SegmentState> = {
  verified: "ok", built: "built", unknown: "built", mismatch: "mismatch", changed: "changed", todo: "todo",
};
// The legend names the same fills as `ProgressSegments` uses for each state.
const SWATCH: Record<"ok" | "built" | "mismatch" | "todo", string> = { ok: "bg-success", built: "bg-chart-soft", mismatch: "bg-warning/80", todo: "bg-muted" };

/** `pubProg()` inside its card: 「V／N 已核對」, the approval line, one segment per item and the legend. */
export function LaunchProgress({ view }: { view: LaunchView }) {
  const n = (states: LaunchItemState[]) => view.items.filter((i) => states.includes(i.state)).length;
  const ok = n(["verified"]), mismatch = n(["mismatch"]);
  const approved = timeText(view.approved_at);
  const label = `${ok}／${view.items.length} 已核對`;
  return (
    <section aria-label="核對進度" className="surface px-[22px] py-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold">{label}</h2>
        <span className="text-xs text-muted-foreground">第 {view.version ?? 1} 版核准{approved ? `・${approved}` : ""}</span>
      </div>
      <ProgressSegments label={label} segments={view.items.map((i) => ({ key: i.id, state: SEGMENT[i.state], title: i.name }))} />
      <Legend items={[
        { label: `已核對 ${ok}`, swatch: SWATCH.ok },
        { label: `已建好待讀回 ${n(["built", "unknown"])}`, swatch: SWATCH.built },
        ...(mismatch > 0 ? [{ label: `不符 ${mismatch}`, swatch: SWATCH.mismatch }] : []),
        { label: `待操作 ${n(["todo", "changed"])}`, swatch: SWATCH.todo },
      ]} />
    </section>
  );
}
