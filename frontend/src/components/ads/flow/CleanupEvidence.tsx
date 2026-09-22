import { Chip, KindMark } from "../patterns";
import type { ChangeItem } from "@/lib/adsChangeApi";
import type { QueueCleanup } from "@/lib/adsTriageApi";
import { formatAmount } from "./changeFlow";
import { Tile } from "./Tile";

interface Row { id: string; name: string | null; thumb: string | null; spend: number | null }

/** F27-I15 Contract F / Screens「Flow pages, new-ad and multi-item」: the confirm card for a
 * cleanup set — every proposed ad in one card (thumb, name, 7-day spend), same "still in the
 * queue → live/rich, already left it → fall back to the change set's own items" split
 * `PauseEvidence`/`BudgetEvidence` already use (`ConfirmPage.tsx`'s own doc comments) — `cleanup`
 * (the queue row's own payload, Contract F) carries `thumbnail_url`/`spend_7d`, the change items
 * alone don't. */
export function CleanupEvidence({ cleanup, items, campaignName }: {
  cleanup: QueueCleanup | null; items: ChangeItem[]; campaignName: string | null;
}) {
  const rows: Row[] = cleanup
    ? cleanup.ads.map((ad) => ({ id: ad.entity_id, name: ad.name, thumb: ad.thumbnail_url, spend: ad.spend_7d }))
    : items.map((item) => ({ id: item.id, name: item.target.name, thumb: null, spend: null }));
  const heading = cleanup
    ? `同時在投 ${cleanup.active_ads} 則・預算約撐得起 ${cleanup.can_support} 則`
    : (campaignName ?? "這個活動");
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center gap-4">
        <Tile icon={<span aria-hidden="true" className="text-2xl">🧹</span>} />
        <div className="min-w-0 flex-1">
          <KindMark kind="fresh">清理</KindMark>
          <p className="mt-1.5 truncate text-[15px] font-semibold">{heading}</p>
        </div>
        <Chip tone="ok">✓ 不會新增花費</Chip>
      </div>
      <div className="mt-4 divide-y divide-border rounded-lg border border-border">
        {rows.map((row) => (
          <div key={row.id} className="flex items-center gap-3 px-4 py-3">
            <Tile url={row.thumb} size="sm" />
            <p className="min-w-0 flex-1 truncate text-sm" title={row.name ?? undefined}>{row.name ?? "（未命名廣告）"}</p>
            <span className="numeric shrink-0 text-sm text-muted-foreground">
              {row.spend === null ? "累積中" : `7 天花 ${formatAmount(row.spend)}`}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-sm text-muted-foreground">
        原因：預算約只撐得起 {cleanup?.can_support ?? "—"} 則，暫停這段時間花費最低的 {rows.length} 則。
      </p>
    </div>
  );
}
