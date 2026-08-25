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
    include: ['src/**/*.test.tsx'],
  },
});
