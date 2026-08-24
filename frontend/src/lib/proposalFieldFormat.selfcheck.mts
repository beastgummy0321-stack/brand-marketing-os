// 提案書物件欄位格式化的自我檢查（B0-30／B0-37）：純函式、無 JSX，直接跑
// `node --experimental-strip-types src/lib/proposalFieldFormat.selfcheck.mts`
// （Node 22.6+；本機用的是 v24，型別剝離內建可用，不必先 build）。
// 沒有測試框架就用 assert 頂格斷言——壞了就丟例外、非零結束碼，跟 pytest 一樣看得出紅燈。
import assert from "node:assert/strict";
import {
  fieldLabel, formatScalarField, isInternalIdKey, shouldHideField,
} from "./proposalFieldFormat.ts";

// 內部識別碼一律隱藏——這正是 B0-30 亂碼字串裡 ccp_/ccy_/brd_/prd_ 那四段的根源。
assert.equal(isInternalIdKey("id"), true);
assert.equal(isInternalIdKey("brand_id"), true);
assert.equal(isInternalIdKey("campaign_cycle_id"), true);
assert.equal(isInternalIdKey("product_id"), true);
assert.equal(isInternalIdKey("allocated_budget"), false);
assert.equal(shouldHideField("created_at"), true);
assert.equal(shouldHideField("updated_at"), true);
assert.equal(shouldHideField("allocated_budget"), false);

// 已知欄位有白話標籤；沒登記過的新欄位退回「底線換空格」，不會沒有標籤地漏出裸鍵名。
assert.equal(fieldLabel("allocated_budget"), "分配預算");
assert.equal(fieldLabel("brand_new_field_from_a_future_block"), "brand new field from a future block");

// 金額／佔比欄位依欄位語意格式化，不是原樣印出資料庫數字。
assert.equal(formatScalarField(75000, "allocated_budget"), "NT$ 75,000");
assert.equal(formatScalarField(1, "allocation_ratio"), "100.00%");
assert.equal(formatScalarField(12345, "no_special_meaning"), "12,345");

// 布林一律翻成是／否，不是 true/false。
assert.equal(formatScalarField(true), "是");
assert.equal(formatScalarField(false), "否");

// B0-30 觀察到的內部列舉代號翻成白話；沒登記過的字串原樣顯示（例如產品名稱）。
assert.equal(formatScalarField("economics", "allocation_basis"), "依產品毛利");
assert.equal(formatScalarField("ok", "status"), "沒問題");
assert.equal(formatScalarField("Beast Gummy", "product_name"), "Beast Gummy");

// B0-37 追蹤健檢那串裡的 ISO 時間戳，格式化成人看得懂的「月/日 時:分」，不是原始時間字串
// 原封不動印出來（確切時分依執行機器時區換算，這裡只驗證形狀，不假設特定時區）。
assert.match(formatScalarField("2026-08-14T16:00:07.980258+00:00"), /^\d{2}\/\d{2} \d{2}:\d{2}$/);

// F4：預算配置區塊（app/ads/proposal.py:77-83）與追蹤健檢區塊（app/ads/tracking.py:587）
// 組出的鍵名，原本沒登記，會被 fieldLabel() 退回底線換空格漏出裸英文鍵名。
assert.equal(fieldLabel("budget"), "總預算");
assert.equal(fieldLabel("allocations"), "各產品分配");
assert.equal(fieldLabel("forecast"), "成效預估");
assert.equal(fieldLabel("channels"), "通路清單");
assert.equal(fieldLabel("ready"), "已就緒");
assert.equal(fieldLabel("total"), "追蹤路數");

// F4：追蹤健檢五路通路的 key 值（app/ads/tracking.py:539-546、552-…）原樣漏出英文代號；
// 正確中文標籤跟 TrackingHealthPage.tsx 的 CHANNEL_CONFIG 共用同一份 TRACKING_CHANNEL_LABELS。
assert.equal(formatScalarField("website", "key"), "官方網站");
assert.equal(formatScalarField("fb_page", "key"), "Facebook 粉專");
assert.equal(formatScalarField("ig_account", "key"), "Instagram");
assert.equal(formatScalarField("shopee", "key"), "蝦皮");
assert.equal(formatScalarField("pharmacy", "key"), "藥局現場");

console.log("proposalFieldFormat.selfcheck.mts: all assertions passed");
