import { useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { deleteChannel, type LibraryChannel } from "@/lib/libraryApi";
import { usePagination } from "@/lib/usePagination";
import { Badge } from "../shared/Badge";
import { InlineDeleteButton } from "../shared/InlineDeleteButton";
import { ChannelPanel } from "../panels/ChannelPanel";

type PanelState = { mode: "closed" } | { mode: "new" } | { mode: "edit"; channel: LibraryChannel };

/** 自有渠道分頁（契約 S5.28–S5.31）。修改／刪除是本票新增的假設動作，見
 * `lib/libraryApi.ts` updateChannel／deleteChannel 上方註解「拿不準的點」。超過 12 列
 * 分頁（互動鐵則⑥）。 */
export function ChannelsTab({
  brandId,
  channels,
  onChanged,
}: {
  brandId: string;
  channels: LibraryChannel[];
  onChanged: () => void;
}) {
  const [panel, setPanel] = useState<PanelState>({ mode: "closed" });
  const { page, pageCount, totalCount, pageItems, goToPage, topRef } = usePagination(channels);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg text-foreground">自有渠道</h2>
        <button
          type="button"
          onClick={() => setPanel({ mode: "new" })}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          新增自有渠道
        </button>
      </div>

      {channels.length === 0 ? (
        <EmptyState title="還沒有登錄自有渠道" description="自有渠道是這個品牌自己的網站與社群帳號，之後發佈內容時會用到。" />
      ) : (
        <div ref={topRef} className="flex flex-col gap-3">
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-left text-sm">
              <thead className="bg-muted text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">類型</th>
                  <th className="px-3 py-2 font-medium">名稱</th>
                  <th className="px-3 py-2 font-medium">識別</th>
                  <th className="px-3 py-2 font-medium">狀態</th>
                  <th className="px-3 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {pageItems.map((channel) => (
                  <tr key={channel.id} className="border-t border-border align-top">
                    <td className="whitespace-nowrap px-3 py-2">
                      <Badge>{channel.channel_type_label}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-foreground">{channel.name}</td>
                    <td className="max-w-[20rem] truncate px-3 py-2 text-muted-foreground" title={channel.identifier}>
                      {channel.identifier}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <Badge>{channel.status === "active" ? "使用中" : "停用"}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <div className="flex items-center gap-3">
                        <button
                          type="button"
                          onClick={() => setPanel({ mode: "edit", channel })}
                          className="text-xs text-primary hover:underline"
                        >
                          修改
                        </button>
                        <InlineDeleteButton
                          confirmText="確定要刪除這個渠道？"
                          onDelete={async () => {
                            await deleteChannel(brandId, channel.id);
                            onChanged();
                          }}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={page} pageCount={pageCount} totalCount={totalCount} onChange={goToPage} />
        </div>
      )}

      {(panel.mode === "new" || panel.mode === "edit") && (
        <ChannelPanel
          brandId={brandId}
          channel={panel.mode === "edit" ? panel.channel : null}
          onClose={() => setPanel({ mode: "closed" })}
          onSaved={() => {
            setPanel({ mode: "closed" });
            onChanged();
          }}
        />
      )}
    </div>
  );
}
