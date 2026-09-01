/** 品牌智庫「創意座標」分頁的 API 型別與呼叫（票 T1b）。對應 `app/schedule/routes.py:704-748`
 * 三支端點——這支分頁自己抓資料（station ① decision 3），不透過 `libraryApi.ts` 的
 * `fetchLibrary()`。回應形狀跟 `scheduleApi.ts` 同一個模組的其他端點一樣不套
 * `{data, generated_at}` 信封，直接照抄路由回傳的欄位。 */
import { apiFetch, errorMessageFromResponse } from "./http";

/** `CONSTITUTION.md` 規則 5 的七個維度鍵名——跟 `components/schedule/CampaignTree.tsx` 的
 * `COORDINATE_LABELS` 是同一份中文翻譯的另一份鏡射（container contract 規則 5：重複比
 * 跨模組互相 import 便宜，兩邊各自維護）。 */
export type CoordinateDimension = "audience" | "pain" | "angle" | "hook" | "proof" | "offer" | "format";

export const COORDINATE_DIMENSIONS: [CoordinateDimension, string][] = [
  ["audience", "受眾"],
  ["pain", "痛點"],
  ["angle", "角度"],
  ["hook", "鉤子"],
  ["proof", "證明"],
  ["offer", "優惠"],
  ["format", "格式"],
];

export interface CoordinateAttributes {
  situation?: string | null;
  lever?: string | null;
  person_on_camera?: string | null;
  funnel_stage?: string | null;
}

export interface Coordinate {
  id: string;
  dimension: CoordinateDimension;
  key: string;
  label: string;
  category: string | null;
  canonical_key: string | null;
  attributes: CoordinateAttributes;
  disabled_at: string | null;
  rejected: boolean;
}

export async function fetchCoordinates(brandId: string): Promise<Coordinate[]> {
  const res = await apiFetch(`/api/schedule/brands/${encodeURIComponent(brandId)}/coordinates`);
  if (!res.ok) {
    throw new Error(await errorMessageFromResponse(res, `讀取失敗（狀態碼 ${res.status}）`));
  }
  const body: { coordinates: Coordinate[] } = await res.json();
  return body.coordinates;
}

export async function createCoordinate(
  brandId: string,
  fields: { dimension: CoordinateDimension; label: string; category: string },
): Promise<Coordinate> {
  const res = await apiFetch(`/api/schedule/brands/${encodeURIComponent(brandId)}/coordinates`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(fields),
  });
  if (!res.ok) {
    throw new Error(await errorMessageFromResponse(res, `新增失敗（狀態碼 ${res.status}）`));
  }
  return (await res.json()) as Coordinate;
}

export async function setCoordinateDisabled(
  brandId: string,
  coordinateId: string,
  disabled: boolean,
): Promise<Coordinate> {
  const res = await apiFetch(
    `/api/schedule/brands/${encodeURIComponent(brandId)}/coordinates/${encodeURIComponent(coordinateId)}/disable`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ disabled }),
    },
  );
  if (!res.ok) {
    throw new Error(await errorMessageFromResponse(res, `更新失敗（狀態碼 ${res.status}）`));
  }
  return (await res.json()) as Coordinate;
}
