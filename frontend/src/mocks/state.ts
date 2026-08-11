/** 假資料層的可切換狀態（票 B2-library，畫面契約第四節「四態在原型上做成可切換的開關」）。
 * 跟主 app 程式碼零耦合——只有 `mocks/` 內部檔案會讀寫這裡。沿用票 B1-inbox／B1-settings
 * 已驗證過的寫法（`git show 76d6432:frontend/src/mocks/state.ts`），只留品牌智庫用得到的三個
 * 開關（不需要 B1 專屬的 apiKeySource）。
 *
 * 已掛載的頁面只在掛載那一刻讀一次資料，切開關不會讓它們自動重讀——讓頁面訂閱假資料層的
 * 開關會把 app 程式碼跟 mocks/ 綁在一起，違反「app 只有一條真實請求路徑」。改用
 * `sessionStorage` 記住選擇，`DevScenarioToggle` 切換後自己 `location.reload()`。 */

export type MockScenario = "normal" | "empty" | "loading";

type Listener = () => void;

const SCENARIO_KEY = "library-mock-scenario";
const READ_FAILURE_KEY = "library-mock-read-failure";
const ACTION_FAILURE_KEY = "library-mock-action-failure";

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
