/** 假 fetch 攔截器（票 B3-intake，畫面契約第十二節：「假資料只准放一個目錄、只有一個
 * 入口」）。原生 `window.fetch` monkey-patch，沿用 B1／B2 已驗證過的寫法
 * （`git show 6cb61e6:frontend/src/mocks/network.ts`）——這個專案只需要攔幾支固定路徑，
 * 裝依賴換不到更少的程式碼。沒對到的路徑一律放行給真正的 `fetch`，不影響已經接真後端的
 * 頁面（跨品牌總覽、收件匣、設定、駕駛艙、品牌智庫、產品、素材工作檯）。
 *
 * B3 沒有「側板 GET 歸動作失敗管」的例外（B1／B2 有：詳情側板、永久刪除側板）——本票
 * 唯一的側板（花費上限）不打自己的 GET，資料來自整包草稿讀取，不需要這個例外機制，照
 * YAGNI 不搬過來。 */
import { getActionFailure, getReadFailure, getScenario } from "./state";

export interface MockRoute {
  method: string;
  pattern: RegExp;
  handler: (match: RegExpMatchArray, init?: RequestInit) => Promise<Response> | Response;
  /** 背景工作啟動端點自己決定成功或失敗（依它自己的超限判斷），不讓這裡先攔截。 */
  skipAutoFail?: boolean;
}

const routes: MockRoute[] = [];
let installed = false;

export function registerRoute(
  method: string,
  pattern: RegExp,
  handler: MockRoute["handler"],
  options?: { skipAutoFail?: boolean },
): void {
  routes.push({ method: method.toUpperCase(), pattern, handler, skipAutoFail: options?.skipAutoFail ?? false });
}

export function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function errorResponse(status = 500, message = "模擬錯誤"): Response {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function envelope<T>(data: T): { data: T; generated_at: string } {
  return { data, generated_at: new Date().toISOString() };
}

function requestPath(input: RequestInfo | URL): string {
  const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
  return url.startsWith("http") ? new URL(url).pathname : url.split("?")[0];
}

export function installMockFetch(): void {
  if (installed) return;
  installed = true;
  const originalFetch = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const path = requestPath(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const route = routes.find((r) => r.method === method && r.pattern.test(path));
    if (!route) return originalFetch(input, init);

    const match = path.match(route.pattern)!;

    if (method === "GET") {
      // 進行中態（整頁骨架）：GET 請求掛著不回應，讓畫面停在骨架卡片。
      if (getScenario() === "loading") return new Promise<Response>(() => {});
      if (getReadFailure()) return errorResponse(500, "模擬讀取失敗");
      return route.handler(match, init);
    }

    // POST／寫入動作：固定加一點延遲，讓「送出中鎖按鈕」看得到。
    await new Promise((resolve) => setTimeout(resolve, 400));
    if (!route.skipAutoFail && getActionFailure()) return errorResponse(500, "模擬儲存失敗");
    return route.handler(match, init);
  };
}
