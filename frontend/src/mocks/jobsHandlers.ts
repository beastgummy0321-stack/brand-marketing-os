/** 全站生成進度單一出口假路由（票 B4-warroom，模組邊界定案節）。跟 campaigns 假資料源各自
 * 獨立——這顆鈴鐺聚合的是 intake／products／library 三處既有背景工作，不是檔期資料，
 * 品牌用虛構名稱（使用者鐵則：測試一律虛構品牌）。 */
import { envelope, jsonResponse, registerRoute } from "./network";
import { getScenario } from "./state";

const JOBS = [
  { brand_id: "demo-warm-tea", brand_name: "暖心茶飲", kind: "scan", status: "running", stage: "正在讀取官網與社群連結", started_at: "2026-08-12T09:10:00+08:00", action_url: "/brands/demo-warm-tea/intake" },
  { brand_id: "demo-paper-goods", brand_name: "紙作良品", kind: "product_research", status: "waiting", stage: "排隊等候中", started_at: "2026-08-12T09:12:00+08:00", action_url: "/brands/demo-paper-goods/products" },
  { brand_id: "demo-warm-tea", brand_name: "暖心茶飲", kind: "question", status: "done", stage: "第 5 題已完成", started_at: "2026-08-12T08:55:00+08:00", action_url: "/brands/demo-warm-tea/intake" },
  { brand_id: "demo-quiet-fitness", brand_name: "靜巷健身", kind: "library_convert", status: "failed", stage: "轉換逾時，未計費", started_at: "2026-08-12T08:40:00+08:00", action_url: "/brands/demo-quiet-fitness/library" },
] as const;

registerRoute("GET", /^\/api\/jobs\/active$/, () => {
  const list = getScenario() === "empty" ? [] : JOBS;
  return jsonResponse(envelope(list));
});
