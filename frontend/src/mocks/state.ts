/** 假資料層的可切換狀態（票 B3-intake，畫面契約第四節「四態在原型上做成可切換的開關」）。
 * 跟主 app 程式碼零耦合——只有 `mocks/` 內部檔案會讀寫這裡。逐字沿用 B1／B2 已驗證過的
 * 寫法（`git show 6cb61e6:frontend/src/mocks/state.ts`）。 */

export type MockScenario = "normal" | "empty" | "loading";

type Listener = () => void;

const SCENARIO_KEY = "intake-mock-scenario";
const READ_FAILURE_KEY = "intake-mock-read-failure";
const ACTION_FAILURE_KEY = "intake-mock-action-failure";

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
