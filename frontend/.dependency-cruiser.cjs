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
    {
      name: "feature-internals-are-private",
      severity: "error",
      comment:
        "ADR 0060：src/components/<功能>/ 之間只准 import 對方的 index.ts；layout 是共用零件櫃，全站可直接拿。",
      from: { path: "^src/components/([^/]+)/" },
      to: {
        path: "^src/components/[^/]+/",
        pathNot: [
          "^src/components/$1/",
          "^src/components/layout/",
          "^src/components/[^/]+/index\\.tsx?$",
        ],
      },
    },
    {
      name: "outsiders-use-the-front-door-too",
      severity: "error",
      comment:
        "ADR 0060：src/components/ 外面的檔案（src/lib/、測試、任何新目錄）一樣只准走功能的 index.ts。少了這條，一行轉出檔就能把上面那條規則整個繞過去。",
      from: { pathNot: ["^src/components/[^/]+/", "^src/App\\.tsx$", "^node_modules/"] },
      to: {
        path: "^src/components/[^/]+/",
        pathNot: [
          "^src/components/layout/",
          "^src/components/[^/]+/index\\.tsx?$",
        ],
      },
    },
    {
      name: "only-main-imports-the-app-shell",
      severity: "error",
      comment:
        "ADR 0060：只有 src/main.tsx 准 import src/App.tsx。App.tsx 是唯一有資格認得每一個功能的檔（路由總表），所以它自己必須是死路，不然它就成了新的轉手站。",
      from: { pathNot: ["^src/main\\.tsx$", "^node_modules/"] },
      to: { path: "^src/App\\.tsx$" },
    },
  ],
  options: {
    tsPreCompilationDeps: true,
    tsConfig: { fileName: "tsconfig.app.json" },
    doNotFollow: { path: "node_modules" },
  },
};
