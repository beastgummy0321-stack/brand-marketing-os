import { useEffect, useState, type ReactNode } from "react";
import { CheckCircle2 } from "lucide-react";
import { Link } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { PRESS_FEEDBACK, cn } from "@/lib/utils";
import { checkWebsiteNow, fetchTrackingHealth, type TrackingChannel } from "@/lib/trackingApi";

/** T0 安裝精靈（官網追蹤，契約 2.1-2.7）：結構與互動照
 * `.scratch/grill/t0-wizard-prototype.html`，視覺沿用駕駛艙既有語彙（契約 2.7）。
 * 只有官網一路（GA4／Meta Pixel 兩段），單一入口 `/brands/:brandId/tracking/setup`。 */

type SegmentKey = "ga4" | "pixel";

// TODO(T0-驗收)：以下步驟文案是概要三步，尚未逐字對照官方文件——驗收時打開下方連結
// 核對實際畫面文字與操作順序，需要的話補截圖指位（契約 2.2）。
const SEGMENT_CONFIG: Record<
  SegmentKey,
  { title: string; shortLabel: string; steps: string[]; guideHref: (brandId: string) => string; guideLabel: string }
> = {
  ga4: {
    title: "GA4（Google 流量記錄器）",
    shortLabel: "GA4",
    steps: [
      "到 Google Analytics 建立 GA4 資源，取得追蹤代碼（Measurement ID）。",
      "回 EasyStore 後台貼上 GA4 追蹤代碼。",
    ],
    guideHref: (brandId) => `/brands/${encodeURIComponent(brandId)}/ads/ga4-guide`,
    guideLabel: "不是 EasyStore？看通用教學",
  },
  pixel: {
    title: "Meta Pixel（臉書轉換記錄器）",
    shortLabel: "Meta Pixel",
    steps: ["到 Meta 事件管理工具建立 Pixel。", "回 EasyStore 後台「銷售通路」把 Pixel 接上。"],
    guideHref: (brandId) => `/brands/${encodeURIComponent(brandId)}/ads/pixel-guide`,
    guideLabel: "不是 EasyStore？看通用教學",
  },
};

const SEGMENT_ORDER: SegmentKey[] = ["ga4", "pixel"];

function SegmentBlock({
  brandId,
  segmentKey,
  missing,
  checking,
  justCheckedStillMissing,
  onCheck,
}: {
  brandId: string;
  segmentKey: SegmentKey;
  missing: boolean;
  checking: boolean;
  justCheckedStillMissing: boolean;
  onCheck: () => void;
}) {
  const cfg = SEGMENT_CONFIG[segmentKey];

  if (!missing) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-success/40 bg-success/5 px-4 py-3">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden="true" />
        <span className="text-sm font-medium text-success">{cfg.title}　已裝好，不用動</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <p className="text-sm font-semibold text-foreground">{cfg.title}</p>

      {checking ? (
        <p className="text-sm text-muted-foreground">正在連你的網站找{cfg.shortLabel}代碼…約 10 秒</p>
      ) : justCheckedStillMissing ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-danger">
            還沒驗到{cfg.shortLabel}。動態載入的平台（如 EasyStore）外部驗不到很正常。
          </p>
          <p className="text-sm text-muted-foreground">
            自己驗最準：GA4 開「報表 → 即時」看有沒有自己的瀏覽；Pixel 用 Meta 事件管理工具的「測試事件」。
          </p>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={onCheck}
              className={cn("rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10", PRESS_FEEDBACK)}
            >
              再檢查一次
            </button>
            <Link
              to={`/brands/${encodeURIComponent(brandId)}/tracking`}
              className={cn("rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted", PRESS_FEEDBACK)}
            >
              稍後再驗
            </Link>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {cfg.steps.map((step, i) => (
            <div key={i} className="flex gap-2 rounded-md border border-border bg-muted/20 px-3 py-2 text-sm">
              <span className="font-mono text-muted-foreground">{i + 1}</span>
              <span className="text-foreground">{step}</span>
            </div>
          ))}
          <div className="flex items-center gap-2 rounded-md border border-border bg-muted/20 px-3 py-2 text-sm">
            <span className="font-mono text-muted-foreground">{cfg.steps.length + 1}</span>
            <span className="flex-1 text-foreground">裝好後按右邊，我連你的網站驗證。</span>
            <button
              type="button"
              disabled={checking}
              onClick={onCheck}
              className={cn(
                "shrink-0 rounded-md border border-primary bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50",
                PRESS_FEEDBACK,
              )}
            >
              我裝好了，幫我檢查
            </button>
          </div>
          <p className="text-xs text-muted-foreground">
            {cfg.guideLabel}{" "}
            <a href={cfg.guideHref(brandId)} target="_blank" rel="noopener noreferrer" className="text-primary underline-offset-4 hover:underline">
              看通用教學 ↗
            </a>
          </p>
        </div>
      )}
    </div>
  );
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; node: TrackingChannel };

/** 進入網址帶的 `missing` query 參數（畫面 1 條文 1.6）只用來讓使用者看得懂連結目的，
 * 不當資料來源——真正顯示哪段用 GET tracking-health 現查現算（同一份邏輯只有一處，
 * 不維護兩份「缺哪樣」的判斷）。 */
export function TrackingSetupPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [checking, setChecking] = useState(false);
  const [justChecked, setJustChecked] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);

  function load() {
    setState((prev) => (prev.status === "ready" ? prev : { status: "loading" }));
    fetchTrackingHealth(brandId)
      .then((health) => {
        const node = health.channels.find((c) => c.key === "website");
        if (!node) {
          setState({ status: "error", message: "找不到官網通路資料。" });
          return;
        }
        setState({ status: "ready", node });
      })
      .catch((err: unknown) => {
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
  }

  useEffect(load, [brandId]);

  async function handleCheck() {
    setChecking(true);
    setCheckError(null);
    try {
      const node = await checkWebsiteNow(brandId);
      setState({ status: "ready", node });
      setJustChecked(true);
    } catch (err) {
      setCheckError(err instanceof Error ? err.message : "檢查失敗，請稍後再試。");
    } finally {
      setChecking(false);
    }
  }

  const backHref = `/brands/${encodeURIComponent(brandId)}/tracking`;
  const websiteEditHref = `/brands/${encodeURIComponent(brandId)}/library?tab=channels&channel_type=website`;

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </div>
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  } else {
    const { node } = state;
    if (node.status === "off") {
      content = (
        <EmptyState
          title="還沒有官網網址"
          description="要先在品牌資料填官網網址，才能檢查追蹤代碼。"
          actionInternal
          actionHref={websiteEditHref}
          actionLabel="去填官網網址"
        />
      );
    } else if (node.action.kind === "none") {
      content = (
        <div className="flex flex-col items-center gap-4 rounded-lg border border-success/40 bg-success/5 p-8 text-center">
          <p className="text-base font-medium text-foreground">🎉 官網追蹤都裝好了，不用再做任何事。</p>
          <Link
            to={backHref}
            className={cn("rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90", PRESS_FEEDBACK)}
          >
            回健檢總覽
          </Link>
        </div>
      );
    } else {
      const missingSet = new Set(node.action.missing);
      const missingLabels = SEGMENT_ORDER.filter((k) => missingSet.has(k)).map((k) => SEGMENT_CONFIG[k].shortLabel);
      content = (
        <div className="flex flex-col gap-4">
          <span className="inline-flex w-fit items-center rounded-full border border-warning px-3 py-1 text-xs text-warning">
            還缺 {missingLabels.length} 樣：{missingLabels.join("、")}
          </span>
          {checkError && <p className="text-sm text-danger">{checkError}</p>}
          {SEGMENT_ORDER.map((key) => (
            <SegmentBlock
              key={key}
              brandId={brandId}
              segmentKey={key}
              missing={missingSet.has(key)}
              checking={checking}
              justCheckedStillMissing={justChecked && !checking && missingSet.has(key)}
              onCheck={() => void handleCheck()}
            />
          ))}
        </div>
      );
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "追蹤健檢", href: backHref }, { label: "安裝精靈" }]} />
      <h1 className="font-display text-2xl text-foreground">官網追蹤安裝</h1>
      <p className="text-sm text-muted-foreground">照著做完，廣告帶來的訂單就追得回來。做到一半可以隨時離開，進度不會不見。</p>
      {content}
    </div>
  );
}
