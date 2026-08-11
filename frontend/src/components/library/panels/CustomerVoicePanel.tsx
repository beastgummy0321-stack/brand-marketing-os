import { useState } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import { CUSTOMER_VOICE_CHANNELS, submitCustomerVoice } from "@/lib/libraryApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

/** 貼入顧客原話側板（契約 S5.39）：送出後立即關閉，不等 AI 抽取完成（S5.40，五鐵則③）——
 * `onSubmitted` 把 job_key 交給 `CustomerVoiceTab` 去接手佔位卡與輪詢，這顆側板本身送出
 * 成功就功成身退。 */
export function CustomerVoicePanel({
  brandId,
  onClose,
  onSubmitted,
  onOpenGuide,
}: {
  brandId: string;
  onClose: () => void;
  onSubmitted: (jobKey: string, sourceChannel: string) => void;
  onOpenGuide: () => void;
}) {
  const [sourceChannel, setSourceChannel] = useState("");
  const [sourceDetail, setSourceDetail] = useState("");
  const [rawText, setRawText] = useState("");

  const form = useFormSubmit(async () => {
    const { job_key } = await submitCustomerVoice(brandId, {
      source_channel: sourceChannel,
      source_detail: sourceDetail,
      raw_text: rawText,
    });
    onSubmitted(job_key, sourceChannel);
    onClose();
  });

  return (
    <SidePanel ariaLabel="貼入顧客原話" onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">貼入顧客原話</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="關閉側板"
          className="rounded-md p-2 text-muted-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <p className="text-sm text-muted-foreground">
        把一段評論、留言或客服對話整段貼上，AI 會抽出裡面的痛點與用語，保留原文用詞並標出處。不知道去哪找？{" "}
        <button type="button" onClick={onOpenGuide} className="text-primary underline-offset-4 hover:underline">
          看在地化指引
        </button>
      </p>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void form.submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">這段原話是從哪裡來的？</span>
          <select
            value={sourceChannel}
            onChange={(e) => setSourceChannel(e.target.value)}
            required
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="" disabled>
              請選擇
            </option>
            {CUSTOMER_VOICE_CHANNELS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">出處細節（選填）</span>
          <input
            type="text"
            value={sourceDetail}
            onChange={(e) => setSourceDetail(e.target.value)}
            placeholder="例如「XX保健品 momo 評論區，2026-07」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">原文全文</span>
          <textarea
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            required
            rows={8}
            placeholder="貼上顧客的評論、留言或客服對話原文……"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div>
          <PanelSaveButton saving={form.saving} label="送出，讓 AI 抽重點" pendingLabel="送出中…" />
        </div>
      </form>
    </SidePanel>
  );
}
