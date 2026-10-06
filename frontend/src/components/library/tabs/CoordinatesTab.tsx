import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { X } from "lucide-react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { SidePanel } from "@/components/layout/SidePanel";
import {
  COORDINATE_DIMENSIONS,
  createCoordinate,
  fetchCoordinates,
  setCoordinateDisabled,
  type Coordinate,
  type CoordinateDimension,
} from "@/lib/coordinatesApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { Badge } from "../shared/Badge";
import { PanelSaveButton } from "../shared/PanelSaveButton";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; coordinates: Coordinate[]; refreshError?: string };

function coordinateError(err: unknown): string {
  return err instanceof Error ? err.message : "讀取失敗，請稍後再試。";
}

/** 品牌智庫第 8 分頁「創意座標」（票 T1b）：七個維度各自一個子分頁按鈕，`angle` 底下的
 * 種子角度再依 `category` 收合分組，不做成一路往下滑的長頁（互動鐵則）。這支分頁自己打
 * `/api/schedule/brands/{brandId}/coordinates` 三支端點，不經過 `fetchLibrary()`
 * （station ① decision 3）。 */
export function CoordinatesTab({ brandId }: { brandId: string }) {
  // Each brand owns its selection and draft; an old request cannot replace a new brand's rows.
  return <BrandCoordinatesTab key={brandId} brandId={brandId} />;
}

function BrandCoordinatesTab({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [dimension, setDimension] = useState<CoordinateDimension>("angle");
  const [selectedCategory, setSelectedCategory] = useState("");
  const [panelOpen, setPanelOpen] = useState(false);
  const request = useRef(0);
  const categorySelect = useRef<HTMLSelectElement>(null);
  const activeDimension = useRef<HTMLButtonElement>(null);

  function restoreFocus() {
    (categorySelect.current ?? activeDimension.current)?.focus();
  }

  const load = useCallback(async () => {
    const currentRequest = ++request.current;
    // Refresh keeps the mounted controls, selection and focus. Initial reads still use the skeleton.
    setState((previous) => previous.status === "ready"
      ? { status: "ready", coordinates: previous.coordinates }
      : { status: "loading" });
    try {
      const coordinates = await fetchCoordinates(brandId);
      if (currentRequest === request.current) setState({ status: "ready", coordinates });
    } catch (err) {
      if (currentRequest !== request.current) return;
      const message = coordinateError(err);
      setState((previous) => previous.status === "ready"
        ? { ...previous, refreshError: message }
        : { status: "error", message });
    }
  }, [brandId]);

  useEffect(() => {
    void load();
    return () => { request.current += 1; };
  }, [load]);

  useEffect(() => {
    if (state.status !== "ready") return;
    const categories = state.coordinates.filter((c) => c.dimension === dimension)
      .map((c) => c.category ?? "未分類");
    if (!categories.includes(selectedCategory)) setSelectedCategory(categories[0] ?? "");
  }, [state, dimension, selectedCategory]);

  async function saved(coordinate: Coordinate) {
    // The response confirms this row even if the subsequent reread fails.
    setState((previous) => previous.status === "ready"
      ? { status: "ready", coordinates: previous.coordinates.some((c) => c.id === coordinate.id)
        ? previous.coordinates.map((c) => c.id === coordinate.id ? coordinate : c)
        : [...previous.coordinates, coordinate] }
      : previous);
    await load();
  }

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-4">
        <div className="flex gap-2">
          {COORDINATE_DIMENSIONS.map(([key]) => (
            <Skeleton key={key} className="h-9 w-20" />
          ))}
        </div>
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );
  } else if (state.status === "error") {
    content = (
      <EmptyState title="讀取失敗" description={state.message} actionLabel="重新載入" onAction={load} />
    );
  } else {
    const { coordinates } = state;
    const shown = coordinates.filter((c) => c.dimension === dimension);
    content = (
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-2">
          <div className="flex flex-wrap gap-1.5">
            {COORDINATE_DIMENSIONS.map(([key, label]) => {
              const active = dimension === key;
              const count = coordinates.filter((c) => c.dimension === key).length;
              return (
                <button
                  key={key}
                  ref={active ? activeDimension : undefined}
                  type="button"
                  onClick={() => setDimension(key)}
                  className={
                    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors " +
                    (active
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground")
                  }
                >
                  {label}
                  <span
                    className={
                      "rounded-full px-1.5 text-xs " +
                      (active ? "bg-primary-foreground/20" : "bg-muted text-muted-foreground")
                    }
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
          <button
            type="button"
            onClick={() => setPanelOpen(true)}
            className="shrink-0 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            新增座標
          </button>
        </div>

        {shown.length === 0 ? (
          <EmptyState
            title="這個維度還沒有座標"
            description="按上面「新增座標」新增一個，或先看看其他維度。"
          />
        ) : (
          <CoordinateGroups brandId={brandId} coordinates={shown}
            selectedCategory={selectedCategory} onCategoryChange={setSelectedCategory} onChanged={saved}
            categorySelect={categorySelect} onFocusFallback={restoreFocus} />
        )}
        {state.refreshError && (
          <EmptyState title="讀取失敗" description={state.refreshError} actionLabel="重新載入" onAction={load} />
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-display text-lg text-foreground">創意座標</h2>
      {content}

      {panelOpen && (
        <CoordinateFormPanel
          brandId={brandId}
          defaultDimension={dimension}
          onClose={() => setPanelOpen(false)}
          onSaved={(coordinate) => {
            setPanelOpen(false);
            void saved(coordinate);
          }}
        />
      )}
    </div>
  );
}

/** 依 `category` 分組收合（`null` 併入「未分類」），組內順序照後端回傳（已按
 * `category NULLS LAST, label` 排序），不再重排一次。 */
function CoordinateGroups({
  brandId,
  coordinates,
  selectedCategory,
  onCategoryChange,
  categorySelect,
  onFocusFallback,
  onChanged,
}: {
  brandId: string;
  coordinates: Coordinate[];
  selectedCategory: string;
  onCategoryChange: (category: string) => void;
  categorySelect: RefObject<HTMLSelectElement | null>;
  onFocusFallback: () => void;
  onChanged: (coordinate: Coordinate) => Promise<void>;
}) {
  const groups = new Map<string, Coordinate[]>();
  for (const c of coordinates) {
    const key = c.category ?? "未分類";
    const list = groups.get(key);
    if (list) list.push(c);
    else groups.set(key, [c]);
  }

  const category = groups.has(selectedCategory) ? selectedCategory : [...groups.keys()][0];
  const items = groups.get(category) ?? [];
  return (
    <div className="flex flex-col gap-3">
      <label className="flex items-center gap-3 text-sm text-muted-foreground">分類<select ref={categorySelect} value={category} onChange={e => onCategoryChange(e.target.value)}>{[...groups].map(([key,rows]) => <option key={key} value={key}>{key}（{rows.length}）</option>)}</select></label>
          <div className="overflow-x-auto border-t border-border">
            <table className="text-left text-sm">
              <thead className="bg-muted text-muted-foreground">
                <tr>
                  <th className="px-4 py-2 font-medium">座標名稱</th>
                  <th className="px-4 py-2 font-medium">漏斗位置</th>
                  <th className="px-4 py-2 font-medium text-right">狀態</th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => (
                  <tr key={c.id} className="border-t border-border align-top">
                    <td className="px-4 py-2 text-foreground">{c.label}</td>
                    <td className="px-4 py-2">
                      {c.attributes.funnel_stage ? (
                        <Badge>{c.attributes.funnel_stage}</Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <DisableToggle brandId={brandId} coordinate={c} onChanged={onChanged} onFocusFallback={onFocusFallback} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
    </div>
  );
}

function DisableToggle({
  brandId,
  coordinate,
  onChanged,
  onFocusFallback,
}: {
  brandId: string;
  coordinate: Coordinate;
  onChanged: (coordinate: Coordinate) => Promise<void>;
  onFocusFallback: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const enabled = coordinate.disabled_at === null;

  function toggle() {
    const hadFocus = document.activeElement === input.current;
    setBusy(true);
    setError(null);
    setCoordinateDisabled(brandId, coordinate.id, enabled)
      .then(onChanged)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "更新失敗，請稍後再試。");
      })
      .finally(() => {
        setBusy(false);
        // Disabling can move focus to the body; do not steal it if the user moved elsewhere.
        if (hadFocus) {
          requestAnimationFrame(() => {
            if (document.activeElement !== document.body && document.activeElement !== input.current) return;
            if (input.current) input.current.focus();
            else onFocusFallback();
          });
        }
      });
  }

  return (
    <div className="flex flex-col items-end gap-0.5">
      <label className="flex items-center justify-end gap-1.5 text-sm text-foreground">
        <input ref={input} type="checkbox" checked={enabled} disabled={busy} onChange={toggle} />
        {enabled ? "啟用" : "已停用"}
      </label>
      {error && <span className="text-xs text-danger">{error}</span>}
    </div>
  );
}

function CoordinateFormPanel({
  brandId,
  defaultDimension,
  onClose,
  onSaved,
}: {
  brandId: string;
  defaultDimension: CoordinateDimension;
  onClose: () => void;
  onSaved: (coordinate: Coordinate) => void;
}) {
  const [dimension, setDimension] = useState<CoordinateDimension>(defaultDimension);
  const [label, setLabel] = useState("");
  const [category, setCategory] = useState("");

  const form = useFormSubmit(async () => {
    const coordinate = await createCoordinate(brandId, { dimension, label, category });
    onSaved(coordinate);
  });

  return (
    <SidePanel ariaLabel="新增座標" onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">新增座標</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="關閉側板"
          className="rounded-md p-2 text-muted-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <form
        {...form.formProps}
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void form.submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">屬於哪個維度？</span>
          <select
            value={dimension}
            onChange={(e) => setDimension(e.target.value as CoordinateDimension)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            {COORDINATE_DIMENSIONS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">座標名稱</span>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            required
            placeholder="例如「開箱直播」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">分類（選填）</span>
          <input
            type="text"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="例如「Meta 特化」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div>
          <PanelSaveButton saving={form.saving} label="新增這個座標" />
        </div>
      </form>
    </SidePanel>
  );
}
