import { useState } from "react";
import { Link } from "react-router-dom";
import type { Cycle } from "@/lib/warroomApi";

/** 素材（S8.23-24，僅入口，S12 素材工作檯內部長相不屬本頁）。 */
export function CreativeStep({ brandId, cycle }: { brandId: string; cycle: Cycle }) {
  const [folderMsg, setFolderMsg] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <div>
        <h2 className="font-display text-lg text-foreground">這期已經有素材在準備了</h2>
        <p className="mt-1 text-sm text-muted-foreground">計畫核准當下已經在背景預生成一批素材。</p>
      </div>
      <Link
        to={`/brands/${brandId}/workbench/${cycle.id}`}
        className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
      >
        看素材
      </Link>
      <div className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
        圖不進系統，人工把生圖結果丟進素材資料夾。
        <button type="button" onClick={() => setFolderMsg("這是本機檔案總管操作，原型不模擬開啟資料夾。")} className="ml-2 text-primary hover:underline">
          開素材資料夾
        </button>
        {folderMsg && <p className="mt-1 text-xs text-muted-foreground">{folderMsg}</p>}
      </div>
    </div>
  );
}
