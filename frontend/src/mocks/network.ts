/** 假 fetch 攔截器（票 B1-inbox／B1-settings，畫面契約第十二節：「假資料只准放一個目錄、
 * 只有一個入口」）。原生 `window.fetch` monkey-patch——不裝 MSW 之類的函式庫，這個專案
 * 目前只需要攔幾支固定路徑，装依賴換不到更少的程式碼。沒對到的路徑一律放行給真正的
 * `fetch`，不影響其他已經接真後端的頁面（跨品牌總覽、駕駛艙、素材工作檯）。 */
import { getActionFailure, getReadFailure, getScenario } from "./state";

export interface MockRoute {
  method: string;
  pattern: RegExp;
  handler: (match: RegExpMatchArray, init?: RequestInit) => Promise<Response> | Response;
}

const routes: MockRoute[] = [];
let installed = false;

export function registerRoute(
  method: string,
  pattern: RegExp,
  handler: MockRoute["handler"],
): void {
  routes.push({ method: method.toUpperCase(), pattern, handler });
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

// 側板（S2.15 詳情）的 GET 歸「動作失敗」開關管，不歸「讀取失敗」開關管：這樣才能單獨
// 展示側板讀取失敗（S2.18）而不連帶把整頁列表也弄壞，也不用為此再多開第三顆開關。
const SIDE_PANEL_PATH = /^\/api\/system\/prototype-phase$/;

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
      // 進行中態（S2.20／S15 整頁骨架）：GET 請求掛著不回應，讓畫面停在骨架卡片。
      if (getScenario() === "loading") return new Promise<Response>(() => {});
      const failing = SIDE_PANEL_PATH.test(path) ? getActionFailure() : getReadFailure();
      if (failing) return errorResponse(500, "模擬讀取失敗");
      return route.handler(match, init);
    }

    // POST／寫入動作：固定加一點延遲，讓「送出中鎖按鈕」看得到；「進行中」情境不影響個別
    // 動作（那是整頁首次讀取的展示，跟送出中是兩件事）。
    await new Promise((resolve) => setTimeout(resolve, 400));
    if (getActionFailure()) return errorResponse(500, "模擬儲存失敗");
    return route.handler(match, init);
  };
}
