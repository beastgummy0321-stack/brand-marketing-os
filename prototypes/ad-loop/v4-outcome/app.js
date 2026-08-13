(function () {
  'use strict';

  var app = document.getElementById('app');
  var progressSteps = document.getElementById('progressSteps');
  var overlay = document.getElementById('fundOverlay');
  var resetButton = document.querySelector('[data-action="reset"]');
  var platformKeys = ['meta', 'google', 'tiktok'];
  var platformNames = { meta: 'Meta', google: 'Google', tiktok: 'TikTok' };
  var platformColors = { Meta: '#1E3A8A', Google: '#A16207', TikTok: '#0F766E' };
  var stepNames = ['開戶', '目標', '建議書', '操盤', '月報'];
  var state;

  function clone(data) {
    return JSON.parse(JSON.stringify(data));
  }

  function resetState() {
    state = clone(window.mockData);
    state.screen = 'onboarding';
    state.analysisOpen = false;
    state.activePlatform = 'meta';
    state.activeBatches = { meta: 'batch1', google: 'batch1', tiktok: 'batch1' };
    state.optimized = false;
    state.executingRebalance = false;
    state.dailyCapError = false;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, function (character) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character];
    });
  }

  function formatNumber(value) {
    return Number(value).toLocaleString('zh-TW');
  }

  function money(value) {
    return 'NT$' + formatNumber(value);
  }

  function currentPerformance() {
    return state.optimized ? state.performance.after : state.performance.before;
  }

  function currentAllocation() {
    return state.optimized ? state.portfolio.portfolioAfter.allocation : state.portfolio.portfolioBefore.allocation;
  }

  function stepCount() {
    return { onboarding: 1, goal: 2, proposal: 3, monthly: 5 }[state.screen];
  }

  function renderProgress() {
    var completeThrough = stepCount();
    progressSteps.innerHTML = stepNames.map(function (name, index) {
      var step = index + 1;
      return '<li class="' + (step <= completeThrough ? 'is-complete' : '') + '"><span class="step-dot">' + (step < completeThrough || completeThrough === 5 && step === 5 ? '✓' : step) + '</span>' + name + '</li>';
    }).join('');
  }

  function platformIcon(platform) {
    var letters = { Meta: 'M', Google: 'G', TikTok: 'T' };
    return '<svg class="platform-icon" viewBox="0 0 36 36" aria-hidden="true"><rect width="36" height="36" rx="8" fill="' + platformColors[platform] + '"></rect><text x="18" y="23" text-anchor="middle" fill="#fff" font-family="ui-monospace,monospace" font-weight="700" font-size="15">' + letters[platform] + '</text></svg>';
  }

  function render() {
    renderProgress();
    resetButton.classList.toggle('is-hidden', state.screen !== 'monthly');
    if (state.screen === 'onboarding') app.innerHTML = renderOnboarding();
    if (state.screen === 'goal') app.innerHTML = renderGoal();
    if (state.screen === 'proposal') app.innerHTML = renderProposal();
    if (state.screen === 'monthly') app.innerHTML = renderMonthly();
  }

  function renderOnboarding() {
    var cards = platformKeys.map(function (key) {
      var account = state.accounts[key];
      var status = account.connected ? 'is-connected' : '';
      var label = account.connected ? '已連結' : '連結';
      return '<article class="account-card card ' + status + '"><div class="account-card__top">' + platformIcon(account.name) + '<span class="account-card__name">' + account.name + '</span></div><button class="button button--quiet" type="button" data-action="connect" data-platform="' + key + '" ' + (account.connected ? 'disabled' : '') + '>' + label + '</button></article>';
    }).join('');
    var ready = platformKeys.every(function (key) { return state.accounts[key].connected; });
    var detection = state.tracking.detected ? '<span class="detection-result is-detected"><span class="check-mark">✓</span>已偵測到追蹤碼</span>' : '<span class="detection-result">尚未偵測</span>';
    return '<section data-screen="onboarding"><h1>開戶：連接您的三個廣告帳戶</h1><p class="page-intro">連結三個帳戶後即可開始</p><div class="account-grid">' + cards + '</div><section class="tracking-card card" aria-labelledby="trackingTitle"><div class="field"><label id="trackingTitle" for="trackingUrl">安裝追蹤碼</label><input id="trackingUrl" value="' + escapeHtml(state.tracking.url) + '" inputmode="url"></div><div><button class="button button--quiet" type="button" data-action="detect">偵測</button>' + detection + '</div></section><div class="tooltip-wrap button--next" data-tooltip="請先連結三個帳戶"><button class="button" type="button" data-action="to-goal" ' + (ready ? '' : 'disabled') + '>下一步</button></div></section>';
  }

  function renderGoal() {
    return '<section data-screen="goal"><div class="goal-card card"><h1>設定目標</h1><p class="page-intro">把結果交給投組處理</p><div class="field"><label for="goalUrl">品牌網址</label><input id="goalUrl" value="' + escapeHtml(state.goal.url) + '" inputmode="url"></div><div class="field"><label for="goalStatement">這個月想要</label><input id="goalStatement" value="' + escapeHtml(state.goal.statement) + '"></div><div class="field input-with-suffix"><label for="goalBudget">預算</label><div class="input-wrap"><input id="goalBudget" type="number" min="0" value="' + state.goal.budget + '"><span class="input-suffix">NT$／月</span></div></div><button class="button button--full" type="button" data-action="generate">產生投資組合建議書</button></div></section>';
  }

  function renderProposal() {
    var risk = state.portfolio.risk;
    return '<section data-screen="proposal"><div class="report-heading"><div><h1>投資組合建議書</h1><p class="page-intro">以 ' + escapeHtml(state.goal.statement) + ' 倒推本月配置</p></div></div><section class="portfolio-banner"><div><span class="portfolio-banner__label">預估每月訂閱</span><span class="portfolio-banner__value">' + state.portfolio.predictedRange.low + '–' + state.portfolio.predictedRange.high + ' 筆</span></div><div><span class="portfolio-banner__label">目標</span><span class="mono">50 筆</span></div><div><span class="risk-badge">中風險</span></div></section><div class="recommendation-grid"><div><section class="card card-pad">' + renderAnalysis() + '</section><section class="card card-pad">' + renderAllocation(currentAllocation()) + '</section><section class="card card-pad">' + renderCreatives() + '</section></div><aside><section class="card card-pad"><h2>風險說明</h2><p class="risk-copy">這份配置以達標為主，同時保留可調整的緩衝。</p><ul class="risk-list">' + risk.reasons.map(function (reason) { return '<li>' + warningIcon() + '<span>' + escapeHtml(reason) + '</span></li>'; }).join('') + '</ul></section><section class="card card-pad risk-controls"><h2>風控設定</h2><div class="field"><label for="dailyCap">日上限</label><input id="dailyCap" type="number" min="0" value="' + state.riskControls.dailyCap + '"><p id="dailyCapError" class="field-error">' + (state.dailyCapError ? '日上限不可超過月預算' : '') + '</p></div><div class="field"><label for="autoPause">無轉換自動暫停門檻</label><div class="input-wrap input-with-suffix"><input id="autoPause" type="number" min="1" value="' + state.riskControls.autoPauseThreshold + '"><span class="input-suffix">連續幾筆</span></div></div></section><section class="card card-pad approval-card"><h2>投放排程</h2><div class="schedule-grid"><div class="field"><label for="startDate">開始日期</label><input id="startDate" readonly value="' + state.schedule.start + '"></div><div class="field"><label for="endDate">結束日期</label><input id="endDate" readonly value="' + state.schedule.end + '"></div></div><button class="button button--gold button--full" type="button" data-action="approve">核准並委託操盤</button></section></aside></div></section>';
  }

  function warningIcon() {
    return '<svg width="15" height="15" viewBox="0 0 20 20" aria-hidden="true"><path fill="currentColor" d="M10 2.5 19 18H1L10 2.5Zm0 5.1-.7 5h1.4l-.7-5Zm0 7.1a.9.9 0 1 0 0 1.8.9.9 0 0 0 0-1.8Z"></path></svg>';
  }

  function renderAnalysis() {
    var open = state.analysisOpen;
    var groups = [['賣點', state.aiAnalysis.sellingPoints], ['受眾', state.aiAnalysis.audiences], ['競品', state.aiAnalysis.competitors]];
    return '<button class="collapsible-trigger" type="button" data-action="toggle-analysis" aria-expanded="' + open + '"><h2>AI 分析</h2><span><span class="analysis-toggle-copy">' + (open ? '收合' : '展開') + '</span> <span class="collapse-arrow">⌄</span></span></button><div class="analysis-content ' + (open ? 'is-open' : '') + '">' + groups.map(function (group) { return '<div class="analysis-group"><strong>' + group[0] + '</strong><div>' + group[1].map(function (item) { return '<span>' + escapeHtml(item) + '</span>'; }).join('') + '</div></div>'; }).join('') + '</div>';
  }

  function renderAllocation(allocation) {
    var radius = 78;
    var circumference = 2 * Math.PI * radius;
    var running = 0;
    var colors = [platformColors.Meta, platformColors.Google, platformColors.TikTok];
    var segments = allocation.map(function (item, index) {
      var length = circumference * item.pct / 100;
      var segment = '<circle cx="100" cy="100" r="' + radius + '" stroke="' + colors[index] + '" stroke-dasharray="' + length + ' ' + (circumference - length) + '" stroke-dashoffset="-' + running + '"></circle>';
      running += length;
      return segment;
    }).join('');
    var legend = allocation.map(function (item, index) { return '<div class="legend__item"><span class="legend__color" style="background:' + colors[index] + '"></span><span>' + item.platform + '</span><span class="mono">' + item.pct + '%</span><span class="mono">' + money(item.amount) + '</span></div>'; }).join('');
    return '<h2>三平台配置</h2><div class="allocation-layout"><svg class="donut" viewBox="0 0 200 200" aria-label="三平台預算配置圓環圖"><circle class="donut-track" cx="100" cy="100" r="' + radius + '"></circle>' + segments + '<text class="donut__center" x="100" y="96" text-anchor="middle">本月預算</text><text x="100" y="119" text-anchor="middle" font-family="ui-monospace,monospace" font-size="17">' + money(state.goal.budget) + '</text></svg><div class="legend">' + legend + '</div></div>';
  }

  function renderCreatives() {
    var active = state.activePlatform;
    var offset = { meta: '0', google: '67px', tiktok: '145px' }[active];
    var tabs = platformKeys.map(function (key) { return '<button class="tab" type="button" data-action="tab" data-platform="' + key + '" role="tab" aria-selected="' + (key === active) + '">' + platformNames[key] + '</button>'; }).join('');
    var items = state.creatives[active][state.activeBatches[active]];
    return '<h2>持倉明細</h2><div class="tabs" role="tablist" style="--tab-offset:' + offset + '">' + tabs + '</div><div class="creative-toolbar"><span class="field-label">' + platformNames[active] + ' 素材</span><button class="button button--quiet" type="button" data-action="refresh-creatives">換一批</button></div><div id="creativeGrid" class="creative-grid">' + items.map(function (item) { return creativeCard(active, item); }).join('') + '</div>';
  }

  function creativeCard(platform, item) {
    if (platform === 'meta') return '<article class="creative-card"><div class="creative-card__visual" style="background:' + item.color + '">LUMIBREW</div><div class="creative-card__copy"><h3>' + escapeHtml(item.title) + '</h3><p>' + escapeHtml(item.body) + '</p></div></article>';
    if (platform === 'google') return '<article class="creative-card serp-card"><span class="url">lumibrew.example.com</span><strong>' + escapeHtml(item.headline1) + '</strong><strong>' + escapeHtml(item.headline2) + '</strong><p>' + escapeHtml(item.description) + '</p></article>';
    return '<article class="creative-card script-card"><div class="script-cover" style="background:' + item.color + '"></div><ul>' + item.points.map(function (point) { return '<li>' + escapeHtml(point) + '</li>'; }).join('') + '</ul></article>';
  }

  function renderMonthly() {
    var performance = currentPerformance();
    return '<section data-screen="monthly"><div class="report-heading"><div><h1>基金月報</h1><p class="page-intro">把成效做成可讀、可調的投組報告</p></div></div><section class="overview-grid">' + renderKpis(performance) + renderGoalMeter(performance.goalRate) + '</section><section class="chart-card card">' + renderTrend(performance.trend) + '</section><section class="platform-results"><h2>三平台損益</h2><div class="platform-result-grid">' + performance.byPlatform.map(renderPlatformResult).join('') + '</div></section><button class="button button--outline" type="button" data-action="show-rebalance">查看再平衡提案</button>' + renderRebalance() + '</section>';
  }

  function renderKpis(performance) {
    var values = [
      ['花費', '花 ' + money(performance.spend) + ' 帶來 ' + performance.orders + ' 筆訂單', money(performance.spend)],
      ['成交', '本月已有 ' + performance.orders + ' 筆訂閱', formatNumber(performance.orders) + ' 筆'],
      ['每筆成本', '每筆訂閱平均花 ' + money(performance.cac), money(performance.cac)],
      ['ROAS', '每花 1 元帶回 ' + performance.roas.toFixed(2) + ' 元', performance.roas.toFixed(2) + '×']
    ];
    return values.map(function (item, index) { return '<article class="kpi-card card"><h2>' + item[0] + '</h2><p>' + item[1] + '</p><strong class="kpi-value" data-kpi="' + index + '" data-raw="' + [performance.spend, performance.orders, performance.cac, performance.roas][index] + '">' + item[2] + '</strong></article>'; }).join('');
  }

  function renderGoalMeter(rate) {
    var circumference = 2 * Math.PI * 54;
    var progress = Math.min(rate, 100) / 100 * circumference;
    return '<article class="kpi-card card goal-meter"><svg viewBox="0 0 140 140" aria-label="目標達成率 ' + rate + ' 百分比"><circle class="track" cx="70" cy="70" r="54"></circle><circle class="value" cx="70" cy="70" r="54" stroke-dasharray="' + progress + ' ' + circumference + '"></circle><text x="70" y="78" text-anchor="middle">' + rate + '%</text></svg><div><h2>目標達成率</h2><p>' + (rate >= 100 ? '已超過本月目標' : '距離目標還有 ' + (100 - rate) + '%') + '</p></div></article>';
  }

  function renderTrend(trend) {
    var width = 1100;
    var height = 260;
    var left = 42;
    var right = 26;
    var top = 20;
    var bottom = 35;
    var values = trend.actual.concat(trend.forecastLow, trend.forecastHigh);
    var maximum = Math.max.apply(null, values) + 5;
    var x = function (index) { return left + index * (width - left - right) / 6; };
    var y = function (value) { return top + (maximum - value) * (height - top - bottom) / maximum; };
    var path = function (items) { return items.map(function (value, index) { return (index ? 'L' : 'M') + x(index).toFixed(1) + ' ' + y(value).toFixed(1); }).join(' '); };
    var band = path(trend.forecastHigh) + ' ' + trend.forecastLow.slice().reverse().map(function (value, reverseIndex) { var index = 6 - reverseIndex; return 'L' + x(index).toFixed(1) + ' ' + y(value).toFixed(1); }).join(' ') + ' Z';
    var labels = trend.days.map(function (day, index) { return '<text class="axis-label" x="' + x(index).toFixed(1) + '" y="248" text-anchor="middle">週' + day + '</text>'; }).join('');
    var grids = [0.25, 0.5, 0.75, 1].map(function (part) { var gridY = top + (height - top - bottom) * part; return '<line class="grid" x1="' + left + '" y1="' + gridY + '" x2="' + (width - right) + '" y2="' + gridY + '"></line>'; }).join('');
    return '<div class="chart-heading"><h2>實際 vs 預估</h2><div class="chart-legend"><span class="chart-key"><i class="chart-line"></i>實際</span><span class="chart-key"><i class="chart-line chart-line--dashed"></i>預估中線</span><span class="chart-key"><i class="chart-band"></i>預估區間</span></div></div><svg class="trend-chart" viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="近七日實際與預估趨勢圖">' + grids + '<path class="forecast-band" d="' + band + '"></path><path class="forecast-line" d="' + path(trend.forecastHigh.map(function (value, index) { return (value + trend.forecastLow[index]) / 2; })) + '"></path><path class="actual-line" d="' + path(trend.actual) + '"></path>' + labels + '</svg>';
  }

  function renderPlatformResult(item) {
    return '<article class="platform-result-card card"><div class="account-card__top">' + platformIcon(item.platform) + '<h2>' + item.platform + '</h2></div><dl><dt>花費</dt><dd>' + money(item.spend) + '</dd><dt>訂單</dt><dd>' + item.orders + ' 筆</dd><dt>CPA</dt><dd>' + money(item.cac) + '</dd><dt>ROAS</dt><dd>' + item.roas.toFixed(2) + '×</dd></dl></article>';
  }

  function renderRebalance() {
    var proposals = state.rebalanceProposals.map(function (proposal, index) {
      var executed = state.optimized && proposal.selected;
      return '<article class="proposal card">' + (executed ? '<span class="executed-watermark">已執行</span>' : '') + '<input class="proposal__check" id="proposal' + index + '" type="checkbox" data-action="toggle-proposal" data-index="' + index + '" ' + (proposal.selected ? 'checked' : '') + ' ' + (state.optimized ? 'disabled' : '') + ' aria-label="選擇' + escapeHtml(proposal.target) + '"><div class="proposal__title"><span class="action-tag action-tag--' + proposal.action + '">' + proposal.action + '</span><strong>' + escapeHtml(proposal.target) + '</strong></div><p class="proposal__reason">' + escapeHtml(proposal.reason) + '</p><p class="proposal__impact">' + escapeHtml(proposal.impact) + '</p></article>';
    }).join('');
    var label = state.optimized ? '✓ 已執行' : state.executingRebalance ? '執行中' : '一鍵核准再平衡';
    return '<section id="rebalance" class="rebalance"><h2>再平衡提案</h2><p class="rebalance-intro">把預算移向已證明有效的配置</p><div class="proposal-grid">' + proposals + '</div><button class="button button--gold" type="button" data-action="apply-rebalance" ' + (state.optimized || state.executingRebalance ? 'disabled' : '') + '>' + label + '</button></section>';
  }

  function saveGoalInputs() {
    var url = document.getElementById('goalUrl');
    var statement = document.getElementById('goalStatement');
    var budget = document.getElementById('goalBudget');
    state.goal.url = url.value.trim() || state.goal.url;
    state.goal.statement = statement.value.trim() || state.goal.statement;
    state.goal.budget = Math.max(0, Number(budget.value) || 0);
  }

  function connectAccount(button) {
    var platform = button.dataset.platform;
    button.disabled = true;
    button.textContent = '連結中';
    window.setTimeout(function () {
      state.accounts[platform].connected = true;
      render();
    }, 200);
  }

  function detectTracking(button) {
    var url = document.getElementById('trackingUrl');
    state.tracking.url = url.value.trim() || state.tracking.url;
    button.disabled = true;
    button.textContent = '偵測中';
    window.setTimeout(function () {
      state.tracking.detected = true;
      render();
    }, 400);
  }

  function generateProposal(button) {
    saveGoalInputs();
    button.disabled = true;
    button.innerHTML = '<span class="spinner" aria-hidden="true"></span>分析中';
    window.setTimeout(function () {
      state.screen = 'proposal';
      render();
    }, 1200);
  }

  function validateDailyCap() {
    var field = document.getElementById('dailyCap');
    var error = document.getElementById('dailyCapError');
    state.riskControls.dailyCap = Math.max(0, Number(field.value) || 0);
    state.dailyCapError = state.riskControls.dailyCap > state.goal.budget;
    field.closest('.field').classList.toggle('has-error', state.dailyCapError);
    error.textContent = state.dailyCapError ? '日上限不可超過月預算' : '';
  }

  function refreshCreatives() {
    var platform = state.activePlatform;
    var grid = document.getElementById('creativeGrid');
    grid.classList.add('is-refreshing');
    window.setTimeout(function () {
      state.activeBatches[platform] = state.activeBatches[platform] === 'batch1' ? 'batch2' : 'batch1';
      grid.innerHTML = state.creatives[platform][state.activeBatches[platform]].map(function (item) { return creativeCard(platform, item); }).join('');
      grid.classList.remove('is-refreshing');
    }, 150);
  }

  function approvePortfolio(button) {
    validateDailyCap();
    if (state.dailyCapError) return;
    var autoPause = document.getElementById('autoPause');
    state.riskControls.autoPauseThreshold = Math.max(1, Number(autoPause.value) || 1);
    button.disabled = true;
    overlay.classList.add('is-visible');
    overlay.setAttribute('aria-hidden', 'false');
    window.setTimeout(function () {
      overlay.classList.remove('is-visible');
      overlay.setAttribute('aria-hidden', 'true');
      state.screen = 'monthly';
      render();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }, 1300);
  }

  function countUp(previous, next) {
    var starts = [previous.spend, previous.orders, previous.cac, previous.roas];
    var ends = [next.spend, next.orders, next.cac, next.roas];
    var started = performance.now();
    function frame(now) {
      var progress = Math.min(1, (now - started) / 600);
      document.querySelectorAll('[data-kpi]').forEach(function (element, index) {
        var value = starts[index] + (ends[index] - starts[index]) * progress;
        if (index === 3) element.textContent = value.toFixed(2) + '×';
        else if (index === 1) element.textContent = Math.round(value) + ' 筆';
        else element.textContent = money(Math.round(value));
      });
      if (progress < 1) window.requestAnimationFrame(frame);
    }
    window.requestAnimationFrame(frame);
    document.querySelectorAll('.kpi-value').forEach(function (element) { element.classList.add('is-improved'); });
    window.setTimeout(function () { document.querySelectorAll('.kpi-value').forEach(function (element) { element.classList.remove('is-improved'); }); }, 800);
  }

  function applyRebalance() {
    var before = currentPerformance();
    state.executingRebalance = true;
    render();
    window.setTimeout(function () {
      state.executingRebalance = false;
      state.optimized = true;
      render();
      window.scrollTo({ top: 0, behavior: 'smooth' });
      countUp(before, currentPerformance());
    }, 400);
  }

  app.addEventListener('click', function (event) {
    var button = event.target.closest('[data-action]');
    if (!button || button.disabled) return;
    var action = button.dataset.action;
    if (action === 'connect') connectAccount(button);
    if (action === 'detect') detectTracking(button);
    if (action === 'to-goal') { state.screen = 'goal'; render(); }
    if (action === 'generate') generateProposal(button);
    if (action === 'toggle-analysis') { state.analysisOpen = !state.analysisOpen; render(); }
    if (action === 'tab') { state.activePlatform = button.dataset.platform; render(); }
    if (action === 'refresh-creatives') refreshCreatives();
    if (action === 'approve') approvePortfolio(button);
    if (action === 'show-rebalance') document.getElementById('rebalance').scrollIntoView({ behavior: 'smooth' });
    if (action === 'apply-rebalance') applyRebalance();
  });

  app.addEventListener('change', function (event) {
    if (event.target.dataset.action === 'toggle-proposal') {
      state.rebalanceProposals[Number(event.target.dataset.index)].selected = event.target.checked;
    }
  });

  app.addEventListener('blur', function (event) {
    if (event.target.id === 'dailyCap') validateDailyCap();
  }, true);

  resetButton.addEventListener('click', function () {
    resetState();
    render();
    window.scrollTo({ top: 0, behavior: 'auto' });
  });

  resetState();
  render();
}());
