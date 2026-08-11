import { useState } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import { CHANNEL_TYPES, createChannel, updateChannel, type LibraryChannel } from "@/lib/libraryApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

/** 新增／編輯自有渠道側板（契約 S5.30；修改／刪除入口見 S5.31「拿不準的點」，本票先假設
 * 要補，若之後確認渠道只增不改，刪掉這顆的 `channel` 傳入分支即可）。`channel` 傳 null＝
 * 新增。 */
export function ChannelPanel({
  brandId,
  channel,
  onClose,
  onSaved,
}: {
  brandId: string;
  channel: LibraryChannel | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = channel !== null;
  const [channelType, setChannelType] = useState(channel?.channel_type ?? "website");
  const [name, setName] = useState(channel?.name ?? "");
  const [identifier, setIdentifier] = useState(channel?.identifier ?? "");
  const [status, setStatus] = useState<"active" | "inactive">(channel?.status ?? "active");

  const form = useFormSubmit(async () => {
    const fields = { channel_type: channelType, name, identifier, status };
    if (editing) await updateChannel(brandId, channel.id, fields);
    else await createChannel(brandId, fields);
    onSaved();
  });

  return (
    <SidePanel ariaLabel={editing ? "編輯自有渠道" : "新增自有渠道"} onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">{editing ? "編輯自有渠道" : "新增自有渠道"}</h2>
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
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void form.submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">渠道類型</span>
          <select
            value={channelType}
            onChange={(e) => setChannelType(e.target.value as LibraryChannel["channel_type"])}
            required
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            {CHANNEL_TYPES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">名稱</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            placeholder="例如「青原生活官方商店」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">網址或帳號</span>
          <input
            type="text"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            required
            placeholder="例如 https://example.com/store 或 @your-page"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        <fieldset className="flex flex-col gap-2 text-sm">
          <legend className="font-medium text-foreground">目前狀態？</legend>
          <label className="flex items-center gap-2">
            <input type="radio" name="status" checked={status === "active"} onChange={() => setStatus("active")} />
            使用中
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="status"
              checked={status === "inactive"}
              onChange={() => setStatus("inactive")}
            />
            停用
          </label>
        </fieldset>

        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div>
          <PanelSaveButton saving={form.saving} label={editing ? "儲存修改" : "新增這個渠道"} />
        </div>
      </form>
    </SidePanel>
  );
}
