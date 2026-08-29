import { useState } from "react";
import { CopyIconButton } from "@/components/layout/CopyIconButton";
import { formatCurrency } from "@/lib/format";
import type { CampaignTreeNode, CampaignTreeResult, CreativeAd, CreativeResult } from "@/lib/scheduleApi";

/** 票 09：把選定的方案展開成使用者接下來要打造的結構。這支元件不知道任何投放通路的
 * 詞彙——有幾層、每層叫什麼、扛預算的是哪一層，全部來自代理回覆的 `levels`／`share`，
 * 不是這裡寫死的（機器閘門：`app/tests/test_schedule.py` 會逐字掃這個檔案，出現任何
 * 通路詞彙就紅）。之後要多支援一個通路＝加一個部門任務檔，不是改這支元件。
 * 票 11：加一顆「配對」按鈕，把手動發布出去的第一層節點跟通路那邊的實際成果接起來
 * ——名字對不上（零筆或兩筆以上都算）就顯示後端給的那句失敗訊息，不提供挑選、不猜。
 * 票 01：加一顆「產素材」按鈕，把每個最深層節點各配一份內容——這支元件一樣不知道那份
 * 內容裡有哪些欄位（`label` 由部門任務檔決定），只按 `node` 名稱對回樹上的節點、把
 * `fields` 原樣列出來，機器閘門的字面比對同樣蓋到這個檔案。 */
export function CampaignTree({
  tree,
  binding,
  bindError,
  onBind,
  creative,
  generatingCreative,
  creativeError,
  onGenerateCreative,
}: {
  tree: CampaignTreeResult;
  binding: boolean;
  bindError: string | null;
  onBind: () => void;
  creative: CreativeResult | null;
  generatingCreative: boolean;
  creativeError: string | null;
  onGenerateCreative: () => void;
}) {
  if (tree.failure) {
    return (
      <div className="rounded-md border border-danger/40 bg-card p-4 shadow-[var(--shadow-card)]">
        <h2 className="mb-1 font-display text-lg text-foreground">展開結果</h2>
        <p className="text-sm text-danger">{tree.failure}</p>
      </div>
    );
  }

  const adsByNode = new Map<string, CreativeAd>((creative?.ads ?? []).map((ad) => [ad.node, ad]));

  return (
    <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="font-display text-lg text-foreground">展開結果</h2>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onBind}
            disabled={binding}
            className="rounded-md border border-primary px-2.5 py-1 text-sm font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {binding ? "配對中…" : "配對"}
          </button>
          <button
            type="button"
            onClick={onGenerateCreative}
            disabled={generatingCreative || Boolean(creative?.running)}
            className="rounded-md border border-primary px-2.5 py-1 text-sm font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {generatingCreative || creative?.running ? "產出中…" : "產素材"}
          </button>
          <label
            title="尚未開放：確認送出結構之前一律由人工操作"
            className="flex cursor-not-allowed items-center gap-1.5 text-sm text-muted-foreground opacity-60"
          >
            <input type="checkbox" disabled />
            自動送出
          </label>
        </div>
      </div>
      {(bindError ?? tree.bind_failure) && (
        <p className="mb-3 text-sm text-danger">{bindError ?? tree.bind_failure}</p>
      )}
      {(creativeError ?? creative?.failure) && (
        <p className="mb-3 text-sm text-danger">{creativeError ?? creative?.failure}</p>
      )}
      {creative?.running && (
        <p className="mb-3 rounded-md border border-dashed border-border bg-muted/40 p-2 text-xs text-muted-foreground">
          產出中…這一步可能要幾分鐘，可以先離開這一頁，回來會自己接上。
        </p>
      )}
      <div className="flex flex-col gap-2">
        {tree.nodes.map((node, i) => (
          <TreeNode key={i} node={node} depth={0} levels={tree.levels} adsByNode={adsByNode} />
        ))}
      </div>
    </div>
  );
}

function TreeNode({
  node,
  depth,
  levels,
  adsByNode,
}: {
  node: CampaignTreeNode;
  depth: number;
  levels: string[];
  adsByNode: Map<string, CreativeAd>;
}) {
  const ad = node.children.length === 0 ? adsByNode.get(node.name) : undefined;
  const [warningsOpen, setWarningsOpen] = useState(false);
  const levelLabel = levels[depth] ?? `第 ${depth + 1} 層`;

  return (
    <div className="rounded-md border border-border p-3" style={{ marginLeft: depth * 20 }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{levelLabel}</span>
        <span className="text-sm font-medium text-foreground">{node.name}</span>
        {node.share !== null && (
          <span className="text-sm text-foreground">
            {(node.share * 100).toFixed(0)}%
            {node.daily_amount !== null && `・每日 ${formatCurrency(node.daily_amount)}`}
          </span>
        )}
        {depth === 0 && node.bound_external_id !== null && (
          <span className="text-sm text-foreground">
            花費 {formatCurrency(node.spend)}・ROAS {node.roas === null ? "未追蹤" : `${node.roas.toFixed(2)}x`}
          </span>
        )}
        {node.warnings.length > 0 && (
          <button
            type="button"
            onClick={() => setWarningsOpen((open) => !open)}
            className="rounded-full bg-warning/15 px-2 py-0.5 text-xs font-medium text-warning hover:bg-warning/25"
          >
            提醒 {node.warnings.length}
          </button>
        )}
      </div>

      {node.fields.length > 0 && (
        <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
          {node.fields.map((field, i) => (
            <div key={i} className="flex gap-1">
              <dt>{field.label}：</dt>
              <dd className="text-foreground">{field.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {ad && (
        <div className="mt-2 flex flex-col gap-1.5 border-t border-dashed border-border pt-2">
          {ad.fields.map((field, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="w-20 shrink-0 text-xs text-muted-foreground">{field.label}</span>
              <span className="flex-1 text-sm text-foreground">{field.value}</span>
              <CopyIconButton getText={() => field.value} ariaLabel={`複製${field.label}`} />
            </div>
          ))}
          {ad.warnings.length > 0 && (
            <ul className="flex flex-col gap-0.5 rounded-md bg-warning/10 px-2 py-1.5 text-xs text-warning">
              {ad.warnings.map((warning, i) => (
                <li key={i}>・{warning}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {warningsOpen && node.warnings.length > 0 && (
        <ul className="mt-2 flex flex-col gap-0.5 rounded-md bg-warning/10 px-2 py-1.5 text-xs text-warning">
          {node.warnings.map((warning, i) => (
            <li key={i}>・{warning}</li>
          ))}
        </ul>
      )}

      {node.children.length > 0 && (
        <div className="mt-2 flex flex-col gap-2">
          {node.children.map((child, i) => (
            <TreeNode key={i} node={child} depth={depth + 1} levels={levels} adsByNode={adsByNode} />
          ))}
        </div>
      )}
    </div>
  );
}
