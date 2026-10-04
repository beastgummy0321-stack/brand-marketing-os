import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { getPublish, publishCampaign, type CampaignDetail } from "@/lib/adsApi";
import type { MonthlyBudget } from "@/lib/adsChangeApi";
import type { LaunchMonthBudget, LaunchView } from "@/lib/adsLaunchApi";
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

/** The cap tile follows the campaign's one cap (own cap, or the break-even line standing in); without the campaign
 * read it falls back to the launch summary's own cap. */
function capTile(campaign: CampaignDetail | null, ownCap: number | null) {
  const purchase = !campaign || campaign.cap.result_kind === "purchase";
  const label = purchase ? "每賣一筆的上限" : `每次${campaign.cap.result_label}的上限`;
  const who = campaign ? campaign.name.split("・")[0] || campaign.name : null;
  const value = campaign ? campaign.cap.value : ownCap;
  const basis = campaign ? campaign.cap.basis : ownCap === null ? null : "own";
  if (value === null || basis === null) {
    return { label, value: "沒設上限", unknown: true, note: "還沒設上限，上架後先不打「划算／太貴」的分數，設好就會開始打" };
  }
  const amount = formatAmount(value) ?? "";
  const note = basis === "break_even" ? `${who ?? ""}暫用打平線 ${amount}` : `${who ?? ""}的上限 ${amount}`;
  return { label, value: `${amount} 元`, unknown: false, note };
}

/** F41-I05: the launch view's month block handed to the month-budget card as it is — the backend already gives the
 * month before this launch, and the card draws `extra` on top (as on the add-budget page). The block arrives with the
 * list, so the read is always settled. */
function monthRead(block: LaunchMonthBudget): ApiRead<MonthlyBudget | null> {
  return { status: "ready", data: block, error: null, reload: () => {} };
}

export function PublishList({ brandId, campaignId, name, campaign, campaignFailed, onCampaignRetry, onCampaignSaved, view, onApproved }: {
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
}) {
  const approved = view.step !== "list";
  const { summary: s } = view;
  // The approval hash is read with the list, and again after every settings save — the launch settings and 「各廣告組
  // 的其他設定」 alike (F47-I06, Q5) — so the approval freezes what is on screen (a save changes the launch content).
  const [hashSeq, setHashSeq] = useState(0);
  const hashRead = useApiRead(
    () => (approved ? Promise.resolve(null) : getPublish(brandId, campaignId, "manual").then((r) => r.describe.content_hash ?? null)),
    [brandId, campaignId, approved, hashSeq],
  );
  const [settingsBlocker, setSettingsBlocker] = useState<string | null>("投放設定還在讀取");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hash = hashRead.status === "ready" ? hashRead.data : null;
  const month = approved ? null : view.month_budget ?? null;
  const pageBlocker = campaignFailed ? "活動資料讀不到，先按重試"
    : settingsBlocker
    ?? (s.ads === 0 ? "還沒有任何一則廣告的素材就緒，先到素材補圖"
      : hashRead.status === "error" ? "核准內容讀不到，請重新開啟本頁"
      : !hash ? "正在取得本版核准內容" : null);
  // F41-I05: the month rule has one owner (the backend's launch preflight); its reason is printed verbatim, last.
  const monthBlocker = month?.blocker_text ?? null;
  const blocker = pageBlocker ?? monthBlocker;

  async function approve() {
    if (busy || blocker || !hash) return;
    setBusy(true); setError(null);
    try {
      // One operation per approved content: a retried click reuses it, so the server never records two approvals.
      const key = `ads-publish:${getOrgId()}:${brandId}:${campaignId}:${hash}`;
      const operation = sessionStorage.getItem(key) ?? crypto.randomUUID();
      sessionStorage.setItem(key, operation);
      await publishCampaign(brandId, campaignId, "manual", { content_hash: hash, operation_id: operation });
      onApproved();
    } catch (err) {
      // F47-I06 (Q5): when the content moved under the click (a setting saved a moment ago), the approval hash is
      // read again and the sentence says so; any other refusal keeps the server's own sentence.
      const fresh = await getPublish(brandId, campaignId, "manual").then((r) => r.describe.content_hash ?? null).catch(() => null);
      setError(fresh && fresh !== hash ? "設定剛改過，已重新讀取，請再按一次核准" : err instanceof Error ? err.message : "核准失敗，請稍後再試。");
      setHashSeq((n) => n + 1);
    } finally { setBusy(false); }
  }

  const cap = capTile(campaign, s.cap);
  const missing = view.deferred_ads.length;
  const daily = formatAmount(s.daily_total);

  return (
    <div className="flex flex-col gap-4">
      <PublishHead brandId={brandId} campaignId={campaignId} current={0} name={name} view={view} title="確認上架清單" purpose="核准後照清單到平台建" />
      <section aria-label="上架摘要" className="surface grid grid-cols-4 px-[22px] py-5">
        <Tile label="要建的東西" value={`${s.campaigns + s.groups + s.ads} 項`} note={`活動 ${s.campaigns}・廣告組 ${s.groups}・廣告 ${s.ads}`} />
        <Tile label="每日預算合計" value={daily ?? "未設定"} unknown={daily === null} note={periodText(s.start, s.end)} />
        <Tile label={cap.label} value={cap.value} unknown={cap.unknown} note={cap.note} />
        <Tile label="素材" value={`${s.slots_ready}／${s.slots_total}`}
          note={missing ? `缺圖的那 ${missing} 則先不建立，不會花到錢；補上圖後再加上去` : "都齊了"} />
      </section>

      {month && (
        <BudgetFitCard read={monthRead(month)} month={month.month} extra={month.extra} premiseChanged={false} busy={false}
          onRecheck={() => {}} budgetHref={monthlyBudgetHref(brandId)}
          launch={{ strategyHref: `${campaignPath(brandId, campaignId)}?tab=strategy`, extraBasis: month.extra_basis ?? null }} />
      )}

      {campaign ? (
        <LaunchSettingsCard brandId={brandId} campaign={campaign} locked={approved}
          onSaved={() => setHashSeq((n) => n + 1)} onBlockerChange={setSettingsBlocker}
          onCampaignSaved={(saved) => { onCampaignSaved(saved); setHashSeq((n) => n + 1); }} />
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
      </section>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {approved ? (
        <ActionBar back={{ label: "素材", to: `${campaignPath(brandId, campaignId)}?tab=assets` }}>
          <Button asChild><Link to={publishPath(brandId, campaignId, "platform")}>到平台完成 →</Link></Button>
        </ActionBar>
      ) : (
        <ActionBar back={{ label: "素材", to: `${campaignPath(brandId, campaignId)}?tab=assets` }}
          exit={{ label: "先不要，回投放中心", to: `/brands/${encodeURIComponent(brandId)}/ads` }}
          hint={blocker === null ? "核准不會改動平台" : pageBlocker ?? undefined}>
          {pageBlocker === null && monthBlocker && (
            <span role="status" className="inline-flex items-center gap-1.5 text-xs font-medium text-warning">⚠ {monthBlocker}</span>
          )}
          <Button disabled={busy || blocker !== null} onClick={() => void approve()}>{busy ? "核准中…" : "核准上架清單 →"}</Button>
        </ActionBar>
      )}
    </div>
  );
}
