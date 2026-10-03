import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 跟 vite.config.ts 分開一支：那支是 app 的實際執行路徑（見該檔開頭註解，Storybook 之類
// 的開發工具一律不得進去），測試用的 jsdom 環境同理不進 app 的 build config。
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.tsx', 'src/**/*.test.ts'],
    // F48 Contract R-API: every test file starts with the served ads rules seeded (no request for them).
    setupFiles: ['./src/components/ads/patterns/rulesFixture.ts'],
    // src/lib/auth.ts builds the Supabase client at import time; tests never connect, so dummy
    // values keep every test off the real .env (and CI, which has none).
    env: {
      VITE_SUPABASE_URL: 'http://localhost:54321',
      VITE_SUPABASE_ANON_KEY: 'test-anon-key',
    },
  },
});
