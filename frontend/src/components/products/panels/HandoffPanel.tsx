import { formatUsd } from "@/lib/format";
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { CopyIconButton } from "@/components/layout/CopyIconButton";
import { SidePanel } from "@/components/layout/SidePanel";
import {
  COST_PRODUCT_HANDOFF_FIX,
  fetchProductHandoffPrompt,
  submitProductHandoff,
} from "@/lib/productsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

/** 調研交接包側板（契約 S6.40–S6.48）：複製提示詞給外部 AI → 貼回解析。貼回優先走免費的
 * 直接解析；解析失敗才會呼叫 AI 修復格式（單次同步請求，不進背景——見契約「這題碰系統
 * 哪裡」說明）。 */
export function HandoffPanel({
  brandId,
  productId,
  onClose,
  onSaved,
}: {
  brandId: string;
  productId: string;
  onClose: () => void;
  onSaved: (addedCount: number) => void;
}) {
  const [promptText, setPromptText] = useState<string | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);
  const [replyText, setReplyText] = useState("");

  useEffect(() => {
    fetchProductHandoffPrompt(brandId, productId)
      .then((res) => setPromptText(res.prompt_text))
      .catch((err: unknown) => setPromptError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。"));
  }, [brandId, productId]);

  const form = useFormSubmit(async () => {
    const { added_count } = await submitProductHandoff(brandId, productId, replyText);
    onSaved(added_count);
  });

  return (
    <SidePanel ariaLabel="調研交接包" onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">調研交接包</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="關閉側板"
          className="rounded-md p-2 text-muted-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
        <li>複製下面的提示詞</li>
        <li>帶去外部 AI（例如 ChatGPT）問一次</li>
        <li>把 AI 的回覆貼回下面的欄位</li>
      </ol>

      <div className="flex flex-col gap-2">
        {promptError ? (
          <p className="text-sm text-danger">{promptError}</p>
        ) : (
          <textarea
            readOnly
            value={promptText ?? "讀取中…"}
            rows={6}
            className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-foreground"
          />
        )}
        <div>
          <CopyIconButton
            label="整段複製"
            ariaLabel="整段複製提示詞"
            disabled={!promptText}
            getText={() => promptText ?? ""}
            className="px-3 py-1.5 text-foreground"
          />
        </div>
      </div>

      <form
        className="flex flex-col gap-4"
        {...form.formProps}
        onSubmit={(e) => {
          e.preventDefault();
          void form.submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">貼上外部 AI 的回覆</span>
          <textarea
            value={replyText}
            onChange={(e) => setReplyText(e.target.value)}
            rows={8}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <span className="text-xs text-muted-foreground">
            先嘗試自動讀取（不需費用）；讀取失敗才會請 AI 協助整理格式（預估 {formatUsd(COST_PRODUCT_HANDOFF_FIX)}，受花費上限保護）。
          </span>
        </label>
        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div>
          <PanelSaveButton saving={form.saving} label="送出，讀進來" pendingLabel="讀取中…" />
        </div>
      </form>
    </SidePanel>
  );
}
