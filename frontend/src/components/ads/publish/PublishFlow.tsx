import type { ReactNode } from "react";
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

/** `pubHead()`: step dots (earlier steps link back), the campaign chip with 首次上架・N 項（・第 V 版）, title, purpose. */
export function PublishHead({ brandId, campaignId, current, name, view, title, purpose, aside }: {
  brandId: string; campaignId: string; current: number; name: string; view: LaunchView; title: string; purpose: string; aside?: ReactNode;
}) {
  const steps: FlowStep[] = URL_STEPS.map((s, i) => ({ label: s.label, to: i < current ? publishPath(brandId, campaignId, s.key) : undefined }));
  const version = view.version && view.version > 1 ? `・第 ${view.version} 版` : "";
  return (
    <FlowHeader steps={steps} current={current} title={title} purpose={purpose} aside={aside}
      context={<><CampaignChip objective="other" name={name} /><span>首次上架・{view.items.length} 項{version}</span></>} />
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
