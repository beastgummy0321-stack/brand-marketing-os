import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { assetBlob } from "@/lib/adsUserAssetsApi";

export function AuthAssetMedia({ brandId, assetId, filename, mime, duration, autoPreview = false }: { brandId: string; assetId: string; filename: string; mime: string; duration?: number | null; autoPreview?: boolean }) {
  const [show, setShow] = useState(autoPreview); const [url, setUrl] = useState("");
  const [error, setError] = useState(""); const [downloading, setDownloading] = useState(false);
  useEffect(() => {
    if (!show) return;
    const controller = new AbortController(); let objectUrl = "";
    setUrl(""); setError("");
    assetBlob(brandId, assetId, "preview", controller.signal).then(blob => {
      if (controller.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob); setUrl(objectUrl);
    }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "預覽尚未完成。"); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [brandId, assetId, show]);
  const downloadController = useRef<AbortController | null>(null);
  useEffect(() => {
    setShow(autoPreview); setUrl(""); setError(""); setDownloading(false);
    return () => downloadController.current?.abort();
  }, [brandId, assetId, autoPreview]);
  async function download() {
    downloadController.current?.abort();
    const controller = new AbortController(); downloadController.current = controller;
    setDownloading(true); setError("");
    try {
      const blob = await assetBlob(brandId, assetId, "download", controller.signal);
      if (controller.signal.aborted) return;
      const link = document.createElement("a"); const objectUrl = URL.createObjectURL(blob);
      link.href = objectUrl; link.download = filename; link.click();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "下載失敗。"); }
    finally { if (!controller.signal.aborted) setDownloading(false); }
  }
  return <div className="flex flex-col gap-2"><div className="flex gap-2"><Button variant="outline" size="sm" onClick={() => setShow(v => !v)}>{show ? "收起預覽" : "查看預覽"}</Button><Button variant="outline" size="sm" busy={downloading} onClick={() => void download()}>{downloading ? "取得原檔中…" : "下載原檔"}</Button></div>
    {show && <div>{!url && !error && <p role="status">預覽讀取中…</p>}{url && (mime.startsWith("video/") ? <><video className="max-h-64 w-full rounded" src={url} controls preload="metadata" /><p className="text-xs text-muted-foreground">預覽片段（最多前 15 秒）；原始時長 {duration == null ? "未知" : `${duration} 秒`}。下載原檔保留完整內容。</p></> : <img className="max-h-64 max-w-full rounded object-contain" src={url} alt={filename} />)}</div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </div>;
}
