import type { NativeEntity } from "@/lib/adsExternalApi";

function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
export function mediaUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; }
}
function TextFields({ fields }: { fields: Record<string, unknown> }) {
  return <>{["title", "name", "body", "message", "description", "text"].map(key => typeof fields[key] === "string" && fields[key] ? <p className="whitespace-pre-wrap break-words text-sm" key={key}>{({ title: "標題", name: "標題", body: "內文", message: "內文", description: "說明", text: "文案" } as Record<string, string>)[key]}：{String(fields[key])}</p> : null)}</>;
}
export function NativeCreativeView({ creative }: { creative: NativeEntity["creative"] }) {
  if (!creative?.kind) return <p className="text-sm text-muted-foreground">尚未讀回素材。</p>;
  const fields = creative.fields ?? {}; const story = record(fields.object_story_spec); const link = record(story.link_data); const video = record(story.video_data); const feed = record(fields.asset_feed_spec);
  const attachments = Array.isArray(link.child_attachments) ? link.child_attachments.map(record) : [];
  const feedImages = Array.isArray(feed.images) ? feed.images.map(record) : [];
  const image = mediaUrl(fields.image_url) ?? mediaUrl(link.picture);
  const thumbnail = mediaUrl(fields.thumbnail_url) ?? mediaUrl(video.image_url);
  return <div className="mt-2 flex flex-col gap-2 rounded bg-muted p-3">
    <p className="text-sm font-medium">已讀回素材：{({ image: "圖片", video: "影片", carousel: "輪播", dynamic: "動態／商品目錄", unknown: "類型未知" } as Record<string, string>)[creative.kind] ?? creative.kind}</p>
    <TextFields fields={fields} /><TextFields fields={link} /><TextFields fields={video} />
    {image && <img loading="lazy" referrerPolicy="no-referrer" className="max-h-56 max-w-full object-contain" src={image} alt="平台回傳圖片" />}
    {thumbnail && <figure><img loading="lazy" referrerPolicy="no-referrer" className="max-h-40 max-w-full object-contain" src={thumbnail} alt="平台素材縮圖" /><figcaption className="text-xs text-muted-foreground">平台縮圖，不是原檔。</figcaption></figure>}
    {creative.kind === "video" && <p className="text-sm text-warning">影片原檔尚未取得；縮圖不等於可播放影片或自帶素材版本證據。</p>}
    {attachments.length > 0 && <div className="flex max-w-full gap-3 overflow-x-auto">{attachments.map((item, i) => <div className="min-w-44 max-w-64 rounded border border-border p-2" key={i}><p className="text-xs">輪播項目 {i + 1}</p><TextFields fields={item} />{mediaUrl(item.picture) && <img loading="lazy" referrerPolicy="no-referrer" className="max-h-40 object-contain" src={mediaUrl(item.picture)!} alt={`輪播 ${i + 1} 圖片`} />}</div>)}</div>}
    {creative.kind === "dynamic" && <><p className="text-sm text-warning">動態／商品目錄素材無法完整還原，以下只列已讀回項目，不代表每次實際曝光組合。</p>{["bodies", "titles", "descriptions"].map(key => Array.isArray(feed[key]) ? <div key={key}>{feed[key].map((item, i) => <TextFields fields={record(item)} key={i} />)}</div> : null)}<div className="flex gap-3 overflow-x-auto">{feedImages.map((item, i) => mediaUrl(item.url) ? <img key={i} loading="lazy" referrerPolicy="no-referrer" className="max-h-40 object-contain" src={mediaUrl(item.url)!} alt={`動態素材圖片 ${i + 1}`} /> : <p className="text-xs" key={i}>圖片 {i + 1} 僅有識別資料，未提供可查看圖片。</p>)}</div></>}
    {!image && !thumbnail && !attachments.length && !feedImages.length && <p className="text-xs text-muted-foreground">未提供可查看圖片／縮圖；保留已取得文案，未取得部分不補造。</p>}
  </div>;
}
