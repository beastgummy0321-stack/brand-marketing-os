import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ChevronRight, MoreHorizontal } from "lucide-react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/layout/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/layout/ui/dropdown-menu";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { formatUpdatedAt } from "@/lib/format";
import { formatInstant, useOrgClock } from "@/lib/orgClock";
import { cn } from "@/lib/utils";
import {
  approvePack,
  closePack,
  getPack,
  setPackCompletion,
  type PackCompletionItem,
  type PackDetail,
  type PackSetRow,
} from "@/lib/workbenchApi";
import { ClosePackDialog, PackStatusBadge } from "./WorkbenchHomePage";

const SUMMARY_FIELDS: { key: keyof PackDetail["summary"]; label: string }[] = [
  { key: "situation", label: "情境" },
  { key: "angle", label: "角度" },
  { key: "style", label: "風格" },
  { key: "audience", label: "目標受眾" },
  { key: "key_messages", label: "重點訊息" },
  { key: "reference_link", label: "參考連結" },
];

const SET_ROW_DOT: Record<string, string> = {
  已完成: "bg-success text-success",
  等待決定: "bg-primary text-primary",
  待開始: "bg-muted-foreground/40 text-muted-foreground",
};

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; pack: PackDetail };

/** 任務包頁（F02-I08，`ARCHITECTURE.md` §5.1-§5.3，參考圖 2 1:1）：一個任務包、它的素材組、
 * 還缺什麼，以及這一頁自己擁有的唯一決定——核准整包。所有數字／字串都是 `PackDetail` 給的，
 * 這裡不重新計算（除了「素材組進度」legend 三個桶——那是照每個 set 已經給的 `status` 字面值
 * 計數，不是新發明一條規則）。 */
export function PackPage({ brandId, packId }: { brandId: string; packId: string }) {
  const { brands } = useWorkspace();
  const clock = useOrgClock();
  const navigate = useNavigate();
  const brand = brands.find((b) => b.brand_id === brandId);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [overrideKey, setOverrideKey] = useState<string | null>(null);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [confirmingClose, setConfirmingClose] = useState(false);

  function load() {
    setState((prev) => (prev.status === "ready" ? prev : { status: "loading" }));
    getPack(brandId, packId)
      .then((pack) => setState({ status: "ready", pack }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, [brandId, packId]);

  async function handleCompletion(item: PackCompletionItem, checked: boolean) {
    const pack = await setPackCompletion(brandId, packId, item.key, checked);
    setState({ status: "ready", pack });
  }

  async function handleClose() {
    await closePack(brandId, packId);
    navigate(`/brands/${brandId}/workbench`);
  }

  async function handleApprove() {
    setApproveError(null);
    try {
      const pack = await approvePack(brandId, packId);
      setState({ status: "ready", pack });
    } catch (err) {
      setApproveError(err instanceof Error ? err.message : "核准失敗，請稍後再試。");
    }
  }

  if (state.status === "loading") {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-6 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (state.status === "error") {
    return <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  }

  const { pack } = state;
  const overrideItem = pack.completion.find((item) => item.key === overrideKey) ?? null;

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb
        items={[
          { label: brand ? brand.brand_name : "品牌", href: `/brands/${brandId}` },
          { label: "素材工作檯", href: `/brands/${brandId}/workbench` },
          { label: pack.name },
        ]}
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[260px_1fr]">
        <PackRail brandId={brandId} pack={pack} />

        <div className="flex flex-col gap-4 min-w-0">
          <div className="surface flex flex-col gap-3 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex flex-col gap-1">
                {pack.origin_label ? (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span>
                      {pack.status === "done" ? `已同步至 ${pack.origin_label}` : `來源：${pack.origin_label}`}
                    </span>
                    {pack.origin_href && (
                      <Link to={pack.origin_href} className="text-primary hover:underline">
                        回到投放中心
                      </Link>
                    )}
                  </div>
                ) : (
                  <Badge variant="outline" className="w-fit">{pack.source_label}</Badge>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-xl font-semibold text-foreground">{pack.name}</h1>
                  {/* F47 Q7: approved with sets still missing parts — the chip links to the first such set. */}
                  {pack.approved_gap && !pack.closed ? (
                    <Link
                      to={`/brands/${brandId}/workbench/packs/${pack.id}/sets/${pack.approved_gap.set_id}`}
                      className="rounded-full hover:opacity-80"
                    >
                      <PackStatusBadge pack={pack} />
                      <span className="ml-1 text-xs text-primary hover:underline">去補上 →</span>
                    </Link>
                  ) : (
                    <PackStatusBadge pack={pack} />
                  )}
                </div>
                <p className="text-sm text-muted-foreground">
                  建立於 {formatInstant(pack.created_at, clock.timezone, "md_hm")} ｜ 最後更新 {formatUpdatedAt(pack.updated_at, clock.timezone)}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {!pack.closed && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button type="button" aria-label="更多操作" className="rounded-md p-2 hover:bg-accent">
                        <MoreHorizontal className="size-4" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onSelect={() => setConfirmingClose(true)}>關閉任務包</DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
                <div className="flex flex-col items-end gap-1">
                  {/* F40-I05（drill-7 #14）：按鈕灰掉時，原因與按鈕同一行（參考原型 #/assets 底列
                   * 的「⚠ …」）；文字整段來自後端 `blocking_text`，這裡不重算。 */}
                  <div className="flex flex-wrap items-center justify-end gap-3">
                    <Button
                      disabledReason={pack.status === "done" ? "這包素材已核准" : !pack.can_approve ? pack.blocking_text || "先完成這包素材的檢查" : undefined}
                      onClick={() => void handleApprove()}
                    >
                      {pack.status === "done" ? "已核准" : "核准整包"}
                    </Button>
                  </div>
                  {pack.image_exploration_warning && (
                    <span className="text-xs text-muted-foreground">{pack.image_exploration_warning}</span>
                  )}
                  {approveError && <span className="text-xs text-destructive">{approveError}</span>}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 border-t border-border pt-3 sm:grid-cols-3">
              <MetaTile label="平台" value={pack.meta.platform ?? "—"} />
              <MetaTile label="目標" value={pack.meta.goal ?? "—"} />
              <MetaTile label="需要完成" value={`${pack.meta.sets_required} 個素材組`} />
            </div>
          </div>

          <IncompleteOutputs brandId={brandId} pack={pack} />

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_320px]">
            <div className="flex flex-col gap-4 min-w-0">
              <ProgressCard pack={pack} />
              <SetTable brandId={brandId} pack={pack} />
            </div>

            <div className="flex flex-col gap-4">
              <SummaryCard summary={pack.summary} />
              <CompletionCard
                pack={pack}
                onToggle={(item, checked) => {
                  if (item.key === "required_outputs_met" && checked && !item.ok) {
                    setOverrideKey(item.key);
                    return;
                  }
                  void handleCompletion(item, checked);
                }}
              />
            </div>
          </div>
        </div>
      </div>

      <Dialog open={overrideItem !== null} onOpenChange={(open) => !open && setOverrideKey(null)}>
        <DialogContent>
          <DialogTitle>手動核准完成條件</DialogTitle>
          <DialogDescription>
            還有素材組沒有完成必要的文案與圖片。手動打勾會覆蓋系統判斷，之後仍看得到「已覆蓋」的紀錄。
          </DialogDescription>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOverrideKey(null)}>
              取消
            </Button>
            <Button
              type="button"
              onClick={() => {
                if (overrideItem) void handleCompletion(overrideItem, true);
                setOverrideKey(null);
              }}
            >
              確定覆蓋
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ClosePackDialog
        name={pack.name}
        open={confirmingClose}
        onCancel={() => setConfirmingClose(false)}
        onConfirm={handleClose}
      />
    </div>
  );
}

function IncompleteOutputs({ brandId, pack }: { brandId: string; pack: PackDetail }) {
  const missing = pack.sets.flatMap((set) =>
    set.cells
      .filter((cell) => cell.required !== null && cell.state !== "已選定")
      .map((cell) => ({
        setId: set.id,
        setName: set.name,
        part: cell.part,
        label: cell.label,
        text: cell.text,
      })),
  );
  if (missing.length === 0) return null;
  return (
    <div className="surface flex flex-col gap-2 p-3" aria-label="尚未完成的產物">
      <p className="text-sm font-medium text-foreground">尚未完成</p>
      <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
        {missing.map((item) => (
          <Link
            key={`${item.setId}:${item.label}`}
            to={`/brands/${brandId}/workbench/packs/${pack.id}/sets/${item.setId}?part=${item.part}`}
            className="text-primary hover:underline"
          >
            {item.setName}：{item.label}（{item.text}）
          </Link>
        ))}
      </div>
    </div>
  );
}

function MetaTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-foreground">{value}</span>
    </div>
  );
}

function PackRail({ brandId, pack }: { brandId: string; pack: PackDetail }) {
  const navigate = useNavigate();
  return (
    <div className="surface flex flex-col gap-1 p-3 xl:self-start">
      <div className="px-1 pb-2 text-sm font-semibold text-foreground">任務包</div>
      <button
        type="button"
        onClick={() => navigate(`/brands/${brandId}/workbench`)}
        className="rounded-md px-2 py-1.5 text-left text-sm text-muted-foreground hover:bg-accent"
      >
        ‹ 返回素材工作檯
      </button>
      <button
        type="button"
        className="flex items-center gap-2 rounded-md bg-accent px-2 py-1.5 text-left text-sm font-medium text-foreground"
      >
        <span className="size-2.5 shrink-0 rounded-full bg-primary" />
        總覽
      </button>
      {pack.sets.map((set) => (
        <button
          key={set.id}
          type="button"
          onClick={() => navigate(`/brands/${brandId}/workbench/packs/${pack.id}/sets/${set.id}`)}
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-foreground hover:bg-accent"
        >
          <span className={cn("size-2.5 shrink-0 rounded-full", SET_ROW_DOT[set.status]?.split(" ")[0] ?? "bg-muted-foreground/40")} />
          <span className="truncate">{set.name}</span>
        </button>
      ))}
    </div>
  );
}

function ProgressCard({ pack }: { pack: PackDetail }) {
  const counts = { 已完成: 0, 等待決定: 0, 待開始: 0 } as Record<string, number>;
  for (const set of pack.sets) {
    counts[set.status] = (counts[set.status] ?? 0) + 1; // ZERO_OK: a previously unseen status starts its count at zero.
  }
  return (
    <div className="surface">
      <div className="surface-header">
        <h2>完成進度</h2>
      </div>
      <div className="surface-body flex flex-col gap-3">
        <div className="flex items-end justify-between">
          <span className="text-lg font-semibold text-foreground">
            {pack.sets_done} / {pack.sets_total} 素材組完成
          </span>
          <span className="text-sm text-muted-foreground">{pack.progress_pct}%</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary"
            style={{ width: `${Math.min(100, Math.max(0, pack.progress_pct))}%` }}
          />
        </div>
        <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-success" />已完成 {counts["已完成"]}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-primary" />進行中 {counts["等待決定"]}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-muted-foreground/40" />待開始 {counts["待開始"]}
          </span>
        </div>
      </div>
    </div>
  );
}

function SetTable({ brandId, pack }: { brandId: string; pack: PackDetail }) {
  const navigate = useNavigate();
  const columns = pack.counts.map((c) => ({ part: c.part, label: c.label }));
  return (
    <div className="surface">
      <div className="surface-header">
        <h2>素材組進度</h2>
      </div>
      <div className="surface-body">
        <div className="table-surface">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">素材組</th>
                <th className="px-3 py-2 font-medium">狀態</th>
                {columns.map((col) => (
                  <th key={col.part} className="px-3 py-2 font-medium">{col.label}</th>
                ))}
                <th className="px-3 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {pack.sets.map((set) => (
                <SetTableRow
                  key={set.id}
                  set={set}
                  columns={columns}
                  onOpen={() => navigate(`/brands/${brandId}/workbench/packs/${pack.id}/sets/${set.id}`)}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function SetTableRow({
  set,
  columns,
  onOpen,
}: {
  set: PackSetRow;
  columns: { part: string; label: string }[];
  onOpen: () => void;
}) {
  return (
    <tr className="cursor-pointer border-t border-border hover:bg-accent/40" onClick={onOpen}>
      <td className="px-3 py-2 font-medium text-foreground">{set.name}</td>
      <td className="whitespace-nowrap px-3 py-2">
        <Badge className={cn(SET_ROW_DOT[set.status] ?? "bg-muted text-muted-foreground", "bg-opacity-10")}>
          {set.status}
        </Badge>
      </td>
      {columns.map((col) => {
        const cell = set.cells.find((c) => c.part === col.part);
        return (
          <td key={col.part} className="whitespace-nowrap px-3 py-2 text-foreground">
            {cell ? cell.text : "—"}
          </td>
        );
      })}
      <td className="whitespace-nowrap px-3 py-2 text-right">
        <ChevronRight className="ml-auto size-4 text-muted-foreground" />
      </td>
    </tr>
  );
}

function SummaryCard({ summary }: { summary: PackDetail["summary"] }) {
  const filled = SUMMARY_FIELDS.filter((f) => summary[f.key]);
  return (
    <div className="surface">
      <div className="surface-header">
        <h2>摘要</h2>
      </div>
      <div className="surface-body flex flex-col gap-2">
        {filled.length === 0 && <p className="text-sm text-muted-foreground">上游沒有填寫摘要。</p>}
        {filled.map((f) => (
          <div key={f.key} className="flex items-start justify-between gap-3 text-sm">
            <span className="shrink-0 text-muted-foreground">{f.label}</span>
            <span className="text-right text-foreground">{summary[f.key]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function CompletionCard({
  pack,
  onToggle,
}: {
  pack: PackDetail;
  onToggle: (item: PackCompletionItem, checked: boolean) => void;
}) {
  return (
    <div className="surface">
      <div className="surface-header">
        <h2>完成條件</h2>
      </div>
      <div className="surface-body flex flex-col gap-2">
        {pack.completion.map((item) => {
          const isComputed = item.key === "required_outputs_met";
          return (
            <label
              key={item.key}
              className={cn(
                "flex items-center gap-2 text-sm",
                isComputed ? "text-foreground" : "cursor-pointer text-foreground",
              )}
            >
              <input
                type="checkbox"
                checked={item.ok}
                disabled={isComputed && item.ok && !item.overridden}
                onChange={(e) => onToggle(item, e.target.checked)}
              />
              <span>
                {item.label}
                {item.overridden && <span className="ml-1 text-xs text-muted-foreground">（已覆蓋）</span>}
              </span>
            </label>
          );
        })}
        {pack.blocking_text && (
          <div className="mt-1 rounded-md bg-primary/10 px-3 py-2 text-xs text-primary">
            {pack.blocking_text}，完成後即可核准整包。
          </div>
        )}
      </div>
    </div>
  );
}
