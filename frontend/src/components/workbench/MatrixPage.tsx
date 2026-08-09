import { Fragment, useEffect, useState, type ReactNode } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { fetchMatrix, generateTheme, type MatrixCellRow, type MatrixFormatCell } from "@/lib/workbenchApi";
import { MatrixCell } from "./MatrixCell";
import { ThemePanel } from "./ThemePanel";

/** 欄＝格式，固定順序與比例標籤（app/creative/format_specs.py FORMAT_SPECS，比例查證日
 * 2026-08-07／08）。矩陣資料的 `formats` 物件本身用格式 key 當鍵，這份表只補人看得懂的
 * 欄名，同時把三欄的顯示順序釘死，不依賴後端 JSON 物件鍵序。 */
const FORMAT_COLUMNS: { key: string; label: string }[] = [
  { key: "single_image", label: "單圖 4:5" },
  { key: "carousel", label: "輪播 1:1" },
  { key: "video", label: "影片 9:16" },
];

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; cells: MatrixCellRow[] };

function cellKey(cellId: string, formatKey: string): string {
  return `${cellId}::${formatKey}`;
}

/** 矩陣頁（畫面2，票 16-matrix-page）：切角 × 格式全展開格線，點灰卡生成、成功轉主題卡、
 * 失敗顯示錯誤原因。生成中／錯誤是前端自己疊在格子上的畫面態（伺服器不回這兩種，見
 * workbenchApi.ts 型別註解），不進 LoadState——矩陣資料讀完之後，被點的那一格局部變化，
 * 不用整批重新讀取。 */
export function MatrixPage({ brandId, cycleId }: { brandId: string; cycleId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [generatingKeys, setGeneratingKeys] = useState<Set<string>>(new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});
  /** 側板開關（票 17）：疊在矩陣頁上的覆蓋層 state，不是路由——矩陣頁本身的捲動位置、
   * generatingKeys／errors 都原地不動，開關側板不會重新掛載這個元件。`siblingThemeIds`
   * 隨開啟動作一起記，票 19 影片側板橫向比較同一切角多支腳本要用到（見 MatrixCell 註解）。 */
  const [openPanel, setOpenPanel] = useState<{ themeId: string; siblingThemeIds: string[] } | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchMatrix(brandId, cycleId)
      .then((cells) => {
        if (!cancelled) setState({ status: "ready", cells });
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
  }, [brandId, cycleId]);

  /** 按下灰卡：當下立即轉「生成中」（不等 API 回來才變狀態），成功轉主題卡、失敗恢復灰卡
   * 並帶錯誤原因（不是靜默失敗）。這不是樂觀更新／先斬後奏——沒有假裝生成已經成功，
   * 「生成中」誠實反映「請求已送出、還在等結果」。 */
  function handleGenerate(cellId: string, formatKey: string) {
    const key = cellKey(cellId, formatKey);
    setErrors((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setGeneratingKeys((prev) => new Set(prev).add(key));

    generateTheme(brandId, cycleId, cellId, formatKey)
      .then((theme) => {
        setGeneratingKeys((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
        setState((prev) =>
          prev.status !== "ready"
            ? prev
            : {
                status: "ready",
                cells: prev.cells.map((row) =>
                  row.experiment_cell_id === cellId
                    ? {
                        ...row,
                        formats: {
                          ...row.formats,
                          [formatKey]: { state: "themed", themes: [theme] },
                        },
                      }
                    : row,
                ),
              },
        );
      })
      .catch((err: unknown) => {
        setGeneratingKeys((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
        setErrors((prev) => ({
          ...prev,
          [key]: err instanceof Error ? err.message : "生成失敗，請稍後再試。",
        }));
      });
  }

  /** 側板採用成功後，矩陣頁對應主題卡的狀態標籤也要一起變「已採用」（AC：側板／矩陣頁
   * 對應主題狀態一起更新）。不知道是哪個格子，直接找同 id 的那個就地改，其餘不動。 */
  function handleThemeAdopted(themeId: string) {
    setState((prev) => {
      if (prev.status !== "ready") return prev;
      return {
        status: "ready",
        cells: prev.cells.map((row) => {
          const formats: Record<string, MatrixFormatCell> = {};
          for (const [formatKey, cell] of Object.entries(row.formats)) {
            formats[formatKey] =
              cell.state === "themed"
                ? {
                    ...cell,
                    themes: cell.themes.map((t) =>
                      t.id === themeId ? { ...t, status: "adopted" } : t,
                    ),
                  }
                : cell;
          }
          return { ...row, formats };
        }),
      };
    });
  }

  let content: ReactNode;
  if (state.status === "loading") {
    content = <EmptyState title="讀取中…" description="正在載入這個檔期的生成矩陣。" />;
  } else if (state.status === "error") {
    content = (
      <EmptyState
        title="讀取失敗"
        description={state.message}
        actionHref={`/brands/${encodeURIComponent(brandId)}/workbench`}
        actionInternal
        actionLabel="回素材工作檯"
      />
    );
  } else if (state.cells.length === 0) {
    content = (
      <EmptyState
        title="這期檔期還沒有切角"
        description="矩陣要先有切角（實驗格）才能展開格線，請先回計畫頁設定切角。"
      />
    );
  } else {
    content = (
      <div className="overflow-x-auto">
        <div
          className="grid min-w-[46rem] items-start gap-3"
          style={{
            gridTemplateColumns: `8rem repeat(${FORMAT_COLUMNS.length}, minmax(11rem, 1fr))`,
          }}
        >
          <span aria-hidden="true" />
          {FORMAT_COLUMNS.map((col) => (
            <span key={col.key} className="text-sm font-semibold text-muted-foreground">
              {col.label}
            </span>
          ))}
          {state.cells.map((row) => (
            <Fragment key={row.experiment_cell_id}>
              <span className="flex items-center text-sm text-muted-foreground">
                {row.creative_angle}
              </span>
              {FORMAT_COLUMNS.map((col) => {
                const cell = row.formats[col.key];
                if (!cell) return <span key={col.key} aria-hidden="true" />;
                const key = cellKey(row.experiment_cell_id, col.key);
                return (
                  <MatrixCell
                    key={col.key}
                    cell={cell}
                    isGenerating={generatingKeys.has(key)}
                    errorMessage={errors[key]}
                    onGenerate={() => handleGenerate(row.experiment_cell_id, col.key)}
                    onOpenTheme={(themeId, siblingThemeIds) =>
                      setOpenPanel({ themeId, siblingThemeIds })
                    }
                  />
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb
        items={[
          { label: "跨品牌總覽", href: "/" },
          { label: "素材工作檯", href: `/brands/${encodeURIComponent(brandId)}/workbench` },
          { label: "矩陣頁" },
        ]}
      />
      <div>
        <h1 className="font-display text-2xl text-foreground">矩陣頁</h1>
        <p className="text-sm text-muted-foreground">切角 × 格式的生成矩陣，檔期 {cycleId}</p>
      </div>
      <CreativeFolderBar />
      {content}
      {openPanel && (
        <ThemePanel
          brandId={brandId}
          cycleId={cycleId}
          themeId={openPanel.themeId}
          siblingThemeIds={openPanel.siblingThemeIds}
          onClose={() => setOpenPanel(null)}
          onAdopted={handleThemeAdopted}
        />
      )}
    </div>
  );
}

/** 頂部素材資料夾入口（票 16 AC5）：後端目前只有「開單一主題資料夾」的 JSON 端點
 * （POST .../themes/{id}/folder），沒有這期檔期整包資料夾的大小／開啟端點，不得編造
 * 一個數字或另外接一支不成文的舊版路由（那支是 HTML 轉址，不是這個模組的裸 JSON
 * 慣例）。比照 QuickGenerateStub 的「按不下去、原因寫清楚」先例，先佔位等後端補。 */
function CreativeFolderBar() {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-card px-4 py-3 shadow-[var(--shadow-card)]">
      <div>
        <p className="text-sm font-medium text-foreground">素材資料夾</p>
        <p className="text-xs text-muted-foreground">
          大小：待後端補上這期檔期的資料夾端點，目前請自己到檔案總管確認。
        </p>
      </div>
      <button
        type="button"
        disabled
        title="這期檔期還沒有可以打的開資料夾端點，先留位置"
        className="shrink-0 cursor-not-allowed whitespace-nowrap rounded-md border border-dashed border-border px-4 py-2 text-sm text-muted-foreground/70"
      >
        開資料夾
      </button>
    </div>
  );
}
