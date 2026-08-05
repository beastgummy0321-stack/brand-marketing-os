import { AppShell } from "@/components/layout/AppShell";

/** 票 01-react-shell：目前只交付殼＋設計系統。跨品牌總覽（票 02）、駕駛艙（票 03）
 * 會把這裡換成真正的內容；在那之前用空狀態卡片說明「這頁幹嘛＋第一步」（規格故事 21）。 */
function App() {
  return (
    <AppShell>
      <div className="flex h-full flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-card p-12 text-center shadow-[var(--shadow-card)]">
        <h1 className="font-display text-2xl text-foreground">跨品牌總覽即將上線</h1>
        <p className="max-w-md text-sm text-muted-foreground">
          這裡之後會放每個品牌的健康度卡片。過渡期間，先用舊版頁面查看與操作品牌。
        </p>
        <a
          href="/"
          className="mt-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          前往舊版品牌總覽
        </a>
      </div>
    </AppShell>
  );
}

export default App;
