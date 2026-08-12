import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { Skeleton } from "@/components/layout/Skeleton";
import { TrendSparkline } from "@/components/layout/TrendSparkline";
import { formatCurrency, formatRoas } from "@/lib/format";
import {
  archiveCampaign,
  cycleLabel,
  fetchCampaignList,
  type CampaignBucket,
  type CampaignListItem,
  type InterviewSubmitResult,
} from "@/lib/campaignsApi";
import { usePagination } from "@/lib/usePagination";
import { cn } from "@/lib/utils";
import { Badge } from "./shared/Badge";
import { CampaignDeletePanel } from "./panels/CampaignDeletePanel";
import { InterviewPanel } from "./panels/InterviewPanel";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: CampaignListItem[] };

type BucketFilter = "all" | CampaignBucket;

const BUCKET_LABELS: Record<BucketFilter, string> = {
  all: "全部",
  in_progress: "進行中",
  closed: "已結案",
  archived: "已封存",
};

const BUCKET_ORDER: BucketFilter[] = ["all", "in_progress", "closed", "archived"];

/** 歷史檔期（S7 縮減，票 B4R-cockpit-pins，契約 `.scratch/grill/GRILL-B4R-performance.md`
 * 第三節）：舊版「檔期」清單降級成查歷史用的歸檔頁（R1-1：一進去就要看到的資訊已移交
 * 駕駛艙成效釘選區），主要入口改成從駕駛艙／作戰室點「查歷史檔期」次要連結進來，不再是
 * 側邊導覽的必經之路。`GRILL-B4-campaigns.md` 既有契約（`S7.1-20`）與 `GRILL-B4-warroom.md`
 * 「這次合併判斷」原樣沿用——單一清單＋狀態篩選 chips（鐵則⑥），不再另立摘要卡；本節只加
 * S7.21-23 趨勢縮圖欄。 */
export function CampaignListPage({ brandId }: { brandId: string }) {
  const navigate = useNavigate();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [bucketFilter, setBucketFilter] = useState<BucketFilter>("in_progress");
  const [deleteItem, setDeleteItem] = useState<CampaignListItem | null>(null);
  const [interviewOpen, setInterviewOpen] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [actionState, setActionState] = useState<Record<string, { saving: boolean; error: string | null }>>({});

  function load() {
    setState({ status: "loading" });
    fetchCampaignList(brandId)
      .then((items) => setState({ status: "ready", items }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, [brandId]);

  const items = state.status === "ready" ? state.items : [];
  // 清單依 start_date 由新到舊排序（S7.2：chips 預設停在進行中，第一列就是最新那期）。
  const sorted = [...items].sort((a, b) => (a.start_date < b.start_date ? 1 : -1));
  const counts: Record<BucketFilter, number> = {
    all: sorted.length,
    in_progress: sorted.filter((i) => i.bucket === "in_progress").length,
    closed: sorted.filter((i) => i.bucket === "closed").length,
    archived: sorted.filter((i) => i.bucket === "archived").length,
  };
  const filtered = bucketFilter === "all" ? sorted : sorted.filter((i) => i.bucket === bucketFilter);
  const { page, pageCount, totalCount, pageItems, goToPage, resetPage, topRef } = usePagination(filtered);

  function selectBucket(next: BucketFilter) {
    setBucketFilter(next);
    resetPage();
  }

  function setRowState(id: string, next: { saving: boolean; error: string | null }) {
    setActionState((prev) => ({ ...prev, [id]: next }));
  }

  async function toggleArchive(item: CampaignListItem) {
    setRowState(item.id, { saving: true, error: null });
    try {
      await archiveCampaign(brandId, item.id);
      setBanner(
        item.bucket === "archived"
          ? `已恢復 ${cycleLabel(item)} 這期檔期。`
          : `已封存 ${cycleLabel(item)} 這期檔期。`,
      );
      load();
    } catch (err) {
      setRowState(item.id, { saving: false, error: err instanceof Error ? err.message : "操作失敗，請稍後再試。" });
    }
  }

  function handleNewCampaign() {
    navigate(`/brands/${brandId}/campaigns/new`);
  }

  function handleInterviewSubmitted(result: InterviewSubmitResult) {
    setInterviewOpen(false);
    let message =
      result.rule_card_count === 0 && result.hypothesis_count === 0
        ? "這次沒有勾選任何項目，之後隨時可以回來補。"
        : `記下了 ${result.rule_card_count} 條想避開的方向、${result.hypothesis_count} 條想再驗證的方向。`;
    if (result.conflicts.length > 0) {
      message += "；" + result.conflicts.join("、") + " 兩邊都勾了，這幾項先沒記，之後可以回來擇一。";
    }
    setBanner(message);
  }

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  } else if (items.length === 0) {
    content = (
      <EmptyState
        title="還沒有跑過任何一期廣告"
        description="開一期廣告，系統會讀取品牌智庫的資料，準備好計畫、素材與投放設定，貼到 Meta 即可。"
        actionLabel="開新檔期"
        onAction={handleNewCampaign}
      />
    );
  } else if (filtered.length === 0) {
    content = (
      <div
        ref={topRef}
        className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground"
      >
        目前沒有{BUCKET_LABELS[bucketFilter]}的檔期
      </div>
    );
  } else {
    content = (
      <div ref={topRef} className="flex flex-col gap-3">
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">檔期</th>
                <th className="px-3 py-2 font-medium">狀態</th>
                <th className="px-3 py-2 font-medium">目標</th>
                <th className="px-3 py-2 font-medium">預算</th>
                <th className="px-3 py-2 font-medium">產品</th>
                <th className="px-3 py-2 font-medium">ROAS</th>
                <th className="px-3 py-2 font-medium">成色</th>
                <th className="px-3 py-2 font-medium">趨勢</th>
                <th className="px-3 py-2 font-medium">動作</th>
              </tr>
            </thead>
            <tbody>
              {pageItems.map((item) => {
                const row = actionState[item.id];
                return (
                  <tr key={item.id} className="border-t border-border align-top">
                    <td className="whitespace-nowrap px-3 py-2 text-foreground">
                      <Link to={`/brands/${brandId}/campaigns/${item.id}`} className="text-primary hover:underline">
                        {cycleLabel(item)}
                      </Link>
                      {item.phase_label && (
                        <span className="ml-1.5">
                          <Badge tone="warning">{item.phase_label}</Badge>
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <Badge>{item.status_label}</Badge>
                      {item.bucket === "in_progress" && item.stage_index !== null && (
                        <p className="mt-1 whitespace-nowrap text-xs text-muted-foreground">
                          第 {item.stage_index} 步／共 5 步・剩 {item.days_left} 天
                        </p>
                      )}
                    </td>
                    <td className="px-3 py-2 text-foreground">
                      {item.objective_label}
                      {item.funnel_stage_label && (
                        <span className="ml-1.5">
                          <Badge>{item.funnel_stage_label}</Badge>
                        </span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-foreground">{formatCurrency(item.budget)}</td>
                    <td className="max-w-xs px-3 py-2 text-foreground">
                      {item.product_names.length === 0 ? "整個品牌" : item.product_names.join("、")}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-foreground">
                      {item.roas === null ? "—" : formatRoas(item.roas)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">
                      {item.data_grade ? (
                        <Badge
                          tone={
                            item.verdict_kind === "danger"
                              ? "danger"
                              : item.verdict_kind === "ok"
                                ? "success"
                                : "neutral"
                          }
                        >
                          {item.data_grade.label}
                        </Badge>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">
                      {item.trend_daily_budgets ? (
                        <TrendSparkline data={item.trend_daily_budgets} />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <div className="flex flex-col items-start gap-1">
                        <button
                          type="button"
                          disabled={row?.saving}
                          onClick={() => void toggleArchive(item)}
                          className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {row?.saving ? "處理中…" : item.bucket === "archived" ? "恢復" : "封存"}
                        </button>
                        {item.bucket === "archived" && (
                          <button
                            type="button"
                            onClick={() => setDeleteItem(item)}
                            className="text-xs font-medium text-danger hover:underline"
                          >
                            永久刪除
                          </button>
                        )}
                        {row?.error && <span className="text-xs text-danger">{row.error}</span>}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <Pager page={page} pageCount={pageCount} totalCount={totalCount} onChange={goToPage} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "歷史檔期" }]} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl text-foreground">歷史檔期</h1>
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={`/brands/${brandId}/ads/connections`}
            className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary"
          >
            資料與連線
          </a>
          <a
            href={`/brands/${brandId}/ads/learnings`}
            className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary"
          >
            累積智慧
          </a>
          <button
            type="button"
            onClick={() => setInterviewOpen(true)}
            className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary"
          >
            前朝教訓訪談
          </button>
          <button
            type="button"
            onClick={handleNewCampaign}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            開新檔期
          </button>
        </div>
      </div>

      {banner && <p className="rounded-md bg-success/10 px-3 py-2 text-sm text-success">{banner}</p>}

      {items.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {BUCKET_ORDER.map((bucket) => (
            <FilterChip key={bucket} active={bucketFilter === bucket} onClick={() => selectBucket(bucket)}>
              {BUCKET_LABELS[bucket]}（{counts[bucket]}）
            </FilterChip>
          ))}
        </div>
      )}

      {content}

      {interviewOpen && (
        <InterviewPanel
          brandId={brandId}
          onClose={() => setInterviewOpen(false)}
          onSubmitted={handleInterviewSubmitted}
        />
      )}
      {deleteItem && (
        <CampaignDeletePanel
          brandId={brandId}
          item={deleteItem}
          onClose={() => setDeleteItem(null)}
          onDeleted={() => {
            setBanner(`已永久刪除 ${cycleLabel(deleteItem)} 這期檔期。刪除前的備份已存進 backups 資料夾。`);
            setDeleteItem(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1 text-xs font-medium",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border text-muted-foreground hover:border-primary hover:text-primary",
      )}
    >
      {children}
    </button>
  );
}
