import { formatAmount } from "./Chip";

/** Kit piece for the v9 approved → now row (prototype `pubStale()` `.diff`): one changed field of a stale launch
 * (Feature F28 "Stale launch" `diff[]`: `field_label`, `before`, `after`). `data-slot="diff-row"`.
 * A null side prints 未設定 — never an empty box or 0. */

type Value = string | number | null;
const show = (v: Value) => (v === null || v === "" ? null : typeof v === "number" ? formatAmount(v) : v);

export function DiffRow({ field, item, before, after, beforeLabel = "核准時", afterLabel = "現在" }: {
  /** API `field_label`, e.g. 每日預算. */
  field: string;
  /** Which object, e.g. 「廣告組・A・廣泛受眾」. */
  item?: string;
  before: Value;
  after: Value;
  /** e.g. 「核准時・09/20」. */
  beforeLabel?: string;
  /** e.g. 「現在・09/22 改」. */
  afterLabel?: string;
}) {
  const side = (v: Value) => show(v) ?? <span className="text-muted-foreground">未設定</span>;
  return (
    <div data-slot="diff-row" className="grid grid-cols-[150px_minmax(0,1fr)_24px_minmax(0,1fr)] items-center gap-3 border-t border-border py-3">
      <div className="min-w-0">
        <b className="text-xs">{field}</b>
        {item && <div className="text-[11.5px] text-muted-foreground [overflow-wrap:anywhere]">{item}</div>}
      </div>
      <div className="rounded-lg bg-muted px-3 py-2 text-[13.5px] [overflow-wrap:anywhere]">
        <small className="block text-[11px] text-muted-foreground">{beforeLabel}</small>{side(before)}
      </div>
      <span className="text-center text-muted-foreground" aria-label="改成">→</span>
      <div className="rounded-lg bg-accent px-3 py-2 text-[13.5px] [overflow-wrap:anywhere]">
        <small className="block text-[11px] text-muted-foreground">{afterLabel}</small>{side(after)}
      </div>
    </div>
  );
}
