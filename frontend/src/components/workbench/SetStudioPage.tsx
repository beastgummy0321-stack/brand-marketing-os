import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
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
import { PART_LABEL, regenerateLabel } from "./regenerateLabel";
import { SetGenerationStatus } from "./SetGenerationStatus";

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
  const [searchParams, setSearchParams] = useSearchParams();
  const brand = brands.find((b) => b.brand_id === brandId);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [pollError, setPollError] = useState<string | null>(null);
  const [activePart, setActivePart] = useState<ProductPart | null>(null);
  /** F40-I11 (drill-7 #16): `set.generation.status` is one brief-level field shared by every
   * part, so the payload cannot say which part is running. The page remembers the part this
   * browser started so the other tabs' buttons can name it; cleared when the round ends. */
  const [startedPart, setStartedPart] = useState<ProductPart | null>(null);

  function load(): Promise<void> {
    setState((prev) => (prev.status === "ready" ? prev : { status: "loading" }));
    return getSet(brandId, setId)
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

  // eslint-disable-next-line react-hooks/exhaustive-deps -- `load` reads only brandId/setId
  useEffect(() => void load(), [brandId, setId]);

  useEffect(() => {
    const requested = searchParams.get("part") as ProductPart | null;
    if (
      requested &&
      ["copy", "image_prompt", "video_script"].includes(requested) &&
      state.status === "ready" &&
      state.set.required_parts.includes(requested)
    ) {
      setActivePart(requested);
    }
  }, [searchParams, state]);

  const generating = state.status === "ready" &&
    ["queued", "running"].includes(state.set.generation?.status ?? "");
  useEffect(() => {
    if (!generating) setStartedPart(null);
  }, [generating]);
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
        onAction={() => void load()}
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

  function openPart(part: ProductPart) {
    setActivePart(part);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("part", part);
      return next;
    }, { replace: true });
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
          <MissingPartLinks set={set} onOpen={openPart} />
          <SetGenerationStatus brandId={brandId} set={set} generating={generating} pollError={pollError}
            part={activePart} onReload={load} onRunStarted={setStartedPart} onUpdated={applyUpdated} />

          {set.lock.reason && (
            <div className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
              {set.lock.reason}
            </div>
          )}

          {activePart && (
            <Tabs value={activePart} onValueChange={(v) => openPart(v as ProductPart)}>
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
                    runningPart={generating ? startedPart : null}
                    onRunStarted={setStartedPart}
                    onUpdated={applyUpdated}
                    onSwitchPart={openPart}
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

function MissingPartLinks({
  set,
  onOpen,
}: {
  set: SetDetail;
  onOpen: (part: ProductPart) => void;
}) {
  const missing = set.required_parts.filter(
    (part) => (set.products[part] as SetProduct | undefined)?.state !== "已選定",
  );
  if (missing.length === 0) return null;
  return (
    <div className="surface flex flex-wrap items-center gap-2 p-3 text-sm">
      <span className="text-muted-foreground">完成前尚需選定：</span>
      {missing.map((part) => (
        <button
          key={part}
          type="button"
          onClick={() => onOpen(part)}
          className="font-medium text-primary hover:underline"
        >
          {PART_LABEL[part]}
        </button>
      ))}
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
  runningPart,
  onRunStarted,
  onUpdated,
  onSwitchPart,
  onFinish,
}: {
  brandId: string;
  set: SetDetail;
  part: ProductPart;
  /** The part this browser started in the round now running, `null` when unknown. */
  runningPart: ProductPart | null;
  onRunStarted: (part: ProductPart | null) => void;
  onUpdated: (next: SetDetail) => void;
  onSwitchPart: (part: ProductPart) => void;
  onFinish: () => void;
}) {
  const product = set.products[part] as SetProduct | undefined;
  const [count, setCount] = useState<number>(
    (product?.generation_settings.count as number | undefined) ?? DEFAULT_COUNT,
  );
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  if (!product) {
    return <EmptyState title="這個素材組不需要這個產物" description="" />;
  }

  async function handleRun(runCount?: number) {
    setRunning(true);
    setError(null);
    onRunStarted(part);
    try {
      // 圖片：Decision 28，永遠不帶數量——一輪固定 10 張，由後端決定。
      const arg = part === "image_prompt" ? undefined : (runCount ?? count);
      const next = await runProduct(brandId, set.id, part, arg);
      onUpdated(next);
    } catch (err) {
      onRunStarted(null);
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
  // F40-I11 (drill-7 #16): the rule lives in `regenerateLabel.ts`; this file only renders it.
  const runLabel = regenerateLabel({
    part,
    generating,
    ownRequestInFlight: running,
    runningPart,
    productState: product.state,
    idleLabel: part === "image_prompt" ? "再生成一輪（10 張）" : `再生成 ${count} 張`,
  });
  // F47 Q7: the part's own lock (an override-approved set keeps its missing parts open).
  const locked = product.locked ?? set.lock.locked;
  const showOutput = product.versions.length > 0 || (!generating && set.generation?.status !== "failed");
  const missingLabels = set.required_parts
    .filter((requiredPart) => set.products[requiredPart]?.state !== "已選定")
    .map((requiredPart) => PART_LABEL[requiredPart]);

  function similarCount(): number {
    return (product?.generation_settings.count as number | undefined) ?? count;
  }

  function handleSimilar() {
    void handleRun(similarCount());
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="surface flex flex-wrap items-center justify-between gap-3 p-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-sm font-medium text-foreground">
            {PART_LABEL[part]}：{product.state}
          </span>
          <span className="text-xs text-muted-foreground">
            已選 {product.selected}／需要 {product.required}
          </span>
        </div>
        <Button
          disabled={generating || locked}
          title={runLabel.title}
          aria-label={runLabel.title}
          onClick={() => void handleRun()}
        >
          {runLabel.label}
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

      <details
        className="surface group"
        open={advancedOpen}
        onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
      >
        <summary className="surface-header cursor-pointer select-none text-sm font-medium text-foreground">
          進階設定
        </summary>
        {advancedOpen && <div className="surface-body flex flex-col gap-4">
          {part === "image_prompt" ? (
            <p className="text-sm text-muted-foreground">
              每輪提供 10 個圖片提案，數量不可調整。
            </p>
          ) : (
            <label className="flex max-w-xs flex-col gap-1 text-sm text-foreground">
              產出數量
              <input
                type="number"
                min={1}
                value={count}
                disabled={generating || locked}
                onChange={(e) => setCount(Math.max(1, Number(e.target.value) || 1))}
                className="h-9 rounded-md border border-border bg-card px-2 text-sm"
              />
            </label>
          )}
          {set.generation_settings.length > 0 && (
            <div className="flex flex-col gap-2 border-t border-border pt-3">
              <p className="text-xs font-medium text-muted-foreground">本次生成快照（唯讀）</p>
              {set.generation_settings.map((row) => (
                <div key={row.label} className="flex items-start justify-between gap-3 text-sm">
                  <span className="shrink-0 text-muted-foreground">{row.label}</span>
                  <span className="text-right text-foreground">{row.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>}
      </details>

      <div className="surface flex flex-wrap items-center justify-end gap-3 p-3">
        {!allDone && (
          <span className="text-xs text-muted-foreground">
            尚需選定：{missingLabels.join("、")}
          </span>
        )}
        <Button disabled={!allDone || set.lock.locked} onClick={onFinish}>完成此素材組</Button>
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
  full,
}: {
  version: ProductVersion;
  onSelect: () => void;
  onSimilar?: () => void;
  onEdit?: () => void;
  disabled?: boolean;
  /** Feature Contract L: the part already holds every selection it may (`selection_full`). */
  full?: boolean;
}) {
  const selected = Boolean(version.selected_at);
  const [confirming, setConfirming] = useState(false);
  useEffect(() => setConfirming(false), [version.id, version.selected_at]);
  const blockedByFull = !selected && Boolean(full);
  const failedLines = version.validation_warning?.lines ?? [];
  const statute = version.statutory_warning ?? null;
  const advisory = Boolean(version.claim_warning) || Boolean(statute);
  const needsConfirm = !selected && (advisory || failedLines.length > 0);
  const showWarning = !selected && (advisory || (confirming && failedLines.length > 0));
  return (
    <div className="flex flex-wrap items-center gap-2">
      {showWarning && (
        <div role="status" className="w-full rounded-md bg-warning/10 p-3 text-sm text-warning">
          {statute && (
            <div data-slot="statute-note" className="flex flex-col gap-1.5 text-[13px]">
              <div className="flex flex-wrap items-center gap-1.5">
                <b className="font-semibold text-warning-strong">食安法提醒</b>
                {statute.terms.map((t) => (
                  <span
                    key={t.term}
                    className="inline-flex items-center gap-1 rounded-full border border-warning/35 bg-card px-2 text-xs font-semibold text-warning-strong"
                  >
                    {t.term}
                    <span className="text-[11px] font-normal text-warning">{t.tier_label}</span>
                  </span>
                ))}
              </div>
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span>{statute.sentence}</span>
                <a
                  className="font-medium text-warning-strong underline underline-offset-[3px]"
                  href={statute.href}
                  target="_blank"
                  rel="noreferrer"
                >
                  衛福部認定準則
                </a>
              </div>
            </div>
          )}
          {version.claim_warning && (
            <>
              <p className={cn(statute && "mt-2")}>{version.claim_warning.message}</p>
              <Link className="underline" to={version.claim_warning.href}>前往品牌智庫補充資料（選用）</Link>
            </>
          )}
          {confirming && failedLines.length > 0 && (
            <div className={cn(advisory && "mt-2")}>
              <p>這一版有沒通過的檢查：</p>
              <ul className="mt-1 flex flex-col gap-0.5 text-xs">
                {failedLines.map((line) => <li key={line}>{line}</li>)}
              </ul>
            </div>
          )}
          {confirming && (
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" disabled={disabled} onClick={onSelect}>確認無誤，選定此版</Button>
              <Button size="sm" variant="outline" onClick={() => setConfirming(false)}>返回查看</Button>
            </div>
          )}
        </div>
      )}
      <Button
        size="sm"
        variant={selected ? "default" : "outline"}
        disabled={disabled || blockedByFull}
        onClick={() => {
          if (needsConfirm) setConfirming(true);
          else onSelect();
        }}
      >
        {selected ? "✓ 已選定" : "選定"}
      </Button>
      {blockedByFull && <span className="text-xs text-muted-foreground">已選滿，先取消一張再選</span>}
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
