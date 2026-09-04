# 07-1 前端 depcruise：supabase-js 只准在登入模組 import

Status: backlog。
關聯：Playwright 那一半已完成（`frontend/e2e/smoke.spec.ts`，`cd frontend && npm run e2e` 一行跑完）。

剩下 depcruise 那一條規則：跨模組只准 import 進入點，`@supabase/supabase-js` 只准出現在身分模組。證紅再算數。
