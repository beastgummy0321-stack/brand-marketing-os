import type { CampaignStatus } from "@/lib/adsApi";
import type { QueueItem, QueueProposal } from "@/lib/adsTriageApi";

/** F19-I02：從 `AdsHomePage.tsx` 抽出，讓 `home/CampaignCards.tsx` 跟 `AdsHomePage.tsx` 都能讀，
 * 不必互相 import 造成循環依賴。`AdsHomePage.tsx` 原樣 re-export，`AllCampaignsPage.tsx`
 * （do_not_touch 外但這次沒有理由改）沿用同一個 import 路徑不受影響。 */
export const STATUS_LABEL: Record<CampaignStatus, string> = {
  draft: "草稿",
  ready: "待發布",
  live: "投放中",
  ended: "已結束",
  closed: "已結案",
};

export const STATUS_TONE: Record<CampaignStatus, "secondary" | "default" | "outline"> = {
  draft: "secondary",
  ready: "outline",
  live: "default",
  ended: "outline",
  closed: "secondary",
};

/** F22-I05: what a `stop_loss` row／ad leads to, driven entirely by `item.proposal`
 * (feature Decisions "Queue row state"; routes and labels from the issue's rule details).
 * Shared by `home/QueueRow.tsx` and `detail/CampaignDetailPage.tsx` so both surfaces agree —
 * the pages at these routes are built by other issues in this feature, this only routes there. */
export interface ProposalAction {
  label: string;
  href: string;
  /** confirmed／rejected／deferred: ghost button, and the row no longer counts as open. */
  done: boolean;
}

const proposePath = (brandId: string, campaignId: string, entityId: string) =>
  `/brands/${brandId}/ads/campaigns/${campaignId}/propose/pause/${entityId}`;
const changePath = (
  brandId: string, campaignId: string, setId: string, step: "confirm" | "handoff" | "verify",
) => `/brands/${brandId}/ads/campaigns/${campaignId}/changes/${setId}/${step}`;
const workspacePath = (brandId: string, campaignId: string) => `/brands/${brandId}/ads/campaigns/${campaignId}`;

// `revisit_at` 是「always a timezone-carrying ISO instant」（feature Decisions）——瀏覽器本地
// 時區印「M/D」，不補零、不印年份（跟這頁其餘日期格式一致地簡短）。
function formatRevisitLabel(revisitAt: string): string {
  const d = new Date(revisitAt);
  return `${d.getMonth() + 1}/${d.getDate()} 重看`;
}

export function proposalAction(
  brandId: string,
  campaignId: string,
  entityId: string,
  proposal: QueueProposal | null,
): ProposalAction {
  if (proposal === null) {
    return { label: "去處理", href: proposePath(brandId, campaignId, entityId), done: false };
  }
  // multi-item 清單這批不畫單一步驟頁——導去活動工作區既有的變更清單（feature Decisions
  // "Rule details"），label 還是照 status／verification_state 算，只換連結去處。
  const stepHref = (step: "confirm" | "handoff" | "verify") =>
    proposal.multi ? workspacePath(brandId, campaignId) : changePath(brandId, campaignId, proposal.change_set_id, step);

  switch (proposal.status) {
    case "draft":
      return { label: "等你核准", href: stepHref("confirm"), done: false };
    case "rejected":
      return { label: "已拒絕", href: stepHref("confirm"), done: true };
    case "deferred":
      return {
        label: proposal.revisit_at ? formatRevisitLabel(proposal.revisit_at) : "已暫緩",
        href: stepHref("confirm"),
        done: true,
      };
    case "approved":
      switch (proposal.verification_state) {
        case "pending":
          return { label: "到平台完成", href: stepHref("handoff"), done: false };
        case "reported":
        case "unknown":
          return { label: "核對中", href: stepHref("verify"), done: false };
        case "deviated":
          return { label: "與核准不符", href: stepHref("verify"), done: false };
        case "stale":
          return { label: "需重新檢討", href: stepHref("verify"), done: false };
        case "confirmed":
          return { label: "已核對", href: stepHref("verify"), done: true };
      }
  }
}

/** F22-I05 rescope: whether a queue row still counts as "open" for the home header count
 * (`AdsHomePage.tsx`). `worse` rows have no proposal flow this batch and are never done; a
 * `stop_loss` row is done exactly when `proposalAction(...).done` is true — same rule the row's
 * own button already renders, kept in one place so the header and the button can't disagree. */
export function isQueueItemDone(item: QueueItem): boolean {
  if (item.triage.class !== "stop_loss") return false;
  if (item.brand_id === null) return false;
  return proposalAction(item.brand_id, item.triage.campaign_id, item.triage.entity_id, item.proposal).done;
}
