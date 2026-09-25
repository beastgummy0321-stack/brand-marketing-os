import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { PageTabs } from "@/components/layout/PageTabs";
import { Skeleton } from "@/components/layout/Skeleton";
import type { CampaignDetail } from "@/lib/adsApi";
import type { CampaignWorkspace } from "@/lib/adsWorkspaceApi";
import type { ApiRead } from "@/lib/useApiRead";
import { Chip, ReadFailed, StageRail, Term, formatAmount, type StageStation } from "../patterns";
import type { WorkspaceTab } from "../nextStep";

/** v10 (F30-I07) campaign workspace head (prototype `wsHead()`): breadcrumb, the campaign name, one chip row
 * (草稿 or 目標・在投 N 則, 每日, period, the campaign's one cap), the stage rail from `GET …/workspace` `stage`, and
 * the six tabs with the open-decision count on 總覽. Unknown values print nothing rather than a guess: an unknown
 * pending count shows no number (never 0), an unknown daily budget no chip. The daily budget shown is the
 * workspace's own `daily_budget` only — never next to another daily figure. */

export const WORKSPACE_TABS: { value: WorkspaceTab; label: string }[] = [
  { value: "overview", label: "總覽" },
  { value: "strategy", label: "策略" },
  { value: "structure", label: "投放結構" },
  { value: "assets", label: "素材" },
  { value: "perf", label: "成效" },
  { value: "changes", label: "變更與核對" },
];

/** Prototype `STAGES`: each station opens the tab (or page) where that stage is worked on. */
export function stageStations(brandId: string, campaignId: string): StageStation[] {
  const ws = `/brands/${brandId}/ads/campaigns/${campaignId}`;
  return [
    { key: "plan", label: "計畫", to: `${ws}?tab=strategy` },
    { key: "assets", label: "素材", to: `${ws}?tab=assets` },
    { key: "launch", label: "上架", to: `${ws}?tab=changes` },
    { key: "read", label: "判讀", to: `${ws}?tab=perf` },
    { key: "decide", label: "決策", to: `${ws}?tab=overview` },
    { key: "review", label: "回顧", to: `/brands/${brandId}/ads/month` },
  ];
}

const md = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(8, 10)}`;

/** 「09/08 – 10/08」; an imported campaign reads its platform root's dates. */
export function periodText(c: CampaignDetail): string {
  const root = c.origin === "imported" ? c.external_view?.entities.find((e) => !e.parent_native_id) : null;
  const start = root ? root.start_date : c.start_date;
  const end = root ? root.end_date : c.end_date;
  if (!start && !end) return "投放期間尚未設定";
  return `${start ? md(start) : "開始日未知"} – ${end ? md(end) : "結束日未知"}`;
}

/** Prototype `tgt(c).html`: every cap label names its campaign (caps are per campaign). */
export function CapChip({ campaign: c }: { campaign: CampaignDetail }) {
  const who = c.name.split("・")[0] || c.name;
  if (c.cap.value === null || c.cap.basis === null) return <Chip tone="warn">沒設上限</Chip>;
  const value = formatAmount(c.cap.value);
  return c.cap.basis === "break_even"
    ? <Chip tone="warn" className="max-w-[22rem]"><span className="truncate">{who}暫用</span><Term k="break_even" value={c.cap.value}>打平線</Term> {value}</Chip>
    : <Chip tone="accent" className="max-w-[22rem]"><span className="truncate">{who}的</span><Term k="cap">上限</Term> {value}</Chip>;
}

/** A draft has no platform ads yet: the workspace says so (`draft` block); before it answers, the campaign's own
 * status stands in (an imported campaign is never a draft). */
export function isDraftCampaign(c: CampaignDetail, ws: CampaignWorkspace | null): boolean {
  if (ws) return ws.draft !== null;
  return c.origin !== "imported" && (c.status === "draft" || c.status === "ready");
}

export function WorkspaceHead({ brandId, campaign: c, workspace, tab, onTab, showTabs = true }: {
  brandId: string;
  campaign: CampaignDetail | null;
  workspace: ApiRead<CampaignWorkspace>;
  tab: WorkspaceTab;
  onTab: (tab: WorkspaceTab) => void;
  /** The publish page replaces the tabs (and their bodies) while it is open. */
  showTabs?: boolean;
}) {
  const ws = workspace.status === "ready" ? workspace.data : null;
  const tabLabel = WORKSPACE_TABS.find((t) => t.value === tab)?.label ?? "總覽";
  const home = `/brands/${brandId}/ads`;
  const draft = c ? isDraftCampaign(c, ws) : false;
  const pending = ws?.pending_count ?? null;
  const items = WORKSPACE_TABS.map((t) => (t.value === "overview" && pending !== null && pending > 0 ? { ...t, count: pending } : t));

  return (
    <header className="flex flex-col">
      <Breadcrumb items={c
        ? [{ label: "投放中心", href: home }, { label: c.name, href: `${home}/campaigns/${c.id}` }, { label: tabLabel }]
        : [{ label: "投放中心", href: home }, { label: "活動" }]} />
      {c ? (
        <div className="mt-4 min-w-0">
          <h1 className="text-[26px] leading-tight font-semibold tracking-tight [overflow-wrap:anywhere]">{c.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {draft ? <Chip>草稿</Chip> : (
              // An imported objective can be a whole sentence: only it truncates, 「・在投 N 則」 always shows.
              <Chip className="max-w-[18rem] gap-0">
                <span className="min-w-0 truncate" title={c.objective || undefined}>{c.objective || "目標待確認"}</span>
                {ws && <span className="shrink-0">・在投 {ws.active_ads} 則</span>}
              </Chip>
            )}
            {ws && ws.daily_budget !== null && ws.daily_budget > 0 && <Chip>每日 {formatAmount(ws.daily_budget)}</Chip>}
            <Chip>{periodText(c)}</Chip>
            <CapChip campaign={c} />
          </div>
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-2"><Skeleton className="h-8 w-80" /><Skeleton className="h-6 w-96" /></div>
      )}
      {ws ? (
        <StageRail stations={stageStations(brandId, c?.id ?? "")} current={ws.stage.key} done={ws.stage.done} />
      ) : workspace.status === "error" ? (
        <div className="my-4"><ReadFailed what={`活動進度讀不到：${workspace.error}。其他分頁照常可用。`} onRetry={workspace.reload} /></div>
      ) : (
        <Skeleton className="mt-4 mb-[18px] h-8 w-[34rem] max-w-full" />
      )}
      {showTabs && <PageTabs items={items} value={tab} onChange={onTab} label="活動分頁" />}
    </header>
  );
}
