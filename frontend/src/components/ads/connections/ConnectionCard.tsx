import { Link } from "react-router-dom";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { Chip } from "../patterns";

/** 一張資料連線卡（v7 `connections()`，prototype ≈ 312–321）：圖示・標題＋狀態
 * chip・一行事實・（warn 才有）影響 chip・一顆連去既有設定入口的按鈕。§1.7 item 9——
 * 每張卡各自打自己的 API，一張失敗改成「讀取失敗」＋「重試」，其餘卡照常顯示。 */
export type ConnectionTone = "ok" | "warn" | "neutral";

export type ConnectionState =
  | { status: "loading" }
  | { status: "error"; message: string; onRetry: () => void }
  | {
      status: "ready";
      tone: ConnectionTone;
      badge: string;
      fact: string;
      impacts: string[];
      buttonLabel: string;
      buttonHref: string;
    };

export function ConnectionCard({ icon, title, state }: { icon: string; title: string; state: ConnectionState }) {
  return (
    <div className="surface flex items-center gap-4 p-5" data-testid={`connection-card-${title}`}>
      <div
        className="grid size-[52px] shrink-0 place-items-center rounded-[14px] bg-muted text-2xl"
        aria-hidden="true"
      >
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        {state.status === "loading" && (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-48" />
          </div>
        )}
        {state.status === "error" && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <b className="text-[15px]">{title}</b>
              <Chip tone="warn">讀取失敗</Chip>
            </div>
            <p className="mt-0.5 text-[13px] text-muted-foreground">{state.message}</p>
          </>
        )}
        {state.status === "ready" && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <b className="text-[15px]">{title}</b>
              <Chip tone={state.tone}>{state.tone === "ok" ? `✓ ${state.badge}` : state.badge}</Chip>
            </div>
            <p className="mt-0.5 text-[13px] text-muted-foreground">{state.fact}</p>
            {state.impacts.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-muted-foreground">影響</span>
                {state.impacts.map((impact) => (
                  <Chip key={impact}>{impact}</Chip>
                ))}
              </div>
            )}
          </>
        )}
      </div>
      <div className="shrink-0">
        {state.status === "error" && (
          <Button variant="outline" onClick={state.onRetry}>
            重試
          </Button>
        )}
        {state.status === "ready" && (
          <Button variant={state.tone === "warn" ? "outline" : "ghost"} asChild>
            <Link to={state.buttonHref}>{state.buttonLabel} →</Link>
          </Button>
        )}
      </div>
    </div>
  );
}
