import { useEffect, useState, type ReactNode } from "react";
import { useLocation, useMatch } from "react-router-dom";
import { Topbar } from "./Topbar";
import { Sidebar } from "./Sidebar";
import { useWorkspace } from "./WorkspaceContext";

export function AppShell({ children }: { children: ReactNode }) {
  const { scope } = useWorkspace();
  const match = useMatch("/brands/:brandId/*");
  const location = useLocation();
  const brandId = match?.params.brandId ?? null;
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [location.pathname]);
  return (
    <div className="app-shell">
      <Sidebar brandId={brandId} collapsed={collapsed} />
      <div className="app-workspace">
        <Topbar
          brandId={brandId}
          collapsed={collapsed}
          onToggleSidebar={() => setCollapsed(!collapsed)}
        />
        <main id="main-content" className="app-main">
          {/* Page state must not survive brand/product changes, but tab queries keep it. */}
          <div key={`${scope}:${location.pathname}`}>{children}</div>
        </main>
      </div>
    </div>
  );
}
