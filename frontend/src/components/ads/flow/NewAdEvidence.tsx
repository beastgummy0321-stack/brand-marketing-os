import { Chip, KindMark } from "../patterns";
import type { ChangeItem } from "@/lib/adsChangeApi";
import { Tile } from "./Tile";

/** F27-I15 Screens「Flow pages, new-ad and multi-item」: the confirm card for a `new_ad` item —
 * creative preview, destination ad set and copy. `handoff_snapshot` (Contract, `app/ads/
 * handoff_new_ad.py::_snapshot`) never carries an image URL — only `filename`/`copy`/
 * `destination`/`budget_owner` — so "creative preview" here is the filename + the approved copy
 * text, the same text-first convention `CopyEvidence` already uses in `ConfirmPage.tsx` (no kit
 * piece renders a real asset thumbnail from a change item; `Tile`'s icon fallback stands in, same
 * as `PauseEvidence`'s own fallback when a triage row's `thumbnail_url` is unknown). */
export function NewAdEvidence({ item }: { item: ChangeItem }) {
  const snapshot = item.handoff_snapshot;
  const copy = snapshot?.copy ?? {};
  const headline = copy.headline ?? copy.title;
  const body = copy.body;
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center gap-4">
        <Tile url={null} />
        <div className="min-w-0 flex-1">
          <KindMark kind="fresh">新增廣告，原廣告先留著</KindMark>
          <p className="mt-1.5 truncate text-[15px] font-semibold" title={item.target.name ?? undefined}>
            {item.target.name ?? "（未命名廣告）"}
          </p>
        </div>
        <Chip tone="ok">✓ 沿用既有預算，不會新增花費</Chip>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="rounded-md bg-muted p-3 text-sm">
          <p className="text-xs text-muted-foreground">加入既有投放組</p>
          <p className="mt-1 truncate font-medium" title={snapshot?.destination.name ?? undefined}>
            {snapshot?.destination.name ?? snapshot?.destination.native_id ?? "—"}
          </p>
        </div>
        <div className="rounded-md bg-accent/60 p-3 text-sm">
          <b className="block">{headline ?? "—"}</b>
          <p className="mt-1 whitespace-pre-wrap">{body ?? "—"}</p>
        </div>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">原因：{item.reason}</p>
    </div>
  );
}
