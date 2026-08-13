/* 離線最小驗證：node verify.js */
const fs = require('fs');
const vm = require('vm');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const context = { window: {} };
vm.runInNewContext(fs.readFileSync('mock-data.js', 'utf8'), context);
const data = context.window.mockData;
const app = fs.readFileSync('app.js', 'utf8');
const html = fs.readFileSync('index.html', 'utf8');
const css = fs.readFileSync('style.css', 'utf8');
const before = data.performance.before;
const after = data.performance.after;

assert(['meta', 'google', 'tiktok'].every((key) => data.accounts[key]), '缺少三個廣告帳戶');
assert(data.creatives.meta.batch1.length === 2 && data.creatives.meta.batch2.length === 2, 'Meta 素材批次不完整');
assert(data.creatives.google.batch1.length === 2 && data.creatives.tiktok.batch2.length === 2, 'Google 或 TikTok 素材批次不完整');
assert(after.orders > before.orders && after.cac < before.cac && after.roas > before.roas && after.goalRate > 100, '優化後數據沒有全面改善');
assert(data.rebalanceProposals.length === 3, '再平衡提案不足三張');
assert(/data-action="refresh-creatives"/.test(app) && /data-action="apply-rebalance"/.test(app), '素材或再平衡互動未掛載');
assert(/scrollIntoView/.test(app) && /requestAnimationFrame/.test(app), '捲動或數字動畫未掛載');
assert(/mock-data\.js/.test(html) && /prefers-reduced-motion/.test(css), '離線資料入口或減少動態支援缺失');
console.log('PASS: v4-outcome 離線資料與核心互動掛點有效');
