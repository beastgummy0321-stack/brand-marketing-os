import { useEffect, useState, type ReactNode } from "react";
import { useLocation, useMatch } from "react-router-dom";
import { Topbar } from "./Topbar";
import { Sidebar } from "./Sidebar";
import { useWorkspace } from "./WorkspaceContext";

/** Below Tailwind's `md` (768px) the sidebar no longer fits beside the page (F45-I08 review: at 375px
 * it left ~77px of content). Same breakpoint as the `max-md:` classes in `Sidebar` / `Topbar`. */
const NARROW_QUERY = "(max-width: 767px)";

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window.matchMedia === "function" && window.matchMedia(NARROW_QUERY).matches,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(NARROW_QUERY);
    const update = () => setNarrow(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return narrow;
}

/** App frame. Wide: the sidebar sits beside the page and the top-bar control folds it to icons.
 * Narrow (< md, F47-I02): the sidebar is closed by default and the same control opens it as an
 * overlay over the page (closed again by the backdrop, Escape or any navigation), so the page gets
 * the full width. */
export function AppShell({ children }: { children: ReactNode }) {
  const { scope } = useWorkspace();
  const match = useMatch("/brands/:brandId/*");
  const location = useLocation();
  const brandId = match?.params.brandId ?? null;
  const narrow = useNarrow();
  const [collapsed, setCollapsed] = useState(false);
  const [overlayOpen, setOverlayOpen] = useState(false);
  useEffect(() => {
    window.scrollTo({ top: 0 });
    setOverlayOpen(false);
  }, [location.pathname]);
  useEffect(() => {
    if (!narrow) setOverlayOpen(false);
  }, [narrow]);
  useEffect(() => {
    if (!overlayOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOverlayOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [overlayOpen]);

  return (
    <div className="app-shell">
      <Sidebar brandId={brandId} collapsed={narrow ? false : collapsed} overlayOpen={overlayOpen} />
      {overlayOpen && (
        <button
          type="button"
          aria-label="關閉側欄"
          className="fixed inset-0 z-30 bg-black/30 md:hidden"
          onClick={() => setOverlayOpen(false)}
        />
      )}
      <div className="app-workspace">
        <Topbar
          brandId={brandId}
          collapsed={narrow ? !overlayOpen : collapsed}
          onToggleSidebar={() => (narrow ? setOverlayOpen(!overlayOpen) : setCollapsed(!collapsed))}
        />
        <main id="main-content" className="app-main">
          {/* Page state must not survive brand/product changes, but tab queries keep it. */}
          <div key={`${scope}:${location.pathname}`}>{children}</div>
        </main>
      </div>
    </div>
  );
}
