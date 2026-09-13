import { Component, type ErrorInfo, type ReactNode } from "react";

import { EmptyState } from "./EmptyState";

/** F04-I24：全站唯一一顆路由層 error boundary。React 的 error boundary 只能是 class
 * component（`static getDerivedStateFromError` + `componentDidCatch`），這是唯一寫法。
 * 沒有畫面可以死——一個未預期例外要變成「這一頁壞了」卡片，不是白畫面（演練四，
 * 策略頁自訂預算白畫面）。掛在 `App.tsx` 的 `AppShell` 內、以 `location.pathname` 當
 * `key`，讓使用者點側欄走去別頁時自動重生。 */
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: unknown): { error: Error } {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <EmptyState
          title="這一頁壞了"
          description={this.state.error.message || "畫面在顯示這份資料時出錯了。"}
          actionLabel="重新載入"
          onAction={() => window.location.reload()}
        />
      );
    }
    return this.props.children;
  }
}
