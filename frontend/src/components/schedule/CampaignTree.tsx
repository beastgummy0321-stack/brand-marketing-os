import { useState } from "react";
import { CopyIconButton } from "@/components/layout/CopyIconButton";
import { formatCurrency } from "@/lib/format";
import type {
  CampaignTreeNode,
  CampaignTreeResult,
  CreativeAd,
  CreativeCoordinates,
  CreativeResult,
  ScheduleApproval,
} from "@/lib/scheduleApi";

/** 票 T1：座標七個鍵的顯示順序與中文標籤——外殼不懂詞彙表裡的「值」合不合法，這裡只是
 * 把 `CONSTITUTION.md` 規則 5 的七個英文鍵名翻成使用者看得懂的字，不是業務判斷。 */
const COORDINATE_LABELS: [keyof CreativeCoordinates, string][] = [
  ["audience", "受眾"],
  ["pain", "痛點"],
  ["angle", "角度"],
  ["hook", "鉤子"],
  ["proof", "證明"],
  ["offer", "優惠"],
  ["format", "格式"],
];

/** 票 09：把選定的方案展開成使用者接下來要打造的結構。這支元件不知道任何投放通路的
 * 詞彙——有幾層、每層叫什麼、扛預算的是哪一層，全部來自代理回覆的 `levels`／`share`，
 * 不是這裡寫死的（機器閘門：`app/tests/test_schedule.py` 會逐字掃這個檔案，出現任何
 * 通路詞彙就紅）。之後要多支援一個通路＝加一個部門任務檔，不是改這支元件。
 * 票 11：加一顆「配對」按鈕，把手動發布出去的第一層節點跟通路那邊的實際成果接起來
 * ——名字對不上（零筆或兩筆以上都算）就顯示後端給的那句失敗訊息，不提供挑選、不猜。
 * 票 01：加一顆「產素材」按鈕，把每個最深層節點各配一份內容——這支元件一樣不知道那份
 * 內容裡有哪些欄位（`label` 由部門任務檔決定），只按 `node` 名稱對回樹上的節點、把
 * `fields` 原樣列出來，機器閘門的字面比對同樣蓋到這個檔案。
 * 票 01（`.scratch/approval-slice/issues/01-approval-is-the-money-brake.md`，ADR 0040）：
 * 加一顆「核准」／「重新核准」按鈕跟一顆「撤回」——這是花錢煞車，但這支元件不假裝它擋
 * 得住什麼：今天沒有任何一步是因為核准而被擋下來的，因為系統還不會自己發布，畫面只說
 * 「已核准」，不說「已解鎖」／「可以投放了」。 */
export function CampaignTree({
  tree,
  binding,
  bindError,
  onBind,
  approving,
  approveError,
  onApprove,
  revoking,
  revokeError,
  onRevoke,
  creative,
  generatingCreative,
  creativeError,
  onGenerateCreative,
}: {
  tree: CampaignTreeResult;
  binding: boolean;
  bindError: string | null;
  onBind: () => void;
  approving: boolean;
  approveError: string | null;
  onApprove: () => void;
  revoking: boolean;
  revokeError: string | null;
  onRevoke: () => void;
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
          {/* 超過核准當時的每日上限也要出得來這顆鈕：`within_approved_ceiling` 為 false 時
              下面的 ApprovalStatus 已經寫著「需要重新核准」，但「總額調高、結構沒變」正好
              `matches_current_tree` 還是 true，鈕就不出現，使用者只剩「先撤回再核准」這條
              猜不到的路。這裡只是多一個 OR，M2 禁止動的結構閘門本身一個字都沒改；後端
              `_run_approve` 本來就接受重複核准（每次一列新的，上限＝當下總額）。 */}
          {(tree.approval === null
            || !tree.approval.matches_current_tree
            || !tree.approval.within_approved_ceiling) && (
            <button
              type="button"
              onClick={onApprove}
              disabled={approving}
              className="rounded-md border border-primary px-2.5 py-1 text-sm font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {approving ? "核准中…" : tree.approval === null ? "核准" : "重新核准"}
            </button>
          )}
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
      {approveError && <p className="mb-3 text-sm text-danger">{approveError}</p>}
      {revokeError && <p className="mb-3 text-sm text-danger">{revokeError}</p>}
      {tree.approval && (
        <ApprovalStatus approval={tree.approval} revoking={revoking} onRevoke={onRevoke} />
      )}
      <p className="mb-3 text-xs text-muted-foreground">
        核准不會自動發布——今天沒有任何一步會因為核准而被擋下來，投放仍由人工在通路自己的後台操作。
      </p>
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

function formatApprovedDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
}

/** 已核准的那一行，加上超支比對（票 01：`spend_to_date` null＝這棵樹還沒有節點配對到
 * 通路上的活動，花費根本沒在追蹤，不是「花了 0 元」——兩件事分開講）。不設門檻：兩個
 * 數字都印出來，讓使用者自己判斷，不猜一個「超支多少算警訊」。
 * 票 M2（ADR 0059）：總額縮小不再讓 `matches_current_tree` 翻臉，畫面補兩句話——縮小但
 * 仍在上限內是好消息（跟結構變更那句放在同一個 span，同樣的低調語氣）；壓過上限是花錢
 * 警訊，要跟「活動結構已變更」那句一樣顯眼，這裡給它自己一行加上 danger 色，比原本那句
 * 純文字更醒目（規則：至少一樣顯眼，不是只能一樣）。 */
function ApprovalStatus({
  approval,
  revoking,
  onRevoke,
}: {
  approval: ScheduleApproval;
  revoking: boolean;
  onRevoke: () => void;
}) {
  const diff =
    approval.spend_to_date === null ? null : approval.spend_to_date - approval.expected_to_date;
  const budgetReduced =
    approval.within_approved_ceiling && approval.current_daily_amount < approval.max_daily_amount;
  return (
    <div className="mb-3 rounded-md border border-dashed border-border bg-muted/30 p-2 text-sm text-foreground">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          已於 {formatApprovedDate(approval.approved_at)} 核准，每日 {formatCurrency(approval.approved_amount)}
          {!approval.matches_current_tree && "（活動結構已變更，此核准對應先前版本，請重新核准）"}
          {budgetReduced &&
            `（每日預算已調降為 ${formatCurrency(approval.current_daily_amount)}，仍在核准的每日上限 ${formatCurrency(approval.max_daily_amount)} 內）`}
        </span>
        <button
          type="button"
          onClick={onRevoke}
          disabled={revoking}
          className="text-sm text-muted-foreground hover:text-danger disabled:cursor-not-allowed disabled:opacity-60"
        >
          {revoking ? "撤回中…" : "撤回"}
        </button>
      </div>
      {!approval.within_approved_ceiling && (
        <p className="mt-1 text-sm font-medium text-danger">
          今日預算 {formatCurrency(approval.current_daily_amount)} 已超過核准的每日上限{" "}
          {formatCurrency(approval.max_daily_amount)}，需要重新核准。
        </p>
      )}
      <p className="mt-1 text-xs text-muted-foreground">
        {approval.spend_to_date === null ? (
          "花費尚未開始追蹤（還沒有節點配對到通路上的活動）。"
        ) : (
          <>
            核准後 {approval.days_elapsed} 天：預期累積 {formatCurrency(approval.expected_to_date)}
            ・實際花費 {formatCurrency(approval.spend_to_date)}
            ・差額 {diff !== null && diff >= 0 ? "+" : ""}
            {diff !== null && formatCurrency(diff)}
          </>
        )}
      </p>
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
  const [coordinatesOpen, setCoordinatesOpen] = useState(false);
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
          <button
            type="button"
            onClick={() => setCoordinatesOpen((open) => !open)}
            className="self-start rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground hover:bg-muted/70"
          >
            {coordinatesOpen ? "收起座標" : "這則內容打的座標"}
          </button>
          {coordinatesOpen && (
            <dl className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
              {COORDINATE_LABELS.map(([key, label]) => (
                <div key={key} className="flex gap-1">
                  <dt>{label}：</dt>
                  <dd className="text-foreground">{ad.coordinates[key] ?? "—"}</dd>
                </div>
              ))}
            </dl>
          )}
          {ad.fields.map((field, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="w-20 shrink-0 pt-0.5 text-xs text-muted-foreground">{field.label}</span>
              <div className="flex flex-1 flex-col gap-1">
                {field.value.map((variant, j) => (
                  <div key={j} className="flex items-center gap-2">
                    <span className="flex-1 text-sm text-foreground">{variant}</span>
                    <CopyIconButton
                      getText={() => variant}
                      ariaLabel={`複製${field.label}第${j + 1}個變體`}
                    />
                  </div>
                ))}
              </div>
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
