import { TodoRow } from "../patterns";
import type { ChangeItem } from "@/lib/adsChangeApi";
import { PlatformButton } from "./PlatformButton";

/** F27-I15 Screens「Flow pages, new-ad and multi-item」: the handoff step's rows for a cleanup
 * set — one `TodoRow` per ad, each with its own 打開平台 action (`PlatformButton`, shared with the
 * single-pause flow in `HandoffPage.tsx`). `opened` is page-local tick state, same "Tick state is
 * local to the page" convention `HandoffPage.tsx`'s own doc comment already documents for the
 * single-item flow — the actual report/check calls (one per item) happen when the caller's bottom
 * "我都做完了" button runs, not per row. */
export function CleanupHandoffRows({ items, opened, onOpen }: {
  items: ChangeItem[]; opened: Set<string>; onOpen: (itemId: string) => void;
}) {
  return (
    <>
      {items.map((item, i) => (
        <TodoRow
          key={item.id}
          no={i + 1}
          done={opened.has(item.id)}
          action={<PlatformButton platformUrl={item.platform_url} target={item.target} onOpen={() => onOpen(item.id)} />}
        >
          打開平台上的「{item.target.name ?? "未命名廣告"}」，把開關關掉
        </TodoRow>
      ))}
      <TodoRow no={items.length + 1} action={<span aria-hidden="true" className="text-lg text-muted-foreground">↘</span>}>
        每一則都關掉後，回來按「我都做完了」
      </TodoRow>
    </>
  );
}
