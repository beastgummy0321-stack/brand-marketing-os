import { useState } from "react";
import type { OnboardingConclusion } from "@/lib/onboardingReadApi";

/** 判讀結論的勾選清單（票 S2 D14）——**可重用元件**：props 只認一個 `llm_task` id
 * 跟它的結論，絕不認品牌／帳號／期間 id。票 S5 會拿同一顆元件顯示期中／期末判讀，這裡
 * 如果偷懶塞進帳號或期間 id，S5 就得回頭重挖這個範圍，設計文件明講這是「這裡沒做對，
 * S5 就要重挖」的那個決定。
 *
 * 絕不預先勾選（SPEC §7.1：預先勾好的清單不算「有人真的看過」）——`checked` 只在本地
 * `useState` 裡從空集合開始，不管 `conclusions` 本身有沒有排序或內容變化都不會帶初始值。
 * 已經採用過的（`accepted: true`）跟不能採用的（`acceptable: false`）都畫成不可勾的
 * checkbox，理由分別是「已經採用」跟後端給的 `scope_note`。 */
export function ReadingConclusions({
  taskId,
  conclusions,
  onAccept,
  busy,
  error,
}: {
  taskId: string;
  conclusions: OnboardingConclusion[];
  onAccept: (taskId: string, indexes: number[]) => void;
  busy: boolean;
  error: string | null;
}) {
  const [checked, setChecked] = useState<Set<number>>(new Set());

  const selectable = conclusions.filter((c) => c.acceptable && !c.accepted);
  const allSelected = selectable.length > 0 && selectable.every((c) => checked.has(c.index));

  function toggle(index: number) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function toggleAll() {
    setChecked(allSelected ? new Set() : new Set(selectable.map((c) => c.index)));
  }

  function handleSubmit() {
    onAccept(taskId, Array.from(checked));
    setChecked(new Set());
  }

  return (
    <div className="flex flex-col gap-3">
      {selectable.length > 0 && (
        <label className="flex items-center gap-2 text-sm font-medium text-foreground">
          <input type="checkbox" checked={allSelected} onChange={toggleAll} />
          全選
        </label>
      )}
      <ul className="flex flex-col gap-2">
        {conclusions.map((c) => (
          <li
            key={c.index}
            className="rounded-md border border-border bg-card p-3 shadow-[var(--shadow-card)]"
          >
            <div className="flex items-start gap-2">
              <input
                type="checkbox"
                className="mt-1"
                checked={c.accepted || checked.has(c.index)}
                disabled={c.accepted || !c.acceptable}
                onChange={() => toggle(c.index)}
                aria-label={`採用這條結論：${c.text}`}
              />
              <div className="flex flex-1 flex-col gap-1 text-sm text-foreground">
                <p>{c.text}</p>
                <p className="text-xs text-muted-foreground">
                  適用範圍：{c.scope_label}／信心：{c.confidence || "（代理沒有寫）"}
                </p>
                {c.evidence && <p className="text-xs text-muted-foreground">依據：{c.evidence}</p>}
                {c.sample_note && (
                  <p className="text-xs text-muted-foreground">樣本說明：{c.sample_note}</p>
                )}
                {c.accepted && <p className="text-xs text-primary">已採用</p>}
                {!c.acceptable && c.scope_note && (
                  <p className="text-xs text-danger">{c.scope_note}</p>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {error && <p className="text-sm text-danger">{error}</p>}
      <button
        type="button"
        onClick={handleSubmit}
        disabled={busy || checked.size === 0}
        className="self-start rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {busy ? "採用中…" : `採用勾選的結論（${checked.size}）`}
      </button>
    </div>
  );
}
