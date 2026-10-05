import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ChevronRight, FileText, Image as ImageIcon, ListVideo, MoreHorizontal, Search } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
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
import { useOrgClock } from "@/lib/orgClock";
import { cn } from "@/lib/utils";
import {
  closePack,
  listPacks,
  type PackCard,
  type PackListStatus,
  type PackSort,
  type ProductPart,
} from "@/lib/workbenchApi";

const STATUS_PILLS: { value: PackListStatus; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "pending", label: "待處理" },
  { value: "running", label: "進行中" },
  { value: "awaiting_approval", label: "待核准" },
  { value: "done", label: "已完成" },
  { value: "closed", label: "已關閉" },
];

export const STATUS_LABEL: Record<PackCard["status"], string> = {
  pending: "待處理",
  running: "進行中",
  awaiting_approval: "待核准",
  done: "已完成",
};

export const STATUS_TONE: Record<PackCard["status"], string> = {
  pending: "bg-muted text-muted-foreground",
  running: "bg-warning/10 text-warning",
  awaiting_approval: "bg-warning/10 text-warning",
  done: "bg-success/10 text-success",
};

const SORT_OPTIONS: { value: PackSort; label: string }[] = [
  { value: "updated", label: "最新更新" },
  { value: "created", label: "建立時間" },
  { value: "progress", label: "進度" },
];

const PART_ICON: Record<ProductPart, ReactNode> = {
  copy: <FileText className="size-4" aria-hidden="true" />,
  image_prompt: <ImageIcon className="size-4" aria-hidden="true" />,
  video_script: <ListVideo className="size-4" aria-hidden="true" />,
};

const QUICK_START: { part: ProductPart; label: string; hint: string }[] = [
  { part: "image_prompt", label: "圖片", hint: "商品圖、情境圖、社群圖" },
  { part: "copy", label: "文案", hint: "社群貼文、廣告文案、標題" },
  { part: "video_script", label: "腳本", hint: "短影音腳本、分鏡、拍攝企劃" },
];

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; packs: PackCard[] };

/** 素材工作檯入口（F02-I07，`ARCHITECTURE.md` §5.1-§5.3）：任務包卡片 grid／list，
 * 右欄最近使用＋快速開始。參考圖 1 是 1:1 視覺來源；`counts`／`next_step`／`progress_pct`
 * 等欄位全部照後端 `PackCard` 給的值顯示，這裡不重新計算。 */
export function WorkbenchHomePage({ brandId }: { brandId: string }) {
  const { brands } = useWorkspace();
  const clock = useOrgClock();
  const navigate = useNavigate();
  const brand = brands.find((b) => b.brand_id === brandId);

  const [status, setStatus] = useState<PackListStatus>("all");
  const [sort, setSort] = useState<PackSort>("updated");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [state, setState] = useState<LoadState>({ status: "loading" });

  function load() {
    setState((prev) => (prev.status === "ready" ? prev : { status: "loading" }));
    listPacks(brandId, { status, q: search || undefined, sort })
      .then((packs) => setState({ status: "ready", packs }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, [brandId, status, sort, search]);
  const listRef = useRef<HTMLDivElement>(null);

  async function handleClose(packId: string) {
    await closePack(brandId, packId);
    load();
  }

  /** 「查看全部 →」 (drill-10 乙 #15): every open pack, as the list, scrolled into view. */
  function showAll() {
    setStatus("all");
    setSearch("");
    setView("list");
    listRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const packs = state.status === "ready" ? state.packs : [];
  const isEmptyBrand = state.status === "ready" && packs.length === 0
    && status === "all" && !search;
  const recentPacks = [...packs]
    .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))
    .slice(0, 5);

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-64 w-full" />
        ))}
      </div>
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  } else if (isEmptyBrand) {
    // F36-I02 (drill-6 #5): the real entry since F35 is 「開始做素材 →」 on a draft campaign's
    // 投放結構 tab, so the empty state names it and links to the campaigns list.
    content = (
      <div className="flex flex-col gap-2">
        <EmptyState
          title="目前沒有任務包"
          description="＋ 自由創作 自己開一個工作；或到投放中心打開一個活動，在「投放結構」按「開始做素材 →」，任務包就會送過來。"
          actionLabel="＋ 自由創作"
          onAction={() => navigate(`/brands/${brandId}/workbench/new`)}
        />
        <Button asChild variant="link" className="h-auto self-center p-0 text-sm">
          <Link to={`/brands/${brandId}/ads/campaigns`}>前往投放中心 →</Link>
        </Button>
      </div>
    );
  } else if (packs.length === 0) {
    content = (
      <div className="empty-state surface gap-2">
        <p className="text-sm text-muted-foreground">沒有符合條件的任務包，換個篩選條件試試。</p>
      </div>
    );
  } else if (view === "grid") {
    content = (
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {packs.map((pack) => (
          <PackCardTile
            key={pack.id}
            pack={pack}
            brandId={brandId}
            onClose={() => handleClose(pack.id)}
          />
        ))}
      </div>
    );
  } else {
    content = (
      <div className="table-surface">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">任務包</th>
              <th className="px-3 py-2 font-medium">來源</th>
              <th className="px-3 py-2 font-medium">狀態</th>
              <th className="px-3 py-2 font-medium">進度</th>
              <th className="px-3 py-2 font-medium">更新於</th>
              <th className="px-3 py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {packs.map((pack) => (
              <tr key={pack.id} className="border-t border-border">
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => navigate(`/brands/${brandId}/workbench/packs/${pack.id}`)}
                    className="text-left font-medium text-primary hover:underline"
                  >
                    {pack.name}
                  </button>
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{pack.source_label}</td>
                <td className="whitespace-nowrap px-3 py-2">
                  <PackStatusBadge pack={pack} />
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-foreground">
                  {pack.sets_done} / {pack.sets_total}（{pack.progress_pct}%）
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                  {formatUpdatedAt(pack.updated_at, clock.timezone)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right">
                  <Button size="sm" onClick={() => navigate(`/brands/${brandId}/workbench/packs/${pack.id}`)}>
                    繼續 →
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="素材工作檯"
        description="管理行銷素材任務，從靈感到上線，一站完成。"
        actions={
          <Button onClick={() => navigate(`/brands/${brandId}/workbench/new`)}>
            ＋ 自由創作
          </Button>
        }
      />
      {brand && <p className="-mt-2 text-sm text-muted-foreground">{brand.brand_name}</p>}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜尋工作、Campaign、素材組"
            className="pl-8"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {STATUS_PILLS.map((pill) => (
            <button
              key={pill.value}
              type="button"
              onClick={() => setStatus(pill.value)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                status === pill.value
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:bg-accent",
              )}
            >
              {pill.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_320px]">
        <div ref={listRef} className="flex scroll-mt-4 flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-base font-semibold">任務包（{state.status === "ready" ? packs.length : 0}）</h2>
            <div className="flex items-center gap-2">
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as PackSort)}
                className="h-8 rounded-md border border-border bg-card px-2 text-xs"
              >
                {SORT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <div className="flex items-center overflow-hidden rounded-md border border-border">
                <button
                  type="button"
                  onClick={() => setView("grid")}
                  aria-pressed={view === "grid"}
                  className={cn("px-2 py-1.5 text-xs", view === "grid" ? "bg-accent" : "bg-card")}
                >
                  格狀
                </button>
                <button
                  type="button"
                  onClick={() => setView("list")}
                  aria-pressed={view === "list"}
                  className={cn("px-2 py-1.5 text-xs", view === "list" ? "bg-accent" : "bg-card")}
                >
                  清單
                </button>
              </div>
            </div>
          </div>
          {content}
        </div>

        <div className="flex flex-col gap-4">
          <div className="surface">
            <div className="surface-header">
              <h2>最近使用</h2>
              <button type="button" onClick={showAll} className="text-xs text-primary hover:underline">
                查看全部 →
              </button>
            </div>
            <div className="surface-body flex flex-col gap-1">
              {recentPacks.length === 0 && (
                <p className="py-2 text-sm text-muted-foreground">還沒有任何任務包。</p>
              )}
              {recentPacks.map((pack) => (
                <button
                  key={pack.id}
                  type="button"
                  onClick={() => navigate(`/brands/${brandId}/workbench/packs/${pack.id}`)}
                  className="flex items-center justify-between gap-2 rounded-md px-1 py-2 text-left hover:bg-accent"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-foreground">{pack.name}</span>
                    <span className="block text-xs text-muted-foreground">
                      {pack.source_label} ・ 更新{formatUpdatedAt(pack.updated_at, clock.timezone)}
                    </span>
                  </span>
                  <PackStatusBadge pack={pack} className="shrink-0" />
                </button>
              ))}
            </div>
          </div>

          <div className="surface">
            <div className="surface-header">
              <h2>快速開始</h2>
            </div>
            <div className="surface-body flex flex-col gap-1">
              <p className="pb-1 text-xs text-muted-foreground">選擇創作類型，快速產出素材內容。</p>
              {QUICK_START.map((item) => (
                <Link
                  key={item.part}
                  to={`/brands/${brandId}/workbench/new?type=${item.part}`}
                  className="flex items-center justify-between gap-2 rounded-md px-1 py-2 hover:bg-accent"
                >
                  <span className="flex items-center gap-2">
                    <span className="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
                      {PART_ICON[item.part]}
                    </span>
                    <span>
                      <span className="block text-sm font-medium text-foreground">{item.label}</span>
                      <span className="block text-xs text-muted-foreground">{item.hint}</span>
                    </span>
                  </span>
                  <ChevronRight className="size-4 text-muted-foreground" />
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** 匯出給 F02-I10 自由創作頁「預覽將建立的工作項目」重用——同一張卡，不是第二份設計
 * （票面 Done 那句話）。預覽情境沒有真正的 pack，呼叫端自己包一層擋掉點擊即可。 */
export function PackCardTile({
  pack,
  brandId,
  onClose,
}: {
  pack: PackCard;
  brandId: string;
  /** Runs after the user confirmed 「關閉任務包」 (the dialog asks once). */
  onClose: () => Promise<unknown> | void;
}) {
  const navigate = useNavigate();
  const clock = useOrgClock();
  const [confirming, setConfirming] = useState(false);
  // 相對時間（<24h）／組織時鐘的絕對時間（`formatUpdatedAt`）; "" for the free-job preview, which has no pack yet.
  const updated = formatUpdatedAt(pack.updated_at, clock.timezone);
  const goto = () => navigate(`/brands/${brandId}/workbench/packs/${pack.id}`);
  const next = pack.next_step;
  // drill-10 乙 #16: 下一步 opens the set and the part that needs it, not the pack overview.
  const gotoNext = () =>
    next ? navigate(`/brands/${brandId}/workbench/packs/${pack.id}/sets/${next.set_id}?part=${next.part}`) : goto();
  const originHref = pack.origin_href;
  return (
    <div className="surface flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between">
        <Badge variant="outline">{pack.source_label}</Badge>
        <div className="flex items-center gap-1">
          <PackStatusBadge pack={pack} />
          {(originHref || !pack.closed) && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button type="button" aria-label="更多操作" className="rounded-md p-1 hover:bg-accent">
                  <MoreHorizontal className="size-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {/* drill-10 乙 #17: the source campaign; no item when the pack has no upstream screen. */}
                {originHref && <DropdownMenuItem onSelect={() => navigate(originHref)}>查看來源</DropdownMenuItem>}
                {!pack.closed && <DropdownMenuItem onSelect={() => setConfirming(true)}>關閉任務包</DropdownMenuItem>}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>

      <button type="button" onClick={goto} className="text-left">
        <h3 className="text-base font-semibold text-foreground">{pack.name}</h3>
        {pack.subtitle && <p className="mt-0.5 text-sm text-muted-foreground">{pack.subtitle}</p>}
      </button>

      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between text-sm">
          <span className="text-foreground">{pack.sets_done} / {pack.sets_total} 已完成</span>
          <span className="text-muted-foreground">{pack.progress_pct}%</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary"
            style={{ width: `${Math.min(100, Math.max(0, pack.progress_pct))}%` }}
          />
        </div>
      </div>

      {pack.next_step && (
        <button
          type="button"
          onClick={gotoNext}
          className="flex items-center justify-between gap-2 rounded-md border border-border bg-accent/40 px-3 py-2 text-left text-sm hover:bg-accent"
        >
          <span className="min-w-0">
            <span className="block text-xs text-muted-foreground">下一步</span>
            <span className="block truncate font-medium text-foreground">
              {pack.next_step.set_name}・{pack.next_step.label}
            </span>
          </span>
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
        </button>
      )}

      <p className="text-xs text-muted-foreground">素材組總數 {pack.sets_total}</p>

      <div className="grid grid-cols-3 gap-2">
        {pack.counts.map((count) => (
          <div key={count.part} className="rounded-md border border-border px-2 py-1.5 text-center">
            <div className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
              {PART_ICON[count.part]}
              {count.label}
            </div>
            <div className="text-sm font-semibold text-foreground">
              {count.selected}／{count.required}
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between pt-1">
        <span className="text-xs text-muted-foreground">{updated ? `更新於 ${updated}` : ""}</span>
        <Button size="sm" onClick={goto}>
          繼續 →
        </Button>
      </div>
      <ClosePackDialog
        name={pack.name}
        open={confirming}
        onCancel={() => setConfirming(false)}
        onConfirm={async () => {
          await onClose();
          setConfirming(false);
        }}
      />
    </div>
  );
}

/** A pack's state chip: 「已關閉」 for a closed pack, the approval gap (「已核准・還缺 N 組」, F47 Q7) for one approved
 * while sets still miss parts, else its status. */
export function PackStatusBadge({ pack, className }: { pack: PackCard; className?: string }) {
  if (pack.closed) return <Badge className={cn("bg-muted text-muted-foreground", className)}>已關閉</Badge>;
  if (pack.approved_gap) {
    return <Badge className={cn("bg-warning/10 text-warning", className)}>{pack.approved_gap.label}</Badge>;
  }
  return <Badge className={cn(STATUS_TONE[pack.status], className)}>{STATUS_LABEL[pack.status]}</Badge>;
}

/** drill-10 乙 #21: 「關閉任務包」 asks once and says what happens; a failed close says why and the dialog stays. */
export function ClosePackDialog({
  name,
  open,
  onCancel,
  onConfirm,
}: {
  name: string;
  open: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  function cancel() {
    setError(null);
    onCancel();
  }
  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "沒有關閉，請稍後再試。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && !busy && cancel()}>
      <DialogContent>
        <DialogTitle>關閉任務包「{name}」？</DialogTitle>
        <DialogDescription>
          關閉後它會從任務包清單移到「已關閉」；裡面的素材組和已選定的版本都會保留，之後在「已關閉」仍打得開。
        </DialogDescription>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" disabled={busy} onClick={cancel}>
            取消
          </Button>
          <Button type="button" disabled={busy} onClick={() => void confirm()}>
            {busy ? "關閉中…" : "確定關閉"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
