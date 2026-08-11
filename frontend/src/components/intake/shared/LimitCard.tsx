import type { LimitBlock } from "@/lib/intakeApi";

/** 超限攔截卡片（契約 S4.71–S4.74）：背景工作啟動前被擋下，行內卡片、不換頁。 */
export function LimitCard({
  block,
  raising,
  onRaise,
  onSkipRemaining,
}: {
  block: LimitBlock;
  raising: boolean;
  onRaise: () => void;
  onSkipRemaining: () => void;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-md border border-warning/40 bg-warning/5 p-4 text-sm">
      <p className="text-foreground">
        這一步預估要花 US$ {block.amount.toFixed(2)}，加上去會超過你設的 US$ {block.budget_limit.toFixed(2)} 上限，所以我先停下來問你。你到目前為止的進度都留著，沒有掉。
      </p>
      <dl className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
        <div>
          <dt>已花費</dt>
          <dd className="text-sm text-foreground">US$ {block.cost_spent.toFixed(2)}</dd>
        </div>
        <div>
          <dt>目前上限</dt>
          <dd className="text-sm text-foreground">US$ {block.budget_limit.toFixed(2)}</dd>
        </div>
        <div>
          <dt>這一步預估</dt>
          <dd className="text-sm text-foreground">US$ {block.amount.toFixed(2)}</dd>
        </div>
      </dl>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={raising}
          onClick={onRaise}
          className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {raising ? "處理中…" : `把上限提高到 US$ ${block.suggested_limit.toFixed(2)} 並繼續`}
        </button>
        <button
          type="button"
          disabled={raising}
          onClick={onSkipRemaining}
          className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
        >
          不再花錢，用目前的結果直接去交接包
        </button>
      </div>
    </div>
  );
}
