import { useSyncExternalStore } from "react";
import {
  getActionFailure,
  getReadFailure,
  getScenario,
  setActionFailure,
  setReadFailure,
  setScenario,
  subscribeMockState,
  type MockScenario,
} from "./state";

const SCENARIOS: { value: MockScenario; label: string }[] = [
  { value: "normal", label: "正常" },
  { value: "empty", label: "空" },
  { value: "loading", label: "進行中" },
];

/** 浮動假資料開關（票 B3-intake，畫面契約第四節：四態要能點得到才算數）。本身也是假
 * 資料層的一部分——之後切真後端時跟著整個 `mocks/` 目錄一起刪掉。逐字沿用 B1／B2 已驗證
 * 過的寫法，切換後重新整理頁面。 */
export function DevScenarioToggle() {
  const scenario = useSyncExternalStore(subscribeMockState, getScenario);
  const readFailure = useSyncExternalStore(subscribeMockState, getReadFailure);
  const actionFailure = useSyncExternalStore(subscribeMockState, getActionFailure);

  function handleScenario(value: MockScenario) {
    setScenario(value);
    window.location.reload();
  }

  function handleReadFailure(next: boolean) {
    setReadFailure(next);
    window.location.reload();
  }

  function handleActionFailure(next: boolean) {
    setActionFailure(next);
    window.location.reload();
  }

  return (
    <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 rounded-lg border border-neutral-300 bg-white p-3 text-xs shadow-lg">
      <p className="font-semibold text-neutral-500">建檔精靈假資料開關</p>
      <div className="flex items-center gap-1.5">
        <span className="w-16 shrink-0 text-neutral-500">四態</span>
        <div className="flex gap-1">
          {SCENARIOS.map((s) => (
            <button
              key={s.value}
              type="button"
              onClick={() => handleScenario(s.value)}
              className={
                "rounded px-2 py-1 " +
                (scenario === s.value
                  ? "bg-neutral-900 text-white"
                  : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200")
              }
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-16 shrink-0 text-neutral-500">讀取失敗</span>
        <button
          type="button"
          onClick={() => handleReadFailure(!readFailure)}
          className={
            "rounded px-2 py-1 " +
            (readFailure ? "bg-neutral-900 text-white" : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200")
          }
        >
          {readFailure ? "開" : "關"}
        </button>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-16 shrink-0 text-neutral-500">動作失敗</span>
        <button
          type="button"
          onClick={() => handleActionFailure(!actionFailure)}
          className={
            "rounded px-2 py-1 " +
            (actionFailure ? "bg-neutral-900 text-white" : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200")
          }
        >
          {actionFailure ? "開" : "關"}
        </button>
      </div>
      <p className="text-neutral-400">動作失敗開＝AI 呼叫本身失敗；接近上限的品牌走正常流程即可看到超限攔截卡片。</p>
    </div>
  );
}
