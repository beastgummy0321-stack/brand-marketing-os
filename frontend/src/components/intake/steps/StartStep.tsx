import { useEffect, useState } from "react";
import type { IntakeDraft, IntakePhoto } from "@/lib/intakeApi";
import { fetchIntakeDraft, submitIntakeRestart, submitIntakeStart, uploadIntakePhoto } from "@/lib/intakeApi";
import { useFormSubmit } from "@/lib/useFormSubmit";

const URL_COUNT = 5;
const PHOTO_ACCEPT = ".jpg,.jpeg,.png,.webp";

/** 起始輸入（契約 S4.1–S4.13）。新品牌（`brandId === null`）與既有品牌重新調研（W1b）
 * 共用同一個畫面容器，只差標題與品牌名稱欄位是否顯示。 */
export function StartStep({
  brandId,
  onSubmitted,
}: {
  brandId: string | null;
  onSubmitted: (result: { brand_id: string; quick: boolean }) => void;
}) {
  const isRestart = brandId !== null;
  const [prevBrandName, setPrevBrandName] = useState<string | null>(null);
  const [prevPhotos, setPrevPhotos] = useState<IntakePhoto[]>([]);
  const [alreadyRunning, setAlreadyRunning] = useState(false);

  const [brandName, setBrandName] = useState("");
  const [clientName, setClientName] = useState("");
  const [description, setDescription] = useState("");
  const [urls, setUrls] = useState<string[]>(Array.from({ length: URL_COUNT }, () => ""));
  const [urlsOpen, setUrlsOpen] = useState(false);
  const [photos, setPhotos] = useState<IntakePhoto[]>([]);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (!isRestart || !brandId) return;
    fetchIntakeDraft(brandId)
      .then((d: IntakeDraft) => {
        setPrevBrandName(d.brand_name);
        setPrevPhotos(d.photos);
        if (!d.completed) setAlreadyRunning(true); // S4.12：已有進行中草稿，不開第二輪
      })
      .catch(() => setPrevBrandName(null));
  }, [isRestart, brandId]);

  async function handlePhotoFiles(files: FileList | null) {
    if (!files) return;
    setPhotoError(null);
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        const uploaded = await uploadIntakePhoto(file);
        setPhotos((prev) => [...prev, uploaded]);
      }
    } catch (err) {
      setPhotoError(err instanceof Error ? err.message : "上傳失敗，請稍後再試。");
    } finally {
      setUploading(false);
    }
  }

  const { saving, error, submit } = useFormSubmit(async () => {
    const trimmedUrls = urls.map((u) => u.trim());
    const photoTokens = photos.map((p) => p.token);
    if (isRestart && brandId) {
      const res = await submitIntakeRestart(brandId, { description, urls: trimmedUrls, photo_tokens: photoTokens, client_name: "" });
      onSubmitted({ brand_id: brandId, quick: res.quick });
    } else {
      if (!brandName.trim()) throw new Error("請填寫品牌名稱。");
      const res = await submitIntakeStart({
        brand_name: brandName.trim(),
        client_name: clientName.trim(),
        description,
        urls: trimmedUrls,
        photo_tokens: photoTokens,
      });
      onSubmitted(res);
    }
  });

  if (alreadyRunning && brandId) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
        這個品牌已經有進行中的建檔草稿，不會另外開一輪。
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <div>
        <h1 className="font-display text-xl text-foreground">
          {isRestart ? `重新調研：${prevBrandName ?? "…"}` : "智能引導建立品牌"}
        </h1>
      </div>

      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {!isRestart && (
          <>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-foreground">品牌名稱（必填）</span>
              <input
                type="text"
                value={brandName}
                onChange={(e) => setBrandName(e.target.value)}
                required
                className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-foreground">所屬客戶（選填，空白視為「自營」）</span>
              <input
                type="text"
                value={clientName}
                onChange={(e) => setClientName(e.target.value)}
                className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
              />
            </label>
          </>
        )}

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">描述（選填）</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
            placeholder="用幾句話描述這個品牌或產品，AI 會拿來當初掃的參考。"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        <div className="flex flex-col gap-2">
          <button type="button" onClick={() => setUrlsOpen((v) => !v)} className="self-start text-sm font-medium text-primary hover:underline">
            {urlsOpen ? "收起研究網址" : "研究網址（選填，最多 5 個）"}
          </button>
          {urlsOpen && (
            <div className="flex flex-col gap-2">
              {urls.map((u, i) => (
                <input
                  key={i}
                  type="text"
                  value={u}
                  onChange={(e) => setUrls((prev) => prev.map((v, idx) => (idx === i ? e.target.value : v)))}
                  placeholder="https://example.com/..."
                  className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
                />
              ))}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-2 text-sm">
          <span className="font-medium text-foreground">產品照（選填）</span>
          {/* B0-14 擴大修：原生 file input 的按鈕字樣跟著瀏覽器語言走，改用隱藏 input＋label 換中文按鈕 */}
          <label className={`w-fit rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground ${uploading ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:bg-muted"}`}>
            {uploading ? "上傳中…" : "選擇檔案"}
            <input
              type="file"
              accept={PHOTO_ACCEPT}
              multiple
              disabled={uploading}
              onChange={(e) => void handlePhotoFiles(e.target.files)}
              className="hidden"
            />
          </label>
          {photoError && <p className="text-danger">{photoError}</p>}
          {(prevPhotos.length > 0 || photos.length > 0) && (
            <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
              {prevPhotos.map((p, i) => (
                <li key={`prev-${i}`}>{p.name}（{p.size_mb.toFixed(1)}MB，上一輪）</li>
              ))}
              {photos.map((p, i) => (
                <li key={`new-${i}`}>
                  {p.name}（{p.size_mb.toFixed(1)}MB）
                </li>
              ))}
            </ul>
          )}
        </div>

        {error && <p className="text-sm text-danger">{error}</p>}

        <button
          type="submit"
          disabled={saving || uploading}
          className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? "處理中…" : isRestart ? "開始這一輪調研" : "建立品牌並開始初掃"}
        </button>
      </form>
    </div>
  );
}
