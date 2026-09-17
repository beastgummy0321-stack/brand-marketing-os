import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Link as LinkIcon } from "lucide-react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/layout/ui/tabs";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { cn } from "@/lib/utils";
import {
  deselectVersion,
  getSet,
  runProduct,
  selectVersion,
  type ProductPart,
  type ProductVersion,
  type SetDetail,
  type SetProduct,
} from "@/lib/workbenchApi";
import { ImagePart } from "./ImagePart";

const PART_LABEL: Record<ProductPart, string> = {
  copy: "文案",
  image_prompt: "圖片",
  video_script: "腳本",
};

const SET_STATUS_TONE: Record<string, string> = {
  已完成: "bg-success/10 text-success",
  等待決定: "bg-warning/10 text-warning",
  待開始: "bg-muted text-muted-foreground",
};

const SET_STATUS_DOT: Record<string, string> = {
  已完成: "bg-success",
  等待決定: "bg-primary",
  待開始: "bg-muted-foreground/40",
};

const DEFAULT_COUNT = 4;

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; set: SetDetail };

/** 一輪的版本們（`generation_round` 相同，`version_index` 已由後端排好序）。*/
interface RoundGroup {
  round: number;
  items: ProductVersion[];
}

function groupRounds(versions: ProductVersion[]): RoundGroup[] {
  const groups: RoundGroup[] = [];
  for (const v of versions) {
    const last = groups[groups.length - 1];
    if (last && last.round === v.generation_round) last.items.push(v);
    else groups.push({ round: v.generation_round, items: [v] });
  }
  return groups;
}

/** 素材組 studio（F02-I09，`ARCHITECTURE.md` §5.1-§5.3／§5.11／§5.13，參考圖 3 1:1）：
 * 生成、看版本、選定、完成這個素材組的地方。所有畫面文字（`cells`/`image_generation.reason`/
 * `generation_settings`）都照 `SetDetail` 給的原樣渲染，這支檔案不重算、不重打一份規則。 */
export function SetStudioPage(props: Parameters<typeof SetStudio>[0]) {
  return <SetStudio key={`${props.brandId}:${props.setId}`} {...props} />;
}

function SetStudio({
  brandId,
  packId,
  setId,
}: {
  brandId: string;
  packId: string;
  setId: string;
}) {
  const { brands } = useWorkspace();
  const navigate = useNavigate();
  const brand = brands.find((b) => b.brand_id === brandId);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [pollError, setPollError] = useState<string | null>(null);
  const [activePart, setActivePart] = useState<ProductPart | null>(null);

  function load() {
    setState((prev) => (prev.status === "ready" ? prev : { status: "loading" }));
    getSet(brandId, setId)
      .then((set) => {
        setState({ status: "ready", set });
        setActivePart((prev) =>
          prev && set.required_parts.includes(prev) ? prev : (set.required_parts[0] ?? null),
        );
      })
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, [brandId, setId]);

  const generating = state.status === "ready" &&
    ["queued", "running"].includes(state.set.generation?.status ?? "");
  useEffect(() => {
    if (!generating) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await getSet(brandId, setId);
        if (cancelled) return;
        setState({ status: "ready", set: next });
        setPollError(null);
      } catch {
        if (!cancelled) setPollError("進度暫時讀不到，會自動重試；請勿重複生成。");
      }
      if (!cancelled) timer = setTimeout(poll, 3000);
    }
    timer = setTimeout(poll, 3000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [brandId, setId, generating]);

  function applyUpdated(next: SetDetail) {
    setState({ status: "ready", set: next });
  }

  if (state.status === "loading") {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-6 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <EmptyState
        title="讀取失敗"
        description={state.message}
        onAction={load}
        actionLabel="重新載入"
      />
    );
  }

  const { set } = state;

  function goToSet(id: string) {
    navigate(`/brands/${brandId}/workbench/packs/${packId}/sets/${id}`);
  }

  function finishSet() {
    const next = set.siblings.find((s) => s.id !== set.id && s.status !== "已完成");
    if (next) goToSet(next.id);
    else navigate(`/brands/${brandId}/workbench/packs/${packId}`);
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb
        items={[
          { label: brand ? brand.brand_name : "品牌", href: `/brands/${brandId}` },
          { label: "素材工作檯", href: `/brands/${brandId}/workbench` },
          { label: set.pack_name, href: `/brands/${brandId}/workbench/packs/${packId}` },
          { label: set.name },
        ]}
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[240px_1fr]">
        <SetRail brandId={brandId} packId={packId} set={set} onOpen={goToSet} />

        <div className="flex flex-col gap-4 min-w-0">
          <SetHeader set={set} />
          {generating && <p role="status" className="rounded-md bg-muted p-3 text-sm">{set.generation?.status === "queued" ? "素材已排隊，等待生成。" : "素材生成中，完成後會自動更新。"}</p>}
          {pollError && <p role="alert" className="text-sm text-danger">{pollError}</p>}
          {set.generation?.status === "failed" && <p role="alert" className="rounded-md bg-danger/10 p-3 text-sm text-danger">這輪生成失敗：{set.generation.error || "請稍後再試。"} 可以按「再生成」重試。</p>}

          {set.lock.locked && (
            <div className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
              {set.lock.reason}
            </div>
          )}

          {activePart && (
            <Tabs value={activePart} onValueChange={(v) => setActivePart(v as ProductPart)}>
              <TabsList>
                {set.required_parts.map((part) => (
                  <TabsTrigger key={part} value={part}>
                    {PART_LABEL[part]}
                  </TabsTrigger>
                ))}
              </TabsList>
              {set.required_parts.map((part) => (
                <TabsContent key={part} value={part}>
                  <ProductPanel
                    brandId={brandId}
                    set={set}
                    part={part}
                    onUpdated={applyUpdated}
                    onSwitchPart={setActivePart}
                    onFinish={finishSet}
                  />
                </TabsContent>
              ))}
            </Tabs>
          )}
        </div>
      </div>
    </div>
  );
}

function SetRail({
  brandId,
  packId,
  set,
  onOpen,
}: {
  brandId: string;
  packId: string;
  set: SetDetail;
  onOpen: (id: string) => void;
}) {
  const navigate = useNavigate();
  return (
    <div className="surface flex flex-col gap-1 p-3 xl:self-start">
      <div className="px-1 pb-2 text-sm font-semibold text-foreground">素材組</div>
      <button
        type="button"
        onClick={() => navigate(`/brands/${brandId}/workbench/packs/${packId}`)}
        className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-foreground hover:bg-accent"
      >
        <span className="size-2.5 shrink-0 rounded-full bg-primary" />
        總覽
      </button>
      {set.siblings.map((sib) => (
        <button
          key={sib.id}
          type="button"
          onClick={() => onOpen(sib.id)}
          className={cn(
            "flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent",
            sib.id === set.id ? "bg-accent font-medium text-foreground" : "text-foreground",
          )}
        >
          <span
            className={cn(
              "size-2.5 shrink-0 rounded-full",
              SET_STATUS_DOT[sib.status] ?? "bg-muted-foreground/40",
            )}
          />
          <span className="flex min-w-0 flex-col">
            <span className="truncate">{sib.name}</span>
            {sib.angle && <span className="truncate text-xs text-muted-foreground">{sib.angle}</span>}
          </span>
        </button>
      ))}
    </div>
  );
}

function SetHeader({ set }: { set: SetDetail }) {
  const chips = [set.chips.platform, set.chips.style, set.chips.size].filter(
    (v): v is string => Boolean(v),
  );
  return (
    <div className="surface flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          {set.origin_label && (
            <span className="text-xs text-muted-foreground">來源：{set.origin_label}</span>
          )}
          <h1 className="text-xl font-semibold text-foreground">{set.name}</h1>
          <div className="flex flex-wrap items-center gap-1.5">
            {chips.map((c) => (
              <Badge key={c} variant="outline">
                {c}
              </Badge>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {set.origin_href && (
            <Link
              to={set.origin_href}
              className="text-xs text-primary hover:underline"
            >
              回到投放中心 ↗
            </Link>
          )}
          <Badge className={SET_STATUS_TONE[set.status] ?? "bg-muted text-muted-foreground"}>
            {set.status}
          </Badge>
        </div>
      </div>
    </div>
  );
}

function ProductPanel({
  brandId,
  set,
  part,
  onUpdated,
  onSwitchPart,
  onFinish,
}: {
  brandId: string;
  set: SetDetail;
  part: ProductPart;
  onUpdated: (next: SetDetail) => void;
  onSwitchPart: (part: ProductPart) => void;
  onFinish: () => void;
}) {
  const product = set.products[part] as SetProduct | undefined;
  const [mode, setMode] = useState<"quick" | "precise">("quick");
  const [count, setCount] = useState<number>(
    (product?.generation_settings.count as number | undefined) ?? DEFAULT_COUNT,
  );
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!product) {
    return <EmptyState title="這個素材組不需要這個產物" description="" />;
  }

  // 摘要行：跳過 `generation_settings` 前三列（header chips 已經顯示過同樣的值），
  // 其餘照給的順序濃縮成一行，不重打一份標籤對照表。
  const summaryLine = set.generation_settings
    .slice(3)
    .filter((row) => row.text !== "—")
    .map((row) => row.text)
    .join("、");

  async function handleRun(runCount?: number) {
    setRunning(true);
    setError(null);
    try {
      // 圖片：Decision 28，永遠不帶數量——一輪固定 10 張，由後端決定。
      const arg = part === "image_prompt" ? undefined : (runCount ?? count);
      const next = await runProduct(brandId, set.id, part, arg);
      onUpdated(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "產出失敗，請稍後再試。");
    } finally {
      setRunning(false);
    }
  }

  async function handleSelect(versionId: string, selected: boolean) {
    setError(null);
    try {
      const next = selected
        ? await deselectVersion(brandId, set.id, versionId)
        : await selectVersion(brandId, set.id, versionId);
      onUpdated(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失敗，請稍後再試。");
    }
  }

  const allDone = set.required_parts.every(
    (p) => (set.products[p] as SetProduct | undefined)?.state === "已選定",
  );
  const generating = running || ["queued", "running"].includes(set.generation?.status ?? "");
  const locked = set.lock.locked;
  const showOutput = product.versions.length > 0 || (!generating && set.generation?.status !== "failed");

  function similarCount(): number {
    return (product?.generation_settings.count as number | undefined) ?? count;
  }

  function handleSimilar() {
    void handleRun(similarCount());
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="surface flex flex-wrap items-center gap-3 p-3">
        {part !== "image_prompt" && (
          <div className="inline-flex overflow-hidden rounded-md border border-border">
            <button
              type="button"
              onClick={() => setMode("quick")}
              className={cn("px-2.5 py-1.5 text-xs font-medium", mode === "quick" ? "bg-accent" : "bg-card")}
            >
              快速生成
            </button>
            <button
              type="button"
              onClick={() => setMode("precise")}
              className={cn("px-2.5 py-1.5 text-xs font-medium", mode === "precise" ? "bg-accent" : "bg-card")}
            >
              精準控制
            </button>
          </div>
        )}

        {summaryLine && (
          <div className="flex min-w-0 flex-1 items-center gap-1.5 text-xs text-muted-foreground">
            <LinkIcon className="size-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">{summaryLine}</span>
          </div>
        )}

        {part !== "image_prompt" && mode === "precise" && (
          <input
            type="number"
            min={1}
            value={count}
            onChange={(e) => setCount(Math.max(1, Number(e.target.value) || 1))}
            className="h-8 w-16 rounded-md border border-border bg-card px-2 text-sm"
            aria-label="產出數量"
          />
        )}

        <Button disabled={generating || locked} onClick={() => void handleRun()}>
          {generating ? "生成中…" : part === "image_prompt" ? "再生成一輪（10 張）" : `再生成 ${count} 張`}
        </Button>
      </div>

      {error && (
        <div className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">{error}</div>
      )}

      {showOutput && part === "image_prompt" && (
        <ImagePart
          set={set}
          product={product}
          onSelect={handleSelect}
          onSwitchPart={onSwitchPart}
          imageGeneration={set.image_generation}
          locked={locked}
          onSimilar={handleSimilar}
        />
      )}
      {showOutput && part === "copy" && <CopyPart product={product} onSelect={handleSelect} locked={locked} />}
      {showOutput && part === "video_script" && (
        <VideoScriptPart product={product} onSelect={handleSelect} locked={locked} />
      )}

      <div className="surface flex items-center justify-between p-3">
        <Button variant="outline" disabled={generating || locked} onClick={() => void handleRun()}>
          {part === "image_prompt" ? "再生成一輪（10 張）" : `再生成 ${count} 張`}
        </Button>
        <Button disabled={!allDone || locked} onClick={onFinish}>
          完成此素材組
        </Button>
      </div>
    </div>
  );
}

/** `CopyRoundCard`／`ScriptRoundCard`（下面）與 `ImagePart.tsx` 共用；同資料夾內部匯入，不走
 * `index.ts`（ADR 0060 只管跨功能夾）。 */
export function VersionBadge({
  version,
  onSelect,
  onSimilar,
  onEdit,
  disabled,
}: {
  version: ProductVersion;
  onSelect: () => void;
  onSimilar?: () => void;
  onEdit?: () => void;
  disabled?: boolean;
}) {
  const selected = Boolean(version.selected_at);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        size="sm"
        variant={selected ? "default" : "outline"}
        disabled={disabled}
        onClick={onSelect}
      >
        {selected ? "✓ 已選定" : "選定"}
      </Button>
      {onSimilar && (
        <Button size="sm" variant="outline" disabled={disabled} onClick={onSimilar}>
          相似版本
        </Button>
      )}
      {onEdit && (
        <Button size="sm" variant="outline" onClick={onEdit}>
          修改需求
        </Button>
      )}
    </div>
  );
}

function CopyPart({
  product,
  onSelect,
  locked,
}: {
  product: SetProduct;
  onSelect: (versionId: string, selected: boolean) => void;
  locked: boolean;
}) {
  const rounds = groupRounds(product.versions);
  return (
    <div className="flex flex-col gap-4">
      {rounds.length === 0 && <EmptyState title="還沒有生成過" description="按上方「再生成」開始第一輪。" />}
      {rounds.map((group) => (
        <CopyRoundCard key={group.round} group={group} onSelect={onSelect} locked={locked} />
      ))}
    </div>
  );
}

function CopyRoundCard({
  group,
  onSelect,
  locked,
}: {
  group: RoundGroup;
  onSelect: (versionId: string, selected: boolean) => void;
  locked: boolean;
}) {
  const [index, setIndex] = useState(0);
  const version = group.items[index];
  const selected = Boolean(version.selected_at);
  return (
    <div className="surface">
      <div className="surface-header">
        <h2>第 {group.round} 輪</h2>
        <span className="text-xs text-muted-foreground">
          第 {index + 1} ／ {group.items.length} 版
        </span>
      </div>
      <div className="surface-body flex flex-col gap-3">
        <div className="flex flex-col gap-2 text-sm">
          <div>
            <span className="text-xs text-muted-foreground">主文</span>
            <p className="whitespace-pre-wrap text-foreground">{String(version.body?.body ?? "")}</p>
          </div>
          <div>
            <span className="text-xs text-muted-foreground">標題</span>
            <p className="text-foreground">{String(version.body?.headline ?? "")}</p>
          </div>
          <div>
            <span className="text-xs text-muted-foreground">說明</span>
            <p className="text-foreground">{String(version.body?.description ?? "")}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <VersionBadge
            version={version}
            onSelect={() => onSelect(version.id, selected)}
            disabled={locked}
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => setIndex((i) => (i + 1) % group.items.length)}
          >
            下一版
          </Button>
        </div>
      </div>
    </div>
  );
}

function VideoScriptPart({
  product,
  onSelect,
  locked,
}: {
  product: SetProduct;
  onSelect: (versionId: string, selected: boolean) => void;
  locked: boolean;
}) {
  const rounds = groupRounds(product.versions);
  return (
    <div className="flex flex-col gap-4">
      {rounds.length === 0 && <EmptyState title="還沒有生成過" description="按上方「再生成」開始第一輪。" />}
      {rounds.map((group) => (
        <ScriptRoundCard key={group.round} group={group} onSelect={onSelect} locked={locked} />
      ))}
    </div>
  );
}

function ScriptRoundCard({
  group,
  onSelect,
  locked,
}: {
  group: RoundGroup;
  onSelect: (versionId: string, selected: boolean) => void;
  locked: boolean;
}) {
  const [index, setIndex] = useState(0);
  const version = group.items[index];
  const selected = Boolean(version.selected_at);
  const beats = Array.isArray(version.body?.beats) ? (version.body?.beats as Record<string, unknown>[]) : [];
  return (
    <div className="surface">
      <div className="surface-header">
        <h2>第 {group.round} 輪 ・ {String(version.body?.title ?? "")}</h2>
        <span className="text-xs text-muted-foreground">
          第 {index + 1} ／ {group.items.length} 支
        </span>
      </div>
      <div className="surface-body flex flex-col gap-3">
        <div className="flex flex-col gap-2">
          {beats.map((beat, i) => (
            <div key={i} className="rounded-md border border-border p-2 text-xs">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Badge variant="outline">{String(beat.t ?? "")}</Badge>
              </div>
              <p className="mt-1 text-foreground">{String(beat.visual ?? "")}</p>
              <p className="text-muted-foreground">{String(beat.voice ?? "")}</p>
              {Boolean(beat.text) && (
                <p className="text-muted-foreground">字卡：{String(beat.text)}</p>
              )}
            </div>
          ))}
          {beats.length === 0 && <p className="text-sm text-muted-foreground">還沒有節拍。</p>}
        </div>
        <div className="flex items-center gap-2">
          <VersionBadge
            version={version}
            onSelect={() => onSelect(version.id, selected)}
            disabled={locked}
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => setIndex((i) => (i + 1) % group.items.length)}
          >
            下一版
          </Button>
        </div>
      </div>
    </div>
  );
}
