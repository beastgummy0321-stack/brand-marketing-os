import { useEffect, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageTabs } from "@/components/layout/PageTabs";
import { EmptyState } from "@/components/layout/EmptyState";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";

type WorkspaceTab = "overview" | "strategy" | "structure" | "assets" | "performance";

const TABS: { value: WorkspaceTab; label: string }[] = [
  { value: "overview", label: "總覽" },
  { value: "strategy", label: "策略" },
  { value: "structure", label: "投放結構" },
  { value: "assets", label: "素材" },
  { value: "performance", label: "成效" },
];

/** Campaign 五分頁工作區的占位骨架（F03-I13）：路由、麵包屑、分頁殼先立好，內容留給
 * F03-I14——那張票整支換掉這個檔案，這裡不預先蓋任何一個分頁的內容，避免半成品落地。 */
export function CampaignWorkspacePlaceholder({
  brandId,
  campaignId,
}: {
  brandId: string;
  campaignId: string;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation() as { state?: { parseWarning?: string } };
  const tabParam = (searchParams.get("tab") as WorkspaceTab | null) ?? "overview";
  const tab = TABS.some((t) => t.value === tabParam) ? tabParam : "overview";

  const [state, setState] = useState<
    { status: "loading" } | { status: "error"; message: string } | { status: "ready"; campaign: CampaignDetail }
  >({ status: "loading" });

  useEffect(() => {
    setState({ status: "loading" });
    getCampaign(brandId, campaignId)
      .then((campaign) => setState({ status: "ready", campaign }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取 Campaign 失敗，請稍後再試。",
        }),
      );
  }, [brandId, campaignId]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={state.status === "ready" ? state.campaign.name : "Campaign"}
        description={state.status === "ready" ? state.campaign.goal_text : undefined}
      />
      {location.state?.parseWarning && (
        <p className="text-sm text-warning">{location.state.parseWarning}</p>
      )}
      <PageTabs items={TABS} value={tab} onChange={(v) => setSearchParams({ tab: v })} />
      {state.status === "error" ? (
        <EmptyState title="讀取失敗" description={state.message} />
      ) : (
        <div className="surface">
          <div className="surface-body py-10 text-center text-sm text-muted-foreground">
            {state.status === "loading" ? "讀取中…" : "這個分頁的內容還沒做（F03-I14 之後的票補上）。"}
          </div>
        </div>
      )}
    </div>
  );
}
