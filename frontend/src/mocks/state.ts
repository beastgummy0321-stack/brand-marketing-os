/** 假資料層的可切換狀態（票 B1-inbox／B1-settings，畫面契約第四節「四態在原型上做成可
 * 切換的開關」）。跟主 app 程式碼零耦合——只有 `mocks/` 內部檔案會讀寫這裡。
 *
 * 已掛載的頁面只在掛載那一刻讀一次資料（`useEffect(load, [])`，跟真後端接線後的行為
 * 一致），切開關不會讓它們自動重讀——這是刻意的：讓頁面訂閱假資料層的開關會把 app
 * 程式碼跟 mocks/ 綁在一起，違反「app 只有一條真實請求路徑」。改用瀏覽器原生
 * `sessionStorage` 記住選擇，`DevScenarioToggle` 切換後自己 `location.reload()`——
 * 重新整理後這裡從 sessionStorage 復原剛選的狀態，頁面用原本的掛載流程自然讀到新資料。 */

export type MockScenario = "normal" | "empty" | "loading";
export type ApiKeySourceVariant = "env" | "db" | null;

type Listener = () => void;

const SCENARIO_KEY = "mock-scenario";
const API_KEY_SOURCE_KEY = "mock-api-key-source";
// 失敗拆成兩個獨立開關（不是「四態」裡的一個互斥選項）：讀取失敗只管 GET，動作失敗只管
// POST，兩顆可以各自開關、也可以同時開，這樣才點得到「GET 正常、POST 失敗」這種畫面
// （S2.9/S2.10 送出失敗、S15 任一小節單獨送出失敗）。
const READ_FAILURE_KEY = "mock-read-failure";
const ACTION_FAILURE_KEY = "mock-action-failure";

function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = sessionStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

function writeStored(key: string, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // sessionStorage 不可用（例如隱私模式）：退化成只在記憶體內生效，不影響其他功能。
  }
}

let scenario: MockScenario = readStored(SCENARIO_KEY, "normal");
let apiKeySource: ApiKeySourceVariant = readStored(API_KEY_SOURCE_KEY, "env");
let readFailure: boolean = readStored(READ_FAILURE_KEY, false);
let actionFailure: boolean = readStored(ACTION_FAILURE_KEY, false);
const listeners = new Set<Listener>();

function notify(): void {
  listeners.forEach((fn) => fn());
}

export function getScenario(): MockScenario {
  return scenario;
}

export function setScenario(next: MockScenario): void {
  scenario = next;
  writeStored(SCENARIO_KEY, next);
  notify();
}

export function getApiKeySource(): ApiKeySourceVariant {
  return apiKeySource;
}

export function setApiKeySource(next: ApiKeySourceVariant): void {
  apiKeySource = next;
  writeStored(API_KEY_SOURCE_KEY, next);
  notify();
}

export function getReadFailure(): boolean {
  return readFailure;
}

export function setReadFailure(next: boolean): void {
  readFailure = next;
  writeStored(READ_FAILURE_KEY, next);
  notify();
}

export function getActionFailure(): boolean {
  return actionFailure;
}

export function setActionFailure(next: boolean): void {
  actionFailure = next;
  writeStored(ACTION_FAILURE_KEY, next);
  notify();
}

export function subscribeMockState(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
