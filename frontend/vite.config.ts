import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// production 由 FastAPI StaticFiles 掛載於 /app 路徑（票 01-react-shell）
// Storybook 只進 devDependencies（票 v3-fluid-cards-storybook），不得進這支 app 執行路徑的 config
// https://vite.dev/config/
export default defineConfig({
  base: '/app/',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  build: {
    outDir: 'dist'
  }
});