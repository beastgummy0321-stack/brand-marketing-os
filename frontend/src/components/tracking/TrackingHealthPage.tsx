import { useEffect, useRef, useState, type ReactNode } from "react";
import { Camera, Globe, MessageCircle, Pill, ShoppingCart } from "lucide-react";
import { Link } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatSyncTime } from "@/lib/format";
import { PRESS_FEEDBACK, cn } from "@/lib/utils";
import {
  fetchTrackingHealth,
  fetchTrackingRecheckStatus,
  setChannelHidden,
  startTrackingRecheck,
  type TrackingChannel,
  type TrackingChannelKey,
  type TrackingHealth,
} from "@/lib/trackingApi";

/** T0 追蹤健檢總覽（契約 1.1-1.8）：五路固定卡＋隱藏收合。結構與互動照
 * `.scratch/grill/t0-health-prototype.html`，視覺沿用駕駛艙既有語彙（契約 1.9）。 */

export const CHANNEL_CONFIG: Record<TrackingChannelKey, { icon: typeof Globe; label: string }> = {
  website: { icon: Globe, label: "官方網站" },
  fb_page: { icon: MessageCircle, label: "Facebook 粉專" },
  ig_account: { icon: Camera, label: "Instagram" },
  shopee: { icon: ShoppingCart, label: "蝦皮" },
  pharmacy: { icon: Pill, label: "藥局現場" },
};

/** 短標籤只從狀態燈號通用推導（API 沒有另外給每路的短文案）；細節一律看 `channel.message`
 * （該欄位已是白話句子，不重覆發明第二套文案）。 */
export const STATUS_TAG: Record<TrackingChannel["status"], { text: string; className: string }> = {
  ok: { text: "就緒", className: "border-success text-success" },
  warn: { text: "差一步", className: "border-warning text-warning" },
  bad: { text: "尚未偵測", className: "border-danger text-danger" },
  off: { text: "尚未設定", className: "border-border text-muted-foreground" },
};

export const STATUS_DOT: Record<TrackingChannel["status"], string> = {
  ok: "bg-success",
  warn: "bg-warning",
  bad: "bg-danger",
  off: "bg-muted-foreground",
};

/** 每卡主按鈕（鐵則3：一路下一步）。蝦皮／藥局沒有按鈕（契約 1.5：這兩路只有白話說明，
 * 沒有可以「補」的欄位——資料是賣出去才會有，不是填出來的）。 */
function primaryAction(brandId: string, channel: TrackingChannel): { label: string; to: string } | null {
  if (channel.action.kind === "none") return null;
  if (channel.key === "shopee" || channel.key === "pharmacy") return null;
  const encodedBrand = encodeURIComponent(brandId);
  if (channel.action.kind === "install") {
    return {
      label: "去安裝",
      to: `/brands/${encodedBrand}/tracking/setup?missing=${channel.action.missing.join(",")}`,
    };
  }
  return {
    label: channel.key === "website" ? "去填官網網址" : "去補",
    to: `/brands/${encodedBrand}/library?tab=channels&channel_type=${channel.key}`,
  };
}

function ChannelRow({
  brandId,
  channel,
  hiding,
  onToggleHidden,
}: {
  brandId: string;
  channel: TrackingChannel;
  hiding: boolean;
  onToggleHidden: () => void;
}) {
  const cfg = CHANNEL_CONFIG[channel.key];
  const Icon = cfg.icon;
  const tag = STATUS_TAG[channel.status];
  const action = primaryAction(brandId, channel);

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 shadow-[var(--shadow-card)]">
      <Icon className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", STATUS_DOT[channel.status])} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{cfg.label}</p>
        <p className="truncate text-xs text-muted-foreground">{channel.message}</p>
        {channel.sub && (
          <p className="truncate text-xs text-muted-foreground" title={channel.sub}>
            {channel.sub}
          </p>
        )}
        {channel.key === "website" && channel.checked_at && (
          <p className="font-mono text-[11px] text-muted-foreground">上次檢查 {formatSyncTime(channel.checked_at)}</p>
        )}
      </div>
      <span className={cn("shrink-0 rounded-md border px-2 py-0.5 text-xs", tag.className)}>{tag.text}</span>
      {action && (
        <Link
          to={action.to}
          className={cn(
            "shrink-0 rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10",
            PRESS_FEEDBACK,
          )}
        >
          {action.label}
        </Link>
      )}
      <button
        type="button"
        disabled={hiding}
        onClick={onToggleHidden}
        title="這個品牌用不到這條通路"
        className={cn(
          "shrink-0 text-xs text-muted-foreground underline-offset-4 hover:underline disabled:cursor-not-allowed disabled:opacity-50",
          PRESS_FEEDBACK,
        )}
      >
        用不到
      </button>
    </div>
  );
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: TrackingHealth };

export function TrackingHealthPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [recheckPhase, setRecheckPhase] = useState<"idle" | "running" | "failed">("idle");
  const [recheckError, setRecheckError] = useState<string | null>(null);
  const [hidingKey, setHidingKey] = useState<TrackingChannelKey | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function load() {
    setState((prev) => (prev.status === "ready" ? prev : { status: "loading" }));
    fetchTrackingHealth(brandId)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) => {
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
  }

  useEffect(() => {
    load();
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId]);

  function pollRecheck() {
    fetchTrackingRecheckStatus(brandId)
      .then((s) => {
        if (s.status === "running") return;
        stopPolling();
        if (s.status === "failed") {
          setRecheckPhase("failed");
          setRecheckError(s.message ?? "連不上你的網站（網址可能打錯，或網站暫時掛了）。");
        } else {
          setRecheckPhase("idle");
          load();
        }
      })
      .catch(() => {
        stopPolling();
        setRecheckPhase("failed");
        setRecheckError("連不上你的網站（網址可能打錯，或網站暫時掛了）。");
      });
  }

  async function handleRecheckAll() {
    setRecheckPhase("running");
    setRecheckError(null);
    try {
      await startTrackingRecheck(brandId);
      pollRef.current = setInterval(pollRecheck, 1500);
    } catch (err) {
      setRecheckPhase("failed");
      setRecheckError(err instanceof Error ? err.message : "連不上你的網站（網址可能打錯，或網站暫時掛了）。");
    }
  }

  async function handleToggleHidden(key: TrackingChannelKey, hidden: boolean) {
    setHidingKey(key);
    setActionError(null);
    try {
      await setChannelHidden(brandId, key, hidden);
      load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "更新失敗，請稍後再試。");
    } finally {
      setHidingKey(null);
    }
  }

  const websiteEditHref = `/brands/${encodeURIComponent(brandId)}/library?tab=channels&channel_type=website`;

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-16" />
        ))}
      </div>
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  } else {
    const { data } = state;
    const allOff = data.channels.every((c) => c.status === "off");

    if (allOff) {
      content = (
        <EmptyState
          title="還沒有任何通路資料"
          description="第一步：把你的官網網址填進來，健檢才有東西可以查。"
          actionInternal
          actionHref={websiteEditHref}
          actionLabel="去填官網網址"
        />
      );
    } else if (recheckPhase === "running") {
      content = (
        <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground shadow-[var(--shadow-card)]">
          正在連你的網站檢查追蹤代碼…約 10 秒
        </div>
      );
    } else if (recheckPhase === "failed") {
      content = (
        <div className="flex flex-col gap-3 rounded-lg border border-danger/40 bg-danger/5 p-6">
          <p className="text-sm font-medium text-danger">檢查失敗</p>
          <p className="text-sm text-muted-foreground">
            {recheckError ?? "連不上你的網站（網址可能打錯，或網站暫時掛了）。"}
          </p>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={() => void handleRecheckAll()}
              className={cn("rounded-md border border-primary px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10", PRESS_FEEDBACK)}
            >
              再試一次
            </button>
            <Link
              to={websiteEditHref}
              className={cn("rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted", PRESS_FEEDBACK)}
            >
              改網址
            </Link>
          </div>
        </div>
      );
    } else {
      const visible = data.channels.filter((c) => !c.hidden);
      const hiddenOnes = data.channels.filter((c) => c.hidden);
      content = (
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-foreground">
              廣告錢花下去前，先確認訂單追得回來。{" "}
              <span className="font-mono font-semibold">
                {data.ready} / {data.total}
              </span>{" "}
              路就緒
            </p>
            <button
              type="button"
              onClick={() => void handleRecheckAll()}
              className={cn("rounded-md border border-primary px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10", PRESS_FEEDBACK)}
            >
              重新檢查全部
            </button>
          </div>

          {actionError && <p className="text-sm text-danger">{actionError}</p>}

          <div className="flex flex-col gap-2">
            {visible.map((ch) => (
              <ChannelRow
                key={ch.key}
                brandId={brandId}
                channel={ch}
                hiding={hidingKey === ch.key}
                onToggleHidden={() => void handleToggleHidden(ch.key, true)}
              />
            ))}
          </div>

          {hiddenOnes.length > 0 && (
            <div className="flex flex-col gap-2">
              <p className="text-xs text-muted-foreground">收起的通路：</p>
              {hiddenOnes.map((ch) => {
                const cfg = CHANNEL_CONFIG[ch.key];
                const Icon = cfg.icon;
                return (
                  <div
                    key={ch.key}
                    className="flex items-center justify-between rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground"
                  >
                    <span className="flex items-center gap-2">
                      <Icon className="h-4 w-4" aria-hidden="true" />
                      {cfg.label}（標了用不到）
                    </span>
                    <button
                      type="button"
                      disabled={hidingKey === ch.key}
                      onClick={() => void handleToggleHidden(ch.key, false)}
                      className={cn("rounded-md border border-border px-2 py-1 text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50", PRESS_FEEDBACK)}
                    >
                      恢復
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      );
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "設定", href: "/settings" }, { label: "追蹤健檢" }]} />
      <h1 className="font-display text-2xl text-foreground">追蹤健檢</h1>
      {content}
    </div>
  );
}
