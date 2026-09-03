/** 票 07-1（BOARD.md）：全站只有 `src/lib/auth.ts` 准 import `@supabase/supabase-js`——
 * 那支是登入狀態的唯一出入口（見該檔開頭註解），不得散落各處各自建 client。
 * Playwright 那半（真的登入/註冊走一遍）已經在 `frontend/e2e/smoke.spec.ts` 做了，
 * 這支補靜態掃描那半：擋新程式碼直接 import supabase-js 繞過 auth.ts。 */
module.exports = {
  forbidden: [
    {
      name: "supabase-js-only-in-auth",
      severity: "error",
      comment:
        "只有 src/lib/auth.ts 可以 import @supabase/supabase-js，其他地方要透過它已經匯出的函式/hook。",
      from: { pathNot: "^src/lib/auth\\.ts$" },
      to: { path: "^node_modules/@supabase/supabase-js" },
    },
  ],
  options: {
    tsPreCompilationDeps: true,
    tsConfig: { fileName: "tsconfig.app.json" },
    doNotFollow: { path: "node_modules" },
  },
};
