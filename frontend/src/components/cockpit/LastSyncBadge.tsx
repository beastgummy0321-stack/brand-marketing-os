import { formatRelativeHours, formatSyncTime } from "@/lib/format";

/** 最後同步時間（票 07-auto-sync）：成效每日自動同步，這裡讓使用者知道數據新舊。
 * `stale`＝從沒同步過，或最後一次同步不是今天——沿用 CampaignStageBadge 同一套
 * 「越需要注意越用警示色」的配色邏輯。 */
export function LastSyncBadge({
  lastSyncAt,
  stale,
}: {
  lastSyncAt: string | null;
  stale: boolean;
}) {
  const colorClass = stale
    ? "border-warning/30 bg-warning/10 text-warning"
    : "border-border bg-muted text-muted-foreground";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${colorClass}`}
    >
      {lastSyncAt ? `更新於 ${formatRelativeHours(lastSyncAt)}（${formatSyncTime(lastSyncAt)}）` : "尚未更新"}
      {stale ? "・數據可能過期" : ""}
    </span>
  );
}
