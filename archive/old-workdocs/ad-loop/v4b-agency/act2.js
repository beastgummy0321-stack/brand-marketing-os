/* 第二幕：提案書 S2。只透過 app.js 的全域 state／render／helpers 溝通。 */

var PLATFORM_KEYS = ['meta', 'google', 'tiktok'];
var PLATFORM_NAMES = { meta: 'Meta', google: 'Google', tiktok: 'TikTok' };
var PLATFORM_COLORS = { Meta: '#1E3A8A', Google: '#A16207', TikTok: '#0F766E' };
var TRACKING_STATUS_LABEL = { pending: '未設定', checking: '檢查中', done: '已設定✓' };

function trackingAllDone(brand) {
  return brand.act2.tracking.nodes.every(function (node) { return node.status === 'done'; });
}

function renderChannelTable(rows) {
  var trs = rows.map(function (row) {
    return '<tr><td>' + escapeHtml(row.channel) + '</td><td>' + escapeHtml(row.job) + '</td>'
      + '<td class="mono">' + row.pct + '%</td><td>' + escapeHtml(row.expected) + '</td></tr>';
  }).join('');
  return '<h2>管道分工表</h2>'
    + '<div style="overflow-x:auto;margin-top:var(--space-3)"><table class="channel-table">'
    + '<thead><tr><th>管道</th><th>主要工作</th><th>預算占比</th><th>預估成果</th></tr></thead>'
    + '<tbody>' + trs + '</tbody></table></div>';
}

function renderAllocation(allocation, monthlyBudget) {
  var radius = 78;
  var circumference = 2 * Math.PI * radius;
  var running = 0;
  var segments = allocation.map(function (item) {
    var length = circumference * item.pct / 100;
    var color = PLATFORM_COLORS[item.platform];
    var segment = '<circle cx="100" cy="100" r="' + radius + '" stroke="' + color + '"'
      + ' stroke-dasharray="' + length + ' ' + (circumference - length) + '"'
      + ' stroke-dashoffset="-' + running + '"></circle>';
    running += length;
    return segment;
  }).join('');
  var legend = allocation.map(function (item) {
    var color = PLATFORM_COLORS[item.platform];
    return '<div class="legend__item"><span class="legend__color" style="background:' + color + '"></span>'
      + '<span>' + item.platform + '</span><span class="mono">' + item.pct + '%</span>'
      + '<span class="mono">' + money(item.amount) + '</span></div>';
  }).join('');
  return '<h2>預算配置</h2><div class="allocation-layout">'
    + '<svg class="donut" viewBox="0 0 200 200" aria-label="三平台預算配置圓環圖">'
    + '<circle class="donut-track" cx="100" cy="100" r="' + radius + '"></circle>' + segments
    + '<text class="donut__center" x="100" y="96" text-anchor="middle">本月預算</text>'
    + '<text x="100" y="119" text-anchor="middle" font-family="ui-monospace,monospace" font-size="15">'
    + money(monthlyBudget) + '</text></svg>'
    + '<div class="legend">' + legend + '</div></div>';
}

function creativeCard(platform, item) {
  if (platform === 'meta') {
    return '<article class="creative-card"><div class="creative-card__visual" style="background:' + item.color + '">品牌視覺</div>'
      + '<div class="creative-card__copy"><h3>' + escapeHtml(item.title) + '</h3><p>' + escapeHtml(item.body) + '</p></div></article>';
  }
  if (platform === 'google') {
    return '<article class="creative-card serp-card"><span class="url">品牌網址</span>'
      + '<strong>' + escapeHtml(item.headline1) + '</strong><strong>' + escapeHtml(item.headline2) + '</strong>'
      + '<p>' + escapeHtml(item.description) + '</p></article>';
  }
  return '<article class="creative-card script-card"><div class="script-cover" style="background:' + item.color + '"></div>'
    + '<ul>' + item.points.map(function (point) { return '<li>' + escapeHtml(point) + '</li>'; }).join('') + '</ul></article>';
}

function renderCreatives(creatives) {
  var active = state.ui.s2.activePlatform;
  var offsetMap = { meta: '0', google: '67px', tiktok: '145px' };
  var tabs = PLATFORM_KEYS.map(function (key) {
    return '<button class="tab" type="button" data-action="s2-tab" data-platform="' + key + '"'
      + ' role="tab" aria-selected="' + (key === active) + '">' + PLATFORM_NAMES[key] + '</button>';
  }).join('');
  var batch = state.ui.s2.activeBatches[active];
  var items = creatives[active][batch];
  return '<h2>素材多版</h2>'
    + '<div class="tabs" role="tablist" style="--tab-offset:' + offsetMap[active] + '">' + tabs + '</div>'
    + '<p class="creative-hint">讓市場告訴我們哪種有效</p>'
    + '<div class="creative-toolbar"><span class="field-label">' + PLATFORM_NAMES[active] + ' 素材</span>'
    + '<button class="button button--quiet" type="button" data-action="refresh-creatives">換一批</button></div>'
    + '<div id="creativeGrid" class="creative-grid">'
    + items.map(function (item) { return creativeCard(active, item); }).join('') + '</div>';
}

function trackingBlock(brand) {
  var items = brand.act2.tracking.nodes.map(function (node, index) {
    var doneClass = node.status === 'done' ? ' is-done' : '';
    var action = node.status === 'done' ? '' : '<button class="button button--small button--quiet" type="button"'
      + ' data-action="check-node" data-node="' + node.key + '" ' + (node.status === 'checking' ? 'disabled' : '') + '>檢查</button>';
    return '<div class="funnel-node' + doneClass + '"><span class="funnel-node__dot">' + (index + 1) + '</span>'
      + '<span class="funnel-node__label">' + node.label + '</span>'
      + '<span class="funnel-node__status">' + TRACKING_STATUS_LABEL[node.status] + '</span>' + action + '</div>';
  }).join('');
  return '<h2>追蹤設定</h2><div class="funnel">' + items + '</div>'
    + '<div class="tracking-warning">沒有追蹤只知道有曝光，不知道錢有沒有帶來生意</div>';
}

function riskControlsBlock(brand) {
  var risk = brand.act2.riskControls;
  var error = state.ui.s2.dailyCapError;
  return '<h2>風控設定</h2>'
    + '<div class="field' + (error ? ' has-error' : '') + '"><label for="dailyCap">日上限</label>'
    + '<input id="dailyCap" type="number" min="0" value="' + risk.dailyCap + '">'
    + '<p class="field-error">' + (error ? '日上限不可超過月預算' : '') + '</p></div>'
    + '<div class="field"><label for="autoPause">無詢問自動暫停門檻</label>'
    + '<input id="autoPause" type="number" min="1" value="' + risk.autoPauseThreshold + '"></div>';
}

function scheduleBlock(brand) {
  var schedule = brand.act2.schedule;
  return '<h2>投放排程</h2><div class="schedule-grid">'
    + '<div class="field"><label for="startDate">開始日期</label><input id="startDate" readonly value="' + schedule.start + '"></div>'
    + '<div class="field"><label for="endDate">結束日期</label><input id="endDate" readonly value="' + schedule.end + '"></div></div>';
}

function renderAct2() {
  var brand = currentBrand();
  var a2 = brand.act2;
  var riskModifier = (a2.risk.level === '低' || a2.risk.level === '高') ? (' risk-badge--' + a2.risk.level) : '';
  var ready = !state.ui.s2.dailyCapError && trackingAllDone(brand);
  var tooltipAttr = ready ? '' : ' data-tooltip="沒有追蹤只知道有曝光，不知道錢有沒有帶來生意"';
  return '<section data-screen="s2">'
    + '<div class="report-heading"><div><h1>提案書</h1><p class="page-intro">' + escapeHtml(brand.name) + '</p></div></div>'
    + '<section class="proposal-banner">'
    + '<div><span class="proposal-banner__label">預估每月成果</span>'
    + '<span class="proposal-banner__value">' + a2.predictedRange.low + '–' + a2.predictedRange.high + ' 筆</span></div>'
    + '<div><span class="proposal-banner__label">目標</span><span class="mono">' + brand.act1.goalNumber.target + ' 筆</span></div>'
    + '<div><span class="risk-badge' + riskModifier + '">' + a2.risk.level + '風險</span></div>'
    + '</section>'
    + '<div class="proposal-grid-layout"><div>'
    + '<section class="card card-pad">' + renderChannelTable(a2.channelPlan) + '</section>'
    + '<section class="card card-pad">' + renderAllocation(a2.allocation, brand.act1.budget.monthlyCap) + '</section>'
    + '<section class="card card-pad">' + renderCreatives(a2.creatives) + '</section>'
    + '<section class="card card-pad">' + trackingBlock(brand) + '</section>'
    + '</div><aside>'
    + '<section class="card card-pad risk-controls">' + riskControlsBlock(brand) + '</section>'
    + '<section class="card card-pad approval-card">' + scheduleBlock(brand)
    + '<div class="tooltip-wrap"' + tooltipAttr + '>'
    + '<button class="button button--full" type="button" data-action="launch-test" ' + (ready ? '' : 'disabled') + '>小額測試開跑</button>'
    + '</div></section>'
    + '</aside></div></section>';
}

/* ---- 動作 ---- */

function validateDailyCap() {
  var brand = currentBrand();
  var field = document.getElementById('dailyCap');
  if (!field) return true;
  var value = Math.max(0, Number(field.value) || 0);
  brand.act2.riskControls.dailyCap = value;
  state.ui.s2.dailyCapError = value > brand.act1.budget.monthlyCap;
  return !state.ui.s2.dailyCapError;
}

function refreshCreativesS2() {
  var platform = state.ui.s2.activePlatform;
  var grid = document.getElementById('creativeGrid');
  grid.classList.add('is-refreshing');
  window.setTimeout(function () {
    var batches = state.ui.s2.activeBatches;
    batches[platform] = batches[platform] === 'batch1' ? 'batch2' : 'batch1';
    var items = currentBrand().act2.creatives[platform][batches[platform]];
    grid.innerHTML = items.map(function (item) { return creativeCard(platform, item); }).join('');
    grid.classList.remove('is-refreshing');
  }, 150);
}

function checkNode(key) {
  var brand = currentBrand();
  var node = brand.act2.tracking.nodes.filter(function (item) { return item.key === key; })[0];
  if (!node) return;
  node.status = 'checking';
  render();
  window.setTimeout(function () {
    node.status = 'done';
    render();
  }, 400);
}

function launchTest() {
  var brand = currentBrand();
  if (!validateDailyCap()) { render(); return; }
  var autoPauseEl = document.getElementById('autoPause');
  brand.act2.riskControls.autoPauseThreshold = Math.max(1, Number(autoPauseEl.value) || 1);
  if (!trackingAllDone(brand)) return;
  var launchButton = document.querySelector('[data-action="launch-test"]');
  if (launchButton) launchButton.disabled = true;
  launchOverlayEl.classList.add('is-visible');
  launchOverlayEl.setAttribute('aria-hidden', 'false');
  window.setTimeout(function () {
    launchOverlayEl.classList.remove('is-visible');
    launchOverlayEl.setAttribute('aria-hidden', 'true');
    brand.act2.approved = true;
    brand.stage = 'operating';
    brand.healthLight = 'green';
    brand.monthSummary = { spend: brand.act3.performance.before.spend, result: brand.act3.performance.before.orders };
    state.screen = 's3';
    state.ui.s3 = { activeTab: 't1', optimized: false, executingWeekly: false };
    render();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, 1300);
}

function onAct2Action(action, el) {
  if (action === 's2-tab') { state.ui.s2.activePlatform = el.dataset.platform; render(); return true; }
  if (action === 'refresh-creatives') { refreshCreativesS2(); return true; }
  if (action === 'check-node') { checkNode(el.dataset.node); return true; }
  if (action === 'launch-test') { launchTest(); return true; }
  return false;
}

function onAct2Blur(event) {
  if (event.target.id !== 'dailyCap') return;
  validateDailyCap();
  render();
}
