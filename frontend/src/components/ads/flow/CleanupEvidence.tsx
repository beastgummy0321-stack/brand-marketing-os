import { Chip, GradeChip, KindMark } from "../patterns";
import type { ChangeItem } from "@/lib/adsChangeApi";
import type { QueueCleanup, QueueCleanupAd } from "@/lib/adsTriageApi";
import { CostCell } from "./CleanupProposal";
import { Tile } from "./Tile";

type Row = { id: string; name: string | null; ad: QueueCleanupAd | null };

/** F28-I11: the confirm card of a cleanup (prototype v9 `confirmBody()` for kind `clean`, hash `d/clean/ok`) — 關 N 則、
 * 留 M 則 and the close list with grade chips and costs. Once a change set exists its items are the frozen close
 * list (prototype `q.frozen`); each is filled from the queue row's `cleanup` payload while the row is still open,
 * else it falls back to the item's own name (same live/fallback split as `PauseEvidence`/`BudgetEvidence`). */
export function CleanupEvidence({ cleanup, items }: { cleanup: QueueCleanup | null; items: ChangeItem[] }) {
  const pool = new Map([...(cleanup?.ads ?? []), ...(cleanup?.keep ?? [])].map((ad) => [ad.entity_id, ad]));
  const rows: Row[] = items.length
    ? items.map((item) => ({ id: item.target_id, name: pool.get(item.target_id)?.name ?? item.target.name, ad: pool.get(item.target_id) ?? null }))
    : (cleanup?.ads ?? []).map((ad) => ({ id: ad.entity_id, name: ad.name, ad }));
  const keep = cleanup ? pool.size - rows.filter((row) => row.ad).length : null;
  return (
    <div className="surface px-[22px] py-5">
      <div className="flex flex-wrap items-start gap-5">
        <div className="min-w-[240px] flex-1">
          <KindMark kind="cut">清理</KindMark>
          <p className="mt-1.5 text-[26px] font-semibold tracking-tight">
            關 {rows.length} 則{keep !== null && `、留 ${keep} 則`}
          </p>
        </div>
        <Chip tone="ok">✓ 不會新增花費</Chip>
      </div>
      <ul className="mt-3.5">
        {rows.map((row) => (
          <li key={row.id} className="grid grid-cols-[32px_minmax(0,1fr)_90px_100px_36px] items-center gap-3.5 border-t border-border py-[11px] first:border-t-0">
            <Tile url={row.ad?.thumbnail_url} size="sm" />
            <p className="text-sm font-medium [overflow-wrap:anywhere]">{row.name ?? "（未命名廣告）"}</p>
            {row.ad ? <GradeChip grade={row.ad.grade} /> : <span />}
            <div className="numeric text-right">{row.ad && <CostCell ad={row.ad} label="" withCaption />}</div>
            <Chip tone="bad">關</Chip>
          </li>
        ))}
      </ul>
    </div>
  );
}
