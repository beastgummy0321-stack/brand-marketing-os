import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { formatCurrency } from "@/lib/format";
import type { CampaignTreeNode, CampaignTreeResult, ScheduleApproval, ScheduleBrief } from "@/lib/scheduleApi";

interface NodeEntry { node: CampaignTreeNode; path: string; depth: number }
function flattenNodes(nodes: CampaignTreeNode[], parent = "", depth = 0): NodeEntry[] {
  return nodes.flatMap((node, index) => {
    const path = parent ? `${parent}.${index}` : String(index);
    return [{ node, path, depth }, ...flattenNodes(node.children, path, depth + 1)];
  });
}

// 票 05：一個最深層節點的素材狀態，畫在節點詳情右側——文字跟徽章顏色照工單狀態，
// `missing`（這個節點還沒有工單）畫成中性色，不是警訊（可能只是還在提交中的第一拍）。
const BRIEF_STATUS_LABELS: Record<string, string> = {
  queued: "處理中", running: "處理中", done: "文案完成", failed: "失敗",
  closed: "已關閉", missing: "尚未建立",
};

/** 層級與欄位名稱完全由服務提供；只以節點路徑管理選取與收合。 */
export function CampaignTree({ tree, binding, bindError, onBind, approving, approveError, onApprove, revoking, revokeError, onRevoke, briefs, onGoToAssets }: {
  tree: CampaignTreeResult;
  binding: boolean; bindError: string | null; onBind: () => void;
  approving: boolean; approveError: string | null; onApprove: () => void;
  revoking: boolean; revokeError: string | null; onRevoke: () => void;
  briefs: ScheduleBrief[]; onGoToAssets: () => void;
}) {
  const [selectedPath, setSelectedPath] = useState("0");
  const entries = flattenNodes(tree.nodes);
  const selected = entries.find((entry) => entry.path === selectedPath) ?? entries[0];
  const briefByNodeKey = new Map(briefs.map((b) => [b.node_key, b]));
  const busy = binding || approving || revoking;

  if (tree.failure) return <div role="alert" className="surface p-5"><h2 className="mb-2 text-base">展開結果</h2><p className="text-sm text-danger">{tree.failure}</p><p className="mt-3 text-sm text-muted-foreground">回到方案比較，可重新選擇方案並展開。</p></div>;

  return <div className="flex flex-col gap-5">
    <section className="surface">
      <div className="surface-header flex-wrap">
        <h2>展開結果</h2>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" onClick={onBind} disabled={busy}>{binding ? "配對中…" : "配對"}</Button>
          {(tree.approval === null || !tree.approval.matches_current_tree || !tree.approval.within_approved_ceiling) && <Button type="button" variant="outline" onClick={onApprove} disabled={busy}>{approving ? "核准中…" : tree.approval === null ? "核准" : "重新核准"}</Button>}
          <label title="尚未開放：確認送出結構之前一律由人工操作" className="ml-2 flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" disabled />自動送出尚未開放</label>
        </div>
      </div>
      <div className="surface-body flex flex-col gap-3">
        {(bindError ?? tree.bind_failure) && <p role="alert" className="text-sm text-danger">{bindError ?? tree.bind_failure}</p>}
        {tree.budget_note && <p role="status" className="text-xs leading-6 text-warning">{tree.budget_note}</p>}
        {approveError && <p role="alert" className="text-sm text-danger">{approveError}</p>}
        {revokeError && <p role="alert" className="text-sm text-danger">{revokeError}</p>}
        {tree.approval && <ApprovalStatus approval={tree.approval} revoking={revoking} onRevoke={onRevoke} />}
        <p className="text-xs leading-6 text-muted-foreground">核准不會自動發布；投放仍由人工在通路自己的後台操作。</p>
      </div>
    </section>
    {entries.length === 0 ? <div className="surface"><EmptyState title="目前沒有可檢視的節點" description="回到方案比較，選擇方案並重新展開。" /></div> : <div className="surface grid grid-cols-[minmax(220px,0.7fr)_minmax(0,1.3fr)] overflow-hidden">
      <nav aria-label="投放結構節點" className="min-w-0 border-r border-border">
        <div className="flex items-center justify-between gap-2 border-b border-border px-5 py-4"><span className="text-sm font-semibold">結構節點</span><span className="text-xs text-muted-foreground">{entries.length} 個</span></div>
        <ul className="max-h-[65vh] overflow-auto py-2">{tree.nodes.map((node, index) => <NodeBranch key={index} node={node} path={String(index)} depth={0} levels={tree.levels} selectedPath={selected?.path ?? ""} onSelect={setSelectedPath} />)}</ul>
      </nav>
      <div className="min-w-0">{selected && <NodeDetail key={selected.path} entry={selected} levels={tree.levels} brief={selected.node.children.length === 0 ? briefByNodeKey.get(selected.node.node_key) : undefined} onSelectChild={(index) => setSelectedPath(`${selected.path}.${index}`)} onGoToAssets={onGoToAssets} />}</div>
    </div>}
  </div>;
}

function NodeBranch({ node, path, depth, levels, selectedPath, onSelect }: {
  node: CampaignTreeNode; path: string; depth: number; levels: string[]; selectedPath: string; onSelect: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;
  return <li>
    <div className={`flex items-start gap-1 pr-3 ${selectedPath === path ? "bg-accent/65" : ""}`} style={{ paddingLeft: 8 + Math.min(depth, 8) * 12 }}>
      {hasChildren ? <button type="button" className="mt-2.5 rounded p-1 text-muted-foreground hover:bg-muted" aria-label={`${expanded ? "收合" : "展開"} ${node.name}`} aria-expanded={expanded} onClick={() => setExpanded(!expanded)}><ChevronRight className={`size-3.5 ${expanded ? "rotate-90" : ""}`} aria-hidden="true" /></button> : <span className="w-[22px] shrink-0" />}
      <button type="button" aria-pressed={selectedPath === path} onClick={() => onSelect(path)} className="flex min-w-0 flex-1 flex-col gap-1 py-3 text-left">
        <span className="text-xs text-muted-foreground">{levels[depth] ?? `第 ${depth + 1} 層`}</span>
        <span className="break-words text-sm font-medium leading-5">{node.name}</span>
        {node.warnings.length > 0 && <span className="text-xs text-warning">提醒 {node.warnings.length}</span>}
      </button>
    </div>
    {hasChildren && expanded && <ul>{node.children.map((child, index) => <NodeBranch key={index} node={child} path={`${path}.${index}`} depth={depth + 1} levels={levels} selectedPath={selectedPath} onSelect={onSelect} />)}</ul>}
  </li>;
}

function NodeDetail({ entry, levels, brief, onSelectChild, onGoToAssets }: {
  entry: NodeEntry; levels: string[]; brief?: ScheduleBrief; onSelectChild: (index: number) => void;
  onGoToAssets: () => void;
}) {
  const { node, depth } = entry;
  return <section aria-label="節點詳情" className="flex flex-col gap-6 p-6">
    <div><Badge variant="secondary">{levels[depth] ?? `第 ${depth + 1} 層`}</Badge>{node.continued_from_node_key !== null && <Badge variant="outline">延續上一期</Badge>}<h2 className="mt-3 text-lg leading-7">{node.name}</h2></div>
    {(node.share !== null || (depth === 0 && node.bound_external_id !== null)) && <dl className="grid grid-cols-2 gap-x-5 gap-y-4 border-y border-border py-4">
      {node.share !== null && <div><dt className="text-xs text-muted-foreground">預算比例</dt><dd className="mt-1 text-xl font-semibold numeric">{(node.share * 100).toFixed(0)}%</dd></div>}
      {node.share !== null && node.daily_amount !== null && <div><dt className="text-xs text-muted-foreground">每日金額</dt><dd className="mt-1 text-xl font-semibold numeric">{formatCurrency(node.daily_amount)}</dd></div>}
      {depth === 0 && node.bound_external_id !== null && <><div><dt className="text-xs text-muted-foreground">花費</dt><dd className="mt-1 text-xl font-semibold numeric">{formatCurrency(node.spend)}</dd></div><div><dt className="text-xs text-muted-foreground">ROAS</dt><dd className="mt-1 text-xl font-semibold numeric">{node.roas === null ? "未追蹤" : `${node.roas.toFixed(2)}x`}</dd></div></>}
    </dl>}
    {node.fields.length > 0 && <dl className="flex flex-col gap-4">{node.fields.map((field, index) => <div key={index}><dt className="mb-1 text-xs text-muted-foreground">{field.label}</dt><dd className="whitespace-pre-wrap text-sm leading-7">{field.value}</dd></div>)}</dl>}
    {node.warnings.length > 0 && <div className="rounded-lg bg-warning/5 p-4"><h3 className="mb-2 text-sm text-warning">節點提醒</h3><ul className="list-disc space-y-2 pl-4 text-sm leading-6 text-warning">{node.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
    {node.children.length > 0 && <div className="border-t border-border pt-5"><h3 className="mb-3 text-sm">下層節點</h3><div className="flex flex-col gap-2">{node.children.map((child, index) => <Button key={index} type="button" variant="outline" className="h-auto justify-between whitespace-normal py-3 text-left" onClick={() => onSelectChild(index)}><span>{child.name}</span><ChevronRight className="size-4" aria-hidden="true" /></Button>)}</div></div>}
    {node.children.length === 0 && <div className="flex items-center justify-between gap-3 border-t border-border pt-5 text-sm">
      <span>素材：{BRIEF_STATUS_LABELS[brief?.status ?? "missing"] ?? brief?.status}</span>
      <Button type="button" variant="ghost" size="sm" onClick={onGoToAssets}>到素材準備</Button>
    </div>}
  </section>;
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


