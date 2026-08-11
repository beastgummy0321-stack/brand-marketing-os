import { useState } from "react";
import type { IntakeDraft } from "@/lib/intakeApi";
import { COST_PASTE_FIX, fetchPasteFixStatus, resolvePasteScope, startPasteFix, validatePaste } from "@/lib/intakeApi";
import { IntakeJobRow } from "../shared/IntakeJobRow";
import { LimitCard } from "../shared/LimitCard";
import { useIntakeJob } from "../useIntakeJob";
import { ReviewPanel } from "./ReviewPanel";

const FILE_ACCEPT = ".md,.txt";

/** 貼回（契約 S4.46–S4.57）＋緊接其後的待處理清單（S4.58–S4.66，見 `ReviewPanel.tsx`）。
 * 有待處理清單就直接顯示清單（S4.76 續接：只到清單層級，契約的草稿形狀本來就只存
 * `pending_item_count`，沒有存「上次看到第幾筆」）；否則顯示貼上表單。 */
export function PasteStep({ brandId, draft, onRefresh }: { brandId: string; draft: IntakeDraft; onRefresh: () => void }) {
  if (draft.pending_item_count > 0) {
    return <ReviewPanel brandId={brandId} knownProducts={draft.created_product_names} onRefresh={onRefresh} />;
  }
  return <PasteForm brandId={brandId} draft={draft} onRefresh={onRefresh} />;
}

function PasteForm({ brandId, draft, onRefresh }: { brandId: string; draft: IntakeDraft; onRefresh: () => void }) {
  const [rawText, setRawText] = useState(draft.paste_raw);
  const [fileError, setFileError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [dataLineCount, setDataLineCount] = useState<number | null>(null);
  const [resolvingScope, setResolvingScope] = useState<string | null>(null);

  const { job: fixJob, limitBlock: fixLimitBlock, raising: fixRaising, retry: fixRetry, raise: fixRaise } = useIntakeJob(
    brandId,
    "paste_fix",
    false, // 使用者按鈕觸發，不自動開始
    () => startPasteFix(brandId),
    () => fetchPasteFixStatus(brandId),
    onRefresh,
  );

  async function handleFile(file: File | null) {
    if (!file) return;
    setFileError(null);
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!["md", "txt"].includes(ext)) {
      setFileError(`「${file.name}」不是支援的檔案格式，請上傳 .md 或 .txt 檔。`);
      return;
    }
    setRawText(await file.text());
  }

  async function handleValidate() {
    if (!rawText.trim()) {
      setFormError("請先貼上 AI 給你的表格內容。");
      return;
    }
    setValidating(true);
    setFormError(null);
    try {
      const res = await validatePaste(brandId, rawText);
      setDataLineCount(res.data_line_count);
      onRefresh(); // 成功或失敗都要重讀草稿：成功會拿到 pending_item_count，失敗會拿到 paste_errors
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "檢查失敗，請稍後再試。");
    } finally {
      setValidating(false);
    }
  }

  async function handleResolveScope(scopeName: string, action: "create_product" | "assign_brand") {
    setResolvingScope(scopeName);
    try {
      await resolvePasteScope(brandId, { scope_name: scopeName, action });
      onRefresh();
    } finally {
      setResolvingScope(null);
    }
  }

  const errors = draft.paste_errors;
  const hasTableError = errors.some((e) => e.line === null);

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <div>
        <h2 className="font-display text-lg text-foreground">把 AI 給你的表格貼回來</h2>
        <p className="text-sm text-muted-foreground">整段貼上就好，包含第一列的欄位名。系統會先自動檢查格式，此步驟不需費用。</p>
      </div>

      <textarea
        value={rawText}
        onChange={(e) => setRawText(e.target.value)}
        rows={10}
        placeholder="種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源"
        className="w-full rounded-md border border-border px-3 py-2 font-mono text-xs text-foreground"
      />

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">或上傳外部 AI 匯出的檔案（.md／.txt），有檔案以檔案內容為準</span>
        <input type="file" accept={FILE_ACCEPT} onChange={(e) => void handleFile(e.target.files?.[0] ?? null)} className="text-sm text-muted-foreground" />
      </label>
      {fileError && <p className="text-sm text-danger">{fileError}</p>}

      {formError && <p className="text-sm text-danger">{formError}</p>}

      <button
        type="button"
        disabled={validating}
        onClick={() => void handleValidate()}
        className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {validating ? "處理中…" : "檢查並讀進來"}
      </button>

      {errors.length > 0 && (
        <div className="flex flex-col gap-2 rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
          {hasTableError ? (
            <p className="text-danger">{errors[0].msg}</p>
          ) : (
            <>
              <p className="text-danger">
                有 {errors.length} 列讀不進來，其餘 {Math.max(0, (dataLineCount ?? errors.length) - errors.length)} 列沒問題
              </p>
              <ul className="flex flex-col gap-2">
                {errors.map((e, i) => (
                  <li key={i} className="flex flex-col gap-1">
                    <span className="text-foreground">{e.msg}</span>
                    {e.unknown_scope && (
                      <div className="flex gap-2">
                        <button
                          type="button"
                          disabled={resolvingScope === e.unknown_scope}
                          onClick={() => void handleResolveScope(e.unknown_scope!, "create_product")}
                          className="rounded-md border border-border px-2 py-1 text-xs text-foreground hover:border-primary hover:text-primary"
                        >
                          建立成新產品
                        </button>
                        <button
                          type="button"
                          disabled={resolvingScope === e.unknown_scope}
                          onClick={() => void handleResolveScope(e.unknown_scope!, "assign_brand")}
                          className="rounded-md border border-border px-2 py-1 text-xs text-foreground hover:border-primary hover:text-primary"
                        >
                          歸到整個品牌
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}

          {fixLimitBlock ? (
            <LimitCard block={fixLimitBlock} raising={fixRaising} onRaise={() => void fixRaise()} onSkipRemaining={() => onRefresh()} />
          ) : fixJob ? (
            <IntakeJobRow
              job={fixJob}
              runningLabel="AI 正在整理格式"
              actions={[
                { label: "再試一次", onClick: () => void fixRetry() },
                { label: "跳過這一步", onClick: () => onRefresh() },
                { label: "前往設定頁", onClick: () => window.location.assign("/app/settings") },
              ]}
            />
          ) : (
            <button
              type="button"
              onClick={() => void fixRetry()}
              className="self-start rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10"
            >
              請 AI 幫我整理格式（預估 US${COST_PASTE_FIX.toFixed(2)}）
            </button>
          )}
        </div>
      )}
    </div>
  );
}
