import type { ReactNode } from "react";
import { Topbar } from "./Topbar";
import { Sidebar } from "./Sidebar";

/** 新殼版面骨架（票 01-react-shell）：頂欄＋側欄＋內容區，固定 1440px 桌機版面
 * （決策 0038／ADR 0003，不做響應式）。內容區給後續票（02 跨品牌總覽、03 駕駛艙）填。 */
export function AppShell({ children, brandId = null }:
  { children: ReactNode; brandId?: string | null }) {
  return (
    <div className="mx-auto flex h-full w-[var(--width-shell)] flex-col overflow-hidden">
      <Topbar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar brandId={brandId} />
        <main className="flex-1 overflow-y-auto p-8">{children}</main>
      </div>
    </div>
  );
}
