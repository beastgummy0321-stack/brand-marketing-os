import { useEffect, useState } from "react";
import { apiFetch } from "./http";

/** 帶著登入權杖去拿一張需要登入才看得到的圖，換成瀏覽器畫得出來的暫時網址。
 *
 * 為什麼需要這支：`<img src="/brands/…/assets/file/…">` 是瀏覽器自己發出去的請求，它
 * **不會**帶 `Authorization` header，而那兩支圖片路由都要求登入，所以一律回 401。兩處
 * 縮圖（品牌智庫的官方素材、建檔精靈的照片）因此從來沒有真的顯示過——兩邊各自都有
 * `onError` 後備，安靜地換成「圖片載入失敗」的小圖示，所以沒人發現。2026-08-30 第 ⑥ 片
 * 的實機驗收（真的開瀏覽器上傳一張圖）才抓到，跟這個切片把檔案搬進 Supabase Storage
 * 無關——動工前那版一模一樣壞。
 *
 * 修法刻意不動後端、不動權限：改用已經會帶權杖與 `X-Org-Id` 的 `apiFetch` 把位元組抓
 * 下來，轉成 blob 網址交給 `<img>`。伺服器端「誰能看這張圖」的判斷一個字都沒改。
 *
 * ponytail: 每張圖都會真的抓下來，`loading="lazy"` 因此失去意義。官方素材一頁 12 張、
 * 建檔精靈照片是 56px 縮圖，量還小；真的變多再改成捲到才抓（IntersectionObserver）。
 */
export function useAuthedImage(url: string | undefined): { src: string | null; failed: boolean } {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(!url);

  useEffect(() => {
    if (!url) {
      setSrc(null);
      setFailed(true);
      return;
    }

    let cancelled = false;
    let objectUrl: string | null = null;
    setSrc(null);
    setFailed(false);

    void (async () => {
      try {
        const res = await apiFetch(url);
        if (!res.ok) throw new Error(`圖片讀取失敗（狀態碼 ${res.status}）`);
        const blob = await res.blob();
        const created = URL.createObjectURL(blob);
        // 元件在抓圖途中被卸載時，這個網址沒有人會再用它，當場收掉——留著就是漏記憶體，
        // 而下面那支 cleanup 早就跑完了，接不到它。
        if (cancelled) {
          URL.revokeObjectURL(created);
          return;
        }
        objectUrl = created;
        setSrc(created);
      } catch {
        // 401 不會走到這裡：`apiFetch` 自己導去登入頁，那支 promise 永遠不 resolve。
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);

  return { src, failed };
}
