import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { getPublish, publishCampaign, type CampaignDetail } from "@/lib/adsApi";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { ApiResponseError } from "@/lib/http";
import type { MonthlyBudget } from "@/lib/adsChangeApi";
import { fetchLaunchView, type LaunchMonthBudget, type LaunchView } from "@/lib/adsLaunchApi";
import { getOrgId } from "@/lib/auth";
import { useApiRead, type ApiRead } from "@/lib/useApiRead";
import { cn } from "@/lib/utils";
import { BudgetFitCard } from "../flow/confirmParts";
import { monthlyBudgetHref } from "../MonthlyBudgetPanel";
import { ActionBar, CopyField, CopyFields, ReadFailed, TodoRow, formatAmount } from "../patterns";
import { LaunchSettingsCard } from "./LaunchSettingsCard";
import { ItemTitle, PublishHead, campaignPath, fieldText, periodText, publishPath, summaryFields } from "./PublishFlow";

/** F30-I13 step 1 (prototype v10 `pubList()`, hash `pub/fall/list`): the four summary tiles, the launch settings card
 * (F29 `LaunchSettingsCard`, read only after approval), the numbered list of what will be built and 核准上架清單. Only
 * ads whose material is ready are in the batch; the rest (`deferred_ads`) are named in the 素材 tile and go out with a
 * later version. Approval records the plan locally — nothing is written to a platform. */

function Tile({ label, value, note, unknown = false }: { label: string; value: string; note: ReactNode; unknown?: boolean }) {
  // `.kv > div`: label, one big value, one note line; composed from tokens (no kit piece draws a summary tile).
  return (
    <div className="min-w-0 border-l border-border px-5 py-0.5 first:border-l-0 first:pl-0">
      <span className="block text-xs text-muted-foreground">{label}</span>
      <b className={cn("numeric my-0.5 block font-semibold tracking-tight", unknown ? "text-lg font-medium text-muted-foreground" : "text-[22px]")}>{value}</b>
      <span className="block text-xs text-muted-foreground">{note}</span>
    </div>
  );
}

/** The cap's value and basis require the campaign read; a launch summary cannot supply its basis. */
function capTile(campaign: CampaignDetail) {
  const label = campaign.cap.result_kind === "purchase" ? "每賣一筆的上限" : `每次${campaign.cap.result_label}的上限`;
  const who = campaign.name.split("・")[0] || campaign.name;
  const {value, basis} = campaign.cap;
  if (value === null || basis === null) return {label, value: "沒設上限", unknown: true, note: "還沒設上限，上架後先不打「划算／太貴」的分數，設好就會開始打"};
  const amount = formatAmount(value) ?? "";
  return {label, value: `${amount} 元`, unknown: false, note: basis === "break_even" ? `${who}暫用打平線 ${amount}` : `${who}的上限 ${amount}`};
}

/** F41-I05: the launch view's month block handed to the month-budget card as it is — the backend already gives the
 * month before this launch, and the card draws `extra` on top (as on the add-budget page). The block arrives with the
 * list, so the read is always settled. */
function monthRead(block: LaunchMonthBudget): ApiRead<MonthlyBudget | null> {
  return { status: "ready", data: block, error: null, reload: () => {} };
}

export function PublishList(props: Parameters<typeof PublishListBody>[0]) {
  const { scope } = useWorkspace();
  return <PublishListBody key={JSON.stringify([scope, props.brandId, props.campaignId])} {...props} />;
}

function PublishListBody({ brandId, campaignId, name, campaign, campaignFailed, onCampaignRetry, onCampaignSaved, view: initialView, onApproved, pendingReason }: {
  brandId: string;
  campaignId: string;
  name: string;
  campaign: CampaignDetail | null;
  /** The campaign read failed: the settings card cannot be drawn (and approval waits). */
  campaignFailed: string | null;
  onCampaignRetry: () => void;
  onCampaignSaved: (campaign: CampaignDetail) => void;
  view: LaunchView;
  /** The server confirmed the approval; the page reads the launch again and moves on. */
  onApproved: () => void;
  pendingReason?: string | null;
}) {
  // The hash cannot move independently of the complete displayed list and effective settings.
  const initialApproved = initialView.step !== "list";
  const revisionRead = useApiRead(async (signal) => {
    if (initialApproved) return null;
    const described = (await getPublish(brandId, campaignId, "manual")).describe;
    if (signal.aborted) throw new DOMException("The old list read was aborted", "AbortError");
    const next = await fetchLaunchView(brandId, campaignId);
    if (!described.content_hash || !described.launch_settings ||
      described.content_hash !== next.content_hash ||
      JSON.stringify(described.launch_settings) !== JSON.stringify(next.launch_settings)) {
      throw new Error("清單在讀取時又改過，請重新讀取後再核准。");
    }
    return { view: next, settings: described.launch_settings, hash: described.content_hash };
  }, [brandId, campaignId, initialApproved]);
  const [lastRevision, setLastRevision] = useState<typeof revisionRead.data>(null);
  const [refreshing, setRefreshing] = useState(false);
  useEffect(() => {
    if (revisionRead.status === "ready") { setLastRevision(revisionRead.data); setRefreshing(false); }
  }, [revisionRead.status, revisionRead.data]);
  const revision = revisionRead.data ?? lastRevision;
  const view = revision?.view ?? initialView;
  const approved = view.step !== "list";
  const { summary: s } = view;
  const refresh = () => { setRefreshing(true); revisionRead.reload(); };
  const pendingWrite = useRef(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const [refusedHash, setRefusedHash] = useState<string | null>(null);
  const hash = !refreshing && revisionRead.status === "ready" ? revision?.hash ?? null : null;
  const [settingsBlocker, setSettingsBlocker] = useState<string | null>("投放設定還在讀取");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (refusedHash && revisionRead.status === "ready" && revision && revision.hash !== refusedHash) {
      setError("設定剛改過，已重新讀取，請再按一次核准");
      setRefusedHash(null);
    }
  }, [refusedHash, revisionRead.status, revision]);
  const month = approved ? null : view.month_budget ?? null;
  const pageBlocker = campaignFailed ? "活動資料讀不到，先按重試"
    : pendingReason ?? settingsBlocker
    ?? (s.ads === 0 ? "還沒有任何一則廣告的素材就緒，先到素材補圖"
      : revisionRead.status === "error" ? "核准內容讀不到，先按重試"
      : !hash ? "正在取得本版核准內容" : null);
  // F41-I05: the month rule has one owner (the backend's launch preflight); its reason is printed verbatim, last.
  const monthBlocker = month?.blocker_text ?? null;
  const blocker = pageBlocker ?? monthBlocker;

  async function approve() {
    if (pendingWrite.current || busy || blocker || !hash) return;
    pendingWrite.current = true;
    setBusy(true); setError(null);
    try {
      // One operation per approved content: a retried click reuses it, so the server never records two approvals.
      const key = `ads-publish:${getOrgId()}:${brandId}:${campaignId}:${hash}`;
      const operation = sessionStorage.getItem(key) ?? crypto.randomUUID();
      sessionStorage.setItem(key, operation);
      await publishCampaign(brandId, campaignId, "manual", { content_hash: hash, operation_id: operation });
      if (alive.current) onApproved();
    } catch (err) {
      // F47-I06 (Q5): when the content moved under the click (a setting saved a moment ago), the approval hash is
      // read again and the sentence says so; any other refusal keeps the server's own sentence.
      if (!alive.current) return;
      setError(err instanceof Error ? err.message : "核准失敗，請稍後再試。");
      if (err instanceof ApiResponseError && err.status === 409) setRefusedHash(hash);
      onCampaignRetry(); refresh();
    } finally { pendingWrite.current = false; if (alive.current) setBusy(false); }
  }

  const cap = campaign ? capTile(campaign) : null;
  const missing = view.deferred_ads.length;
  const daily = formatAmount(s.daily_total);
  const confirms = view.approval_confirms ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PublishHead brandId={brandId} campaignId={campaignId} current={0} name={name} view={view} title="確認上架清單" purpose="核准後照清單到平台建" />
      <section aria-label="上架摘要" className="surface grid grid-cols-4 px-[22px] py-5">
        <Tile label="要建的東西" value={`${s.campaigns + s.groups + s.ads} 項`} note={`活動 ${s.campaigns}・廣告組 ${s.groups}・廣告 ${s.ads}`} />
        <Tile label="每日預算合計" value={daily ?? "未設定"} unknown={daily === null} note={periodText(s.start, s.end)} />
        {cap ? <Tile label={cap.label} value={cap.value} unknown={cap.unknown} note={cap.note} /> : <div className="min-w-0 border-l border-border px-5 py-0.5" aria-label="每筆上限">
          {campaignFailed ? <ReadFailed what={`上限資料讀不到：${campaignFailed}`} onRetry={onCampaignRetry} /> : <p role="status" className="text-sm text-muted-foreground">讀取上限…</p>}
        </div>}
        <Tile label="素材" value={`${s.slots_ready}／${s.slots_total}`}
          note={missing ? `缺圖的那 ${missing} 則先不建立，不會花到錢；補上圖後再加上去` : "都齊了"} />
      </section>

      {month && (
        <BudgetFitCard read={monthRead(month)} month={month.month} extra={month.extra} premiseChanged={false} busy={false}
          onRecheck={() => {}} budgetHref={monthlyBudgetHref(brandId)} returnTo={publishPath(brandId, campaignId, "list")}
          launch={{ strategyHref: `${campaignPath(brandId, campaignId)}?tab=strategy`, extraBasis: month.extra_basis ?? null }} />
      )}

      {campaign ? (
        <LaunchSettingsCard brandId={brandId} campaign={campaign} locked={approved}
          revision={revision ? { hash: revision.hash, values: revision.settings } : undefined}
          onSaved={refresh} onBlockerChange={setSettingsBlocker}
          onCampaignSaved={(saved) => { onCampaignSaved(saved); refresh(); }} />
      ) : campaignFailed ? (
        <section aria-label="投放設定" className="surface px-[22px] py-5">
          <h2 className="mb-3.5 text-base font-semibold">投放設定</h2>
          <ReadFailed what={`活動資料讀不到：${campaignFailed}。先不要核准，重試後再看一次。`} onRetry={onCampaignRetry} />
        </section>
      ) : (
        <section aria-label="投放設定" className="surface px-[22px] py-5"><p role="status" className="text-sm text-muted-foreground">讀取投放設定…</p></section>
      )}

      <section aria-label="清單" className="surface px-[22px] py-5">
        <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold">清單</h2>
          <span className="text-xs text-muted-foreground">核准後清單就定下來；之後想改，改完再核准一次就好</span>
        </div>
        {view.items.map((item, i) => (
          <TodoRow key={item.id} no={i + 1}>
            <ItemTitle item={item} />
            <CopyFields>
              {summaryFields(item.fields.filter((f) => f.key !== "name")).map((f) => <CopyField key={f.key} label={f.label} value={fieldText(f.value)} copy={false} />)}
            </CopyFields>
          </TodoRow>
        ))}
        {/* F49 Contract B (decision 5): what no platform read can see, said once, before 核准 — approving is the
            confirmation; the readback never asks for these again. */}
        {!approved && confirms.length > 0 && (
          <p data-slot="approval-confirms" className="mt-1 border-t border-border pt-3 text-xs text-muted-foreground">
            平台讀不到這幾項，核准就代表上架時照這樣設：{confirms.map((c) => c.label).join("、")}
          </p>
        )}
      </section>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {revisionRead.status === "error" && <ReadFailed what={`核准內容讀不到：${revisionRead.error}`} onRetry={refresh} />}
      {approved ? (
        <ActionBar back={{ label: "素材", to: `${campaignPath(brandId, campaignId)}?tab=assets` }}>
          <Button asChild><Link to={publishPath(brandId, campaignId, "platform")}>到平台完成 →</Link></Button>
        </ActionBar>
      ) : (
        <ActionBar back={{ label: "素材", to: `${campaignPath(brandId, campaignId)}?tab=assets` }}
          exit={{ label: "先不要，回投放中心", to: `/brands/${encodeURIComponent(brandId)}/ads` }}
          hint={blocker === null ? "核准不會改動平台" : undefined}>
          {pageBlocker === null && monthBlocker && (
            <span role="status" className="inline-flex items-center gap-1.5 text-xs font-medium text-warning">⚠ {monthBlocker}</span>
          )}
          <Button busy={busy} disabledReason={blocker ?? undefined} onClick={() => void approve()}>{busy ? "核准中…" : "核准上架清單 →"}</Button>
        </ActionBar>
      )}
    </div>
  );
}
