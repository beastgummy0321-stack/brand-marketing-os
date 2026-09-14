/** 投放前的品牌層資料：可投放檢查表（F05-I04）＋通路清單（F05-I05）。跟 `adsApi.ts` 分開檔案
 * 只是為了不撐破 800 行慣例，共用 `parseJsonOrThrow`／`BASE` 從那邊 import，不重寫一份。 */
import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";

/** F05-I04：可投放檢查表——`app/ads/readiness.py::launch_readiness()` 的回傳形狀，瀏覽器逐字印
 * 每一列的 `reason`，不重拼句子。三色沒有第四種狀態、`items` 固定三列固定順序。 */
export type ReadinessState = "green" | "yellow" | "red";

export interface ReadinessItem {
  key: string;
  label: string;
  state: ReadinessState;
  reason: string;
  fix_label: string;
  fix_href: string;
}

export interface ReadinessNote {
  key: string;
  text: string;
}

export interface ReadinessAction {
  label: string;
  href: string;
}

export interface LaunchReadiness {
  state: ReadinessState;
  items: ReadinessItem[];
  notes: ReadinessNote[];
  primary: ReadinessAction;
  secondary: ReadinessAction | null;
}

export async function fetchLaunchReadiness(brandId: string): Promise<LaunchReadiness> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/readiness`);
  const data = await parseJsonOrThrow<{ readiness: LaunchReadiness }>(res, "讀取可投放檢查表失敗。");
  return data.readiness;
}

/** F05-I05：通路清單，平台名字只准住在後端 `channels.py`，畫面不准自己寫死。 */
export interface Channel { key: string; label: string; connected: boolean; state_text: string }

export async function fetchChannels(brandId: string): Promise<Channel[]> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/channels`);
  const data = await parseJsonOrThrow<{ channels: Channel[] }>(res, "讀取通路清單失敗。");
  return data.channels;
}
