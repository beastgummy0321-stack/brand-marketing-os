import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { EmptyState } from "@/components/layout/EmptyState";
import { cn, PRESS_FEEDBACK } from "@/lib/utils";
import {
  combineVideoScript,
  fetchThemeDetail,
  parseVideoScript,
  VIDEO_CHAR_BUDGETS,
  type ThemeComponentData,
  type ThemeDetail,
  type VideoScript,
} from "@/lib/workbenchApi";
import { ComponentSection } from "./shared/ComponentSection";
import { CopyIconButton } from "./shared/CopyIconButton";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; siblings: ThemeDetail[] };

interface ScriptEntry {
  theme: ThemeDetail;
  parsed: VideoScript;
}

/** 影片主題內容（畫面 5，票 19-panel-video）：這個切角所有影片腳本（各自一個主題，票 08
 * 「腳本＝主題」）＋切角層共用的 10 個 Hook 池，選一支腳本＋一個 Hook 才能複製套入插槽的
 * 完整腳本文字。
 *
 * 3 支腳本各自獨立抓（Promise.all 對 `siblingThemeIds` 逐一打既有 `fetchThemeDetail`），
 * 不是新端點——矩陣頁的 `GET .../matrix` 只給 id/name/status 摘要（見 workbenchApi.ts
 * MatrixTheme），逐則內容要逐個主題各打一次。這跟 SingleImageContent／CarouselContent
 * 直接吃 ThemePanel 已抓好的單一 `components` 不同，是因為影片側板天生要橫向比較同一切角
 * 的多支腳本，不是只看被點的那一個。
 *
 * 「複製完整腳本」打 `POST .../combine-script`（票 23，`app/ads/routes_creative_theme.py
 * combine_video_script_route()`），純轉發後端 `render_video_script_text()` 組好的內容，
 * 前端不重算組字邏輯（那會變成兩處要同步，規格表一改這裡就悄悄跟丟）。 */
export function VideoContent({
  brandId,
  cycleId,
  themeId,
  siblingThemeIds,
}: {
  brandId: string;
  cycleId: string;
  themeId: string;
  /** 同一個切角底下所有影片格式主題的 id（含 themeId 自己），來源是矩陣頁已經抓到的摘要
   * 清單（MatrixCell 的 `cell.themes`），不是另一支端點。 */
  siblingThemeIds: string[];
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [selectedScriptId, setSelectedScriptId] = useState(themeId);
  const [selectedHookId, setSelectedHookId] = useState<string | null>(null);

  const ids = siblingThemeIds.length > 0 ? siblingThemeIds : [themeId];
  const idsKey = ids.join(",");

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    Promise.all(ids.map((id) => fetchThemeDetail(brandId, cycleId, id)))
      .then((siblings) => {
        if (!cancelled) setState({ status: "ready", siblings });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
          });
        }
      });
    return () => {
      cancelled = true;
    };
    // ids 用 idsKey 這個穩定字串當依賴，siblingThemeIds 陣列參照本身不必然穩定。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, cycleId, idsKey]);

  function updateComponent(scriptThemeId: string, updated: ThemeComponentData) {
    setState((prev) =>
      prev.status !== "ready"
        ? prev
        : {
            status: "ready",
            siblings: prev.siblings.map((t) =>
              t.id === scriptThemeId
                ? { ...t, components: t.components.map((c) => (c.id === updated.id ? updated : c)) }
                : t,
            ),
          },
    );
  }

  if (state.status === "loading") {
    return <EmptyState title="讀取中…" description="正在載入這個切角的影片腳本與 Hook 池。" />;
  }
  if (state.status === "error") {
    return <EmptyState title="讀取失敗" description={state.message} />;
  }

  const { siblings } = state;

  const scripts: ScriptEntry[] = [];
  for (const theme of siblings) {
    const scriptComponent = theme.components.find((c) => c.component_type === "script");
    const parsed = scriptComponent ? parseVideoScript(scriptComponent.content) : null;
    if (parsed) scripts.push({ theme, parsed });
  }

  const hookPool: ThemeComponentData[] = siblings.flatMap((theme) =>
    theme.components.filter((c) => c.component_type === "hook_pool"),
  );

  const selectedScript = scripts.find((s) => s.theme.id === selectedScriptId) ?? scripts[0];
  const selectedHook = hookPool.find((h) => h.id === selectedHookId);
  const canCombine = !!selectedScript && !!selectedHook;
  const activeSibling = selectedScript?.theme;

  function handleActiveComponentUpdated(updated: ThemeComponentData) {
    if (activeSibling) updateComponent(activeSibling.id, updated);
  }

  const bodies = activeSibling?.components.filter((c) => c.component_type === "body") ?? [];
  const titles = activeSibling?.components.filter((c) => c.component_type === "title") ?? [];
  const descriptions = activeSibling?.components.filter((c) => c.component_type === "description") ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-foreground">腳本（{scripts.length}）</h3>
        <div role="radiogroup" aria-label="選擇腳本" className="flex flex-col gap-2">
          {scripts.map(({ theme, parsed }) => {
            const selected = theme.id === selectedScriptId;
            return (
              <button
                key={theme.id}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => setSelectedScriptId(theme.id)}
                className={cn(
                  "flex items-start justify-between gap-3 rounded-md border px-3 py-2 text-left",
                  selected ? "border-primary bg-primary/10" : "border-border hover:border-primary",
                  PRESS_FEEDBACK,
                )}
              >
                <div className="min-w-0">
                  <span className="inline-block rounded-full border border-border bg-card px-2 py-0.5 text-xs font-medium text-foreground">
                    {parsed.framework}
                  </span>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {parsed.segments.map((seg) => seg.label).join(" → ")}
                  </p>
                </div>
                <span
                  className={cn(
                    "flex shrink-0 items-center gap-1 text-xs font-medium",
                    selected ? "text-primary" : "text-muted-foreground",
                  )}
                >
                  {selected && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
                  {selected ? "已選這支" : "選這支"}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-foreground">
          Hook 池（{hookPool.length}／切角共用）
        </h3>
        <div role="radiogroup" aria-label="選擇 Hook" className="flex flex-wrap gap-2">
          {hookPool.map((hook) => {
            const selected = hook.id === selectedHookId;
            return (
              <button
                key={hook.id}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => setSelectedHookId(hook.id)}
                title={hook.content}
                className={cn(
                  "max-w-[16rem] truncate rounded-full border px-3 py-1 text-xs font-medium",
                  selected
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-foreground hover:border-primary",
                  PRESS_FEEDBACK,
                )}
              >
                #{hook.sequence} {hook.content}
              </button>
            );
          })}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-muted/30 p-4">
        {canCombine ? (
          <>
            <p className="text-sm text-foreground">
              已選：<strong>{selectedScript.parsed.framework}</strong>＋
              <strong>Hook #{selectedHook.sequence}</strong>，套入插槽即可輸出完整腳本。
            </p>
            <CopyIconButton
              className="mt-2"
              label="複製完整腳本"
              ariaLabel="複製完整腳本"
              getText={() =>
                combineVideoScript(brandId, cycleId, selectedScript.theme.id, selectedHook.id)
              }
            />
          </>
        ) : (
          <p className="text-sm text-muted-foreground">先選一支腳本＋一個 Hook，才能產生完整腳本。</p>
        )}
      </div>

      <ComponentSection
        title="主要文案"
        components={bodies}
        charBudget={VIDEO_CHAR_BUDGETS.body}
        brandId={brandId}
        cycleId={cycleId}
        onComponentUpdated={handleActiveComponentUpdated}
      />
      <ComponentSection
        title="標題"
        components={titles}
        charBudget={VIDEO_CHAR_BUDGETS.title}
        brandId={brandId}
        cycleId={cycleId}
        onComponentUpdated={handleActiveComponentUpdated}
      />
      <ComponentSection
        title="說明"
        components={descriptions}
        charBudget={VIDEO_CHAR_BUDGETS.description}
        brandId={brandId}
        cycleId={cycleId}
        onComponentUpdated={handleActiveComponentUpdated}
      />
    </div>
  );
}
