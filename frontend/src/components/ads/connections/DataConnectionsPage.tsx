import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { getOrgId } from "@/lib/auth";
import { formatSyncTime } from "@/lib/format";
import { getConnections, type AdsConnections, type ConnectionSource } from "@/lib/adsConnectionsApi";
import { ActionBar, Chip, DAY_SWATCH, DayGrid, Legend, ReadFailed, SourceList, SourceRow, type ChipTone } from "../patterns";

/** v10 `connections()` (Feature F30 Contract H, issue F30-I15): one read of `GET …/connections` feeds the
 * header count, one card of source rows (server order: accounts, orders, product costs, then every platform
 * without a reader, greyed) and the month's day grid. The server owns every state and note; this file only
 * maps a state to its chip words and picks a row glyph. */

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: AdsConnections };

/** `YYYY-MM-DD` → `MM/DD`, the server's own `_md` shape (no Date parsing, so no timezone shift). */
const monthDay = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(8, 10)}`;

/** Chip tone and words per source state. The words are short labels; the server's `note` carries the detail. */
export function sourceChip(source: ConnectionSource): { tone: ChipTone; label: string } {
  switch (source.state) {
    case "ok":
      return { tone: "ok", label: "正常" };
    case "auth_expired":
      return { tone: "warn", label: "權限失效" };
    case "failed":
      return { tone: "warn", label: "讀取失敗" };
    case "never":
      if (source.kind === "orders") return { tone: "warn", label: "尚未匯入" };
      if (source.kind === "product_costs") return { tone: "warn", label: "還沒有商品" };
      if (source.kind === "platform") return { tone: "warn", label: "尚未連接" };
      return { tone: "warn", label: "還沒讀取" };
    case "missing_days": {
      const first = source.missing_days[0];
      if (!first) return { tone: "warn", label: "缺資料" };
      return source.kind === "orders"
        ? { tone: "warn", label: `缺 ${monthDay(first)} 之後` }
        : { tone: "warn", label: `缺 ${source.missing_days.length} 天` };
    }
    case "missing_cost":
      return { tone: "warn", label: "缺成本" };
    case "unsupported":
      return { tone: "neutral", label: "尚未支援" };
  }
}

/** The server note as is; an account that reads fine also says when it was last read (prototype 「最近讀取 …」). */
export function sourceNote(source: ConnectionSource): string {
  if (source.kind === "ad_account" && source.state === "ok" && source.last_success_at) {
    return `${source.note}・最近讀取 ${formatSyncTime(source.last_success_at)}`;
  }
  return source.note;
}

/** Row glyph (prototype ∞ ▤ ▢ G): a platform's own mark when it has one, else its name's first letter. */
const PLATFORM_GLYPH: Record<string, string> = { meta: "∞" };
function sourceIcon(source: ConnectionSource): string {
  if (source.kind === "orders") return "▤";
  if (source.kind === "product_costs") return "▢";
  return (source.platform && PLATFORM_GLYPH[source.platform]) || source.name.slice(0, 1).toUpperCase();
}

const LEGEND = [
  { label: "有資料", swatch: DAY_SWATCH.ok },
  { label: "缺資料", swatch: DAY_SWATCH.missing },
  { label: "不需要／還沒到", swatch: DAY_SWATCH.none },
  { label: "今天", swatch: DAY_SWATCH.today },
];

function Sources({ sources }: { sources: ConnectionSource[] }) {
  return (
    <section aria-label="資料來源" className="surface px-[22px] py-5">
      <SourceList>
        {sources.map((source) => {
          const chip = sourceChip(source);
          const unsupported = source.state === "unsupported";
          // Actions only on rows that need the user (the server leaves `action` null on ok rows).
          const action = source.action && source.state !== "ok" && !unsupported ? (
            <Button variant="outline" size="sm" asChild>
              <Link to={source.action.href}>{source.action.label} →</Link>
            </Button>
          ) : undefined;
          return (
            <SourceRow key={source.key} icon={sourceIcon(source)} name={source.name} tone={chip.tone} status={chip.label}
              note={sourceNote(source)} action={action} dimmed={unsupported} />
          );
        })}
      </SourceList>
    </section>
  );
}

function Calendar({ calendar }: { calendar: AdsConnections["calendar"] }) {
  const month = Number(calendar.month.slice(5, 7));
  const title = `${month} 月每天的資料`;
  return (
    <section aria-label={title} className="surface px-[22px] py-5">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        <Legend items={LEGEND} />
      </div>
      <DayGrid label={title} today={calendar.today}
        rows={calendar.rows.map((row) => ({ key: row.source_key, label: row.label, days: row.days }))} />
    </section>
  );
}

function LoadingBody() {
  return (
    <div data-testid="connections-loading" className="flex flex-col gap-4">
      <div className="surface flex flex-col gap-5 px-[22px] py-5">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3.5">
            <Skeleton className="size-11 rounded-xl" />
            <div className="flex flex-1 flex-col gap-2">
              <Skeleton className="h-4 w-64" />
              <Skeleton className="h-3 w-40" />
            </div>
          </div>
        ))}
      </div>
      <div className="surface px-[22px] py-5"><Skeleton className="h-[120px] w-full" /></div>
    </div>
  );
}

function DataConnections({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    getConnections(brandId, controller.signal)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
    return () => controller.abort();
  }, [brandId, reloadKey]);

  const homeHref = `/brands/${brandId}/ads`;
  return (
    <>
      <div className="flex max-w-[1260px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "資料連線" }]} />
        <PageHeader
          title="資料連線"
          description={state.status === "ready" ? `${state.data.attention_count} 項需要處理` : undefined}
          actions={<Chip tone="ok" className="px-3.5 py-[5px]">只讀取，不會修改你的廣告</Chip>}
        />
        {state.status === "loading" && <LoadingBody />}
        {state.status === "error" && (
          <ReadFailed what={`資料連線的狀態讀不到（${state.message}）。這一頁只讀取，你的廣告不受影響。`}
            onRetry={() => setReloadKey((key) => key + 1)} />
        )}
        {state.status === "ready" && (
          <>
            <Sources sources={state.data.sources} />
            <Calendar calendar={state.data.calendar} />
          </>
        )}
      </div>
      <ActionBar back={{ label: "投放中心", to: homeHref }} />
    </>
  );
}

export function DataConnectionsPage(props: { brandId: string }) {
  return <DataConnections key={`${getOrgId()}:${props.brandId}`} {...props} />;
}
