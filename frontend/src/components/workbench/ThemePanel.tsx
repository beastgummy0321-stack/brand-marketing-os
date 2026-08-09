import { useEffect, useState, type ReactNode } from "react";
import { FolderOpen, X } from "lucide-react";
import { EmptyState } from "@/components/layout/EmptyState";
import { cn, PRESS_FEEDBACK } from "@/lib/utils";
import {
  adoptTheme,
  fetchImagePromptsCopy,
  fetchThemeDetail,
  openThemeFolder,
  SINGLE_IMAGE_CHAR_BUDGETS,
  type ThemeComponentData,
  type ThemeDetail,
} from "@/lib/workbenchApi";
import { CarouselContent } from "./CarouselContent";
import { ThemeStatusTag } from "./MatrixCell";
import { ComponentSection } from "./shared/ComponentSection";
import { CopyIconButton } from "./shared/CopyIconButton";
import { VideoContent } from "./VideoContent";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; theme: ThemeDetail };

/** 側板骨架＋單圖主題內容（畫面 3，票 17-panel-single-image）：點矩陣頁主題卡從右側滑出，
 * 不是路由跳轉——矩陣頁狀態（捲動位置、已選狀態）維持在 MatrixPage 自己的 React state，
 * 這顆元件只是疊在上面的覆蓋層，關閉時矩陣頁原封不動。
 *
 * 滑出過場：整個面板從螢幕右緣（面板固定貼右）平移＋淡入，不是 `transform-origin: center`
 * 的縮放——`entered` 這個 state 在掛載後下一幀才轉 true，讓 CSS transition 真的跑得到
 * （直接在初始 render 就給終態，瀏覽器不會播過場）。`motion-reduce` 全退化成瞬間顯示。 */
export function ThemePanel({
  brandId,
  cycleId,
  themeId,
  siblingThemeIds,
  onClose,
  onAdopted,
}: {
  brandId: string;
  cycleId: string;
  themeId: string;
  /** 同一個切角＋格式底下所有主題的 id（含 themeId 自己）：只有影片格式（票 19）用得到——
   * 要橫向比較同一切角的 3 支腳本，不能只看被點的那一個。單圖／輪播格式一律只有一個主題，
   * 這個 prop 對它們沒有作用。 */
  siblingThemeIds: string[];
  onClose: () => void;
  /** 採用成功後呼叫，讓矩陣頁把對應主題卡的狀態也標成已採用（AC：側板／矩陣頁一起更新）。 */
  onAdopted: (themeId: string) => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [entered, setEntered] = useState(false);
  const [adopting, setAdopting] = useState(false);
  const [adoptError, setAdoptError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchThemeDetail(brandId, cycleId, themeId)
      .then((theme) => {
        if (!cancelled) setState({ status: "ready", theme });
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
  }, [brandId, cycleId, themeId]);

  useEffect(() => {
    const id = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(id);
  }, []);

  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  function handleAdopt() {
    setAdopting(true);
    setAdoptError(null);
    adoptTheme(brandId, cycleId, themeId)
      .then((theme) => {
        setAdopting(false);
        setState({ status: "ready", theme });
        onAdopted(themeId);
      })
      .catch((err: unknown) => {
        setAdopting(false);
        setAdoptError(err instanceof Error ? err.message : "採用失敗，請稍後再試。");
      });
  }

  function handleComponentUpdated(updated: ThemeComponentData) {
    setState((prev) =>
      prev.status !== "ready"
        ? prev
        : {
            status: "ready",
            theme: {
              ...prev.theme,
              components: prev.theme.components.map((c) => (c.id === updated.id ? updated : c)),
            },
          },
    );
  }

  let content: ReactNode;
  if (state.status === "loading") {
    content = <EmptyState title="讀取中…" description="正在載入這個主題的完整內容。" />;
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} />;
  } else {
    const { theme } = state;
    content = (
      <>
        <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
          <div className="min-w-0">
            <h2 className="truncate font-display text-lg text-foreground" title={theme.name}>
              {theme.name}
            </h2>
            <div className="mt-1">
              <ThemeStatusTag status={theme.status} />
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={handleAdopt}
              disabled={adopting || theme.status === "adopted"}
              className="whitespace-nowrap rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {theme.status === "adopted" ? "已採用" : adopting ? "採用中…" : "採用整個主題"}
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label="關閉側板"
              className="rounded-md p-2 text-muted-foreground hover:bg-muted"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>
        {adoptError && <p className="text-xs text-danger">{adoptError}</p>}

        {theme.format_key === "single_image" ? (
          <SingleImageContent
            brandId={brandId}
            cycleId={cycleId}
            themeId={themeId}
            components={theme.components}
            onComponentUpdated={handleComponentUpdated}
          />
        ) : theme.format_key === "carousel" ? (
          <CarouselContent
            brandId={brandId}
            cycleId={cycleId}
            components={theme.components}
            onComponentUpdated={handleComponentUpdated}
          />
        ) : theme.format_key === "video" ? (
          <VideoContent
            brandId={brandId}
            cycleId={cycleId}
            themeId={themeId}
            siblingThemeIds={siblingThemeIds}
          />
        ) : (
          <EmptyState
            title="這個格式的側板內容還沒做"
            description={`格式「${theme.format_key}」的逐則內容側板還在建置中，先用上面的「採用整個主題」，或回矩陣頁看其他格式。`}
          />
        )}
      </>
    );
  }

  return (
    <>
      <div
        aria-hidden="true"
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-40 bg-foreground/20 transition-opacity duration-200 ease-out motion-reduce:duration-0 motion-reduce:transition-none",
          entered ? "opacity-100" : "opacity-0",
        )}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="主題內容側板"
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-[36rem] max-w-full flex-col gap-5 overflow-y-auto",
          "border-l border-border bg-card p-6 shadow-[var(--shadow-card)]",
          "transition-[transform,opacity] duration-[220ms] ease-[cubic-bezier(0.23,1,0.32,1)]",
          "motion-reduce:transition-none motion-reduce:duration-0",
          entered ? "translate-x-0 opacity-100" : "translate-x-full opacity-0",
        )}
      >
        {content}
      </div>
    </>
  );
}

/** 單圖主題內容：圖片提示詞×10（整組複製＋開資料夾）、文案×5／標題×5／說明×5
 * （各帶純圖示複製鈕＋退件圖示）。四段固定順序，不依賴後端 JSON 物件鍵序。 */
function SingleImageContent({
  brandId,
  cycleId,
  themeId,
  components,
  onComponentUpdated,
}: {
  brandId: string;
  cycleId: string;
  themeId: string;
  components: ThemeComponentData[];
  onComponentUpdated: (updated: ThemeComponentData) => void;
}) {
  const imagePrompts = components.filter((c) => c.component_type === "image_prompt");
  const bodies = components.filter((c) => c.component_type === "body");
  const titles = components.filter((c) => c.component_type === "title");
  const descriptions = components.filter((c) => c.component_type === "description");

  return (
    <div className="flex flex-col gap-6">
      <ComponentSection
        title="圖片提示詞"
        components={imagePrompts}
        charBudget={null}
        brandId={brandId}
        cycleId={cycleId}
        onComponentUpdated={onComponentUpdated}
        headerExtra={
          <div className="flex items-center gap-2">
            <CopyIconButton
              label="整組複製"
              ariaLabel="整組複製圖片提示詞"
              getText={async () => {
                const groups = await fetchImagePromptsCopy(brandId, cycleId, themeId);
                return groups.map((g) => g.content).join("\n\n----------\n\n");
              }}
            />
            <OpenFolderButton brandId={brandId} cycleId={cycleId} themeId={themeId} />
          </div>
        }
      />
      <ComponentSection
        title="主要文案"
        components={bodies}
        charBudget={SINGLE_IMAGE_CHAR_BUDGETS.body}
        brandId={brandId}
        cycleId={cycleId}
        onComponentUpdated={onComponentUpdated}
      />
      <ComponentSection
        title="標題"
        components={titles}
        charBudget={SINGLE_IMAGE_CHAR_BUDGETS.title}
        brandId={brandId}
        cycleId={cycleId}
        onComponentUpdated={onComponentUpdated}
      />
      <ComponentSection
        title="說明"
        components={descriptions}
        charBudget={SINGLE_IMAGE_CHAR_BUDGETS.description}
        brandId={brandId}
        cycleId={cycleId}
        onComponentUpdated={onComponentUpdated}
      />
    </div>
  );
}

/** 開資料夾按鈕：三態（idle／opening／opened／failed），不是共用元件（只有這一處用），
 * 就近寫在同一檔。伺服器端 os.startfile 開資料夾，成功不代表「複製」，不套用
 * CopyIconButton 那套複製語意，另外寫一顆小狀態機。 */
function OpenFolderButton({
  brandId,
  cycleId,
  themeId,
}: {
  brandId: string;
  cycleId: string;
  themeId: string;
}) {
  const [state, setState] = useState<"idle" | "opening" | "opened" | "failed">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleClick() {
    setState("opening");
    setErrorMessage(null);
    try {
      await openThemeFolder(brandId, cycleId, themeId);
      setState("opened");
    } catch (err) {
      setState("failed");
      setErrorMessage(err instanceof Error ? err.message : "開資料夾失敗，請稍後再試。");
    }
  }

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={handleClick}
        title={state === "failed" ? (errorMessage ?? "開資料夾") : "開資料夾"}
        className={cn(
          "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-border px-2 py-1 text-xs font-medium transition-colors hover:border-primary hover:text-primary",
          state === "failed" ? "text-danger" : "text-muted-foreground",
          PRESS_FEEDBACK,
        )}
      >
        <FolderOpen className="h-3.5 w-3.5" aria-hidden="true" />
        {state === "opened" ? "已開啟" : state === "opening" ? "開啟中…" : "開資料夾"}
      </button>
      {state === "failed" && errorMessage && (
        <span className="text-xs text-danger">{errorMessage}</span>
      )}
    </span>
  );
}
