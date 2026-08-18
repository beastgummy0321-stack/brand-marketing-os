/* 第三幕：營運駕駛艙 S3（T1～T4）。只透過 app.js 的全域 state／render／helpers 溝通。 */

var S3_TABS = [['t1', '本週作戰'], ['t2', '月報'], ['t3', '長期系統'], ['t4', 'KOL 任務']];

function currentTestBoard(brand) {
  return state.ui.s3.optimized ? brand.act3.testBoard.after : brand.act3.testBoard.before;
}

function currentPerformance(brand) {
  return state.ui.s3.optimized ? brand.act3.performance.after : brand.act3.performance.before;
}

function renderAct3() {
  var brand = currentBrand();
  return '<section data-screen="s3">'
    + renderTodo3(brand)
    + renderS3Tabs()
    + renderS3TabContent(brand)
    + '</section>';
}

function renderTodo3(brand) {
  var todo3 = brand.act3.todo3;
  var replyWarn = todo3.replySpeed === 'yellow';
  var replyNote = replyWarn ? '詢問等太久，客人就跑了' : '回覆速度正常';
  var goodCustomerLabel = todo3.goodCustomerDefined ? '已確認' : '未確認';
  var goodCustomerBtn = todo3.goodCustomerDefined ? ''
    : '<button class="button button--small button--quiet" type="button" data-action="confirm-good-customer">確認</button>';
  return '<div class="todo3-row">'
    + '<div class="todo3-card card"><h3>產品資訊完整度</h3>'
    + '<span class="todo3-card__value mono">' + todo3.productCompleteness + '%</span>'
    + '<span class="todo3-card__note" style="color:var(--accent);font-weight:600">補齊</span></div>'
    + '<div class="todo3-card card"><h3>回覆速度</h3>'
    + '<span class="health-dot health-dot--' + (replyWarn ? 'yellow' : 'green') + '"></span>'
    + '<p class="todo3-card__note' + (replyWarn ? ' todo3-card__note--warn' : '') + '">' + replyNote + '</p></div>'
    + '<div class="todo3-card card"><h3>好客戶定義</h3><p class="todo3-card__note">' + goodCustomerLabel + '</p>'
    + goodCustomerBtn + '</div>'
    + '</div>';
}

function renderS3Tabs() {
  var active = state.ui.s3.activeTab;
  var tabs = S3_TABS.map(function (pair) {
    return '<button class="s3-tab" type="button" data-action="s3-tab" data-tab="' + pair[0] + '"'
      + ' role="tab" aria-selected="' + (pair[0] === active) + '">' + pair[1] + '</button>';
  }).join('');
  return '<div class="s3-tabs" role="tablist">' + tabs + '</div>';
}

function renderS3TabContent(brand) {
  var tab = state.ui.s3.activeTab;
  if (tab === 't1') return renderT1(brand);
  if (tab === 't2') return renderT2(brand);
  if (tab === 't3') return renderT3(brand);
  return renderT4(brand);
}

/* ---- T1 本週作戰 ---- */

function testCard(row) {
  return '<article class="test-card card"><div class="test-card__visual" style="background:#e2e8f0"></div>'
    + '<span class="test-card__name">' + escapeHtml(row.name) + '</span>'
    + '<dl><dt>花費</dt><dd>' + money(row.spend) + '</dd><dt>詢問</dt><dd>' + row.leads + '</dd>'
    + '<dt>單筆成本</dt><dd>' + money(row.cac) + '</dd></dl>'
    + '<span class="status-tag status-tag--' + row.status + '">' + row.status + '</span></article>';
}

function proposalCard(proposal, index) {
  var executed = state.ui.s3.optimized && proposal.selected;
  return '<article class="proposal card">'
    + (executed ? '<span class="executed-watermark">已執行</span>' : '')
    + '<input class="proposal__check" id="proposal' + index + '" type="checkbox" data-action="toggle-proposal"'
    + ' data-index="' + index + '" ' + (proposal.selected ? 'checked' : '') + ' ' + (state.ui.s3.optimized ? 'disabled' : '')
    + ' aria-label="選擇' + escapeHtml(proposal.target) + '">'
    + '<div class="proposal__title"><span class="action-tag action-tag--' + proposal.action + '">' + proposal.action + '</span>'
    + '<strong>' + escapeHtml(proposal.target) + '</strong></div>'
    + '<p class="proposal__reason">' + escapeHtml(proposal.reason) + '</p>'
    + '<p class="proposal__impact">' + escapeHtml(proposal.impact) + '</p>'
    + '</article>';
}

function renderT1(brand) {
  var board = currentTestBoard(brand);
  var groups = PLATFORM_KEYS.map(function (key) {
    var cards = board[key].map(testCard).join('');
    return '<div class="test-platform-group"><h3>' + PLATFORM_NAMES[key] + '</h3>'
      + '<div class="test-card-grid">' + cards + '</div></div>';
  }).join('');
  var proposals = brand.act3.weeklyProposals.map(proposalCard).join('');
  var optimized = state.ui.s3.optimized;
  var executing = state.ui.s3.executingWeekly;
  var btnLabel = optimized ? '✓ 已執行' : executing ? '執行中' : '一鍵核可週提案';
  return '<section class="section-block"><h2>小額測試看板</h2>' + groups + '</section>'
    + '<section class="section-block"><h2>週優化提案收件匣</h2>'
    + '<div class="proposal-grid">' + proposals + '</div>'
    + '<div class="t1-approve-bar"><button class="button" type="button" data-action="apply-weekly"'
    + ' ' + (optimized || executing ? 'disabled' : '') + '>' + btnLabel + '</button></div>'
    + '</section>';
}

/* ---- T2 月報 ---- */

function renderKpis(perf) {
  var values = [
    ['花費', '花 ' + money(perf.spend) + ' 帶來 ' + perf.orders + ' 筆成果', money(perf.spend)],
    ['成交', '本月已有 ' + perf.orders + ' 筆成果', formatNumber(perf.orders) + ' 筆'],
    ['每筆成本', '每筆成果平均花 ' + money(perf.cac), money(perf.cac)],
    ['ROAS', '每花 1 元帶回 ' + perf.roas.toFixed(2) + ' 元', perf.roas.toFixed(2) + '×']
  ];
  return values.map(function (item, index) {
    return '<article class="kpi-card card"><h2>' + item[0] + '</h2><p>' + item[1] + '</p>'
      + '<strong class="kpi-value" data-kpi="' + index + '">' + item[2] + '</strong></article>';
  }).join('');
}

function renderGoalMeter(rate) {
  var circumference = 2 * Math.PI * 54;
  var progress = Math.min(rate, 100) / 100 * circumference;
  return '<article class="kpi-card card goal-meter"><svg viewBox="0 0 140 140" aria-label="目標達成率 ' + rate + ' 百分比">'
    + '<circle class="track" cx="70" cy="70" r="54"></circle>'
    + '<circle class="value" cx="70" cy="70" r="54" stroke-dasharray="' + progress + ' ' + circumference + '"></circle>'
    + '<text x="70" y="78" text-anchor="middle">' + rate + '%</text></svg>'
    + '<div><h2>目標達成率</h2><p>' + (rate >= 100 ? '已超過本月目標' : '距離目標還有 ' + (100 - rate) + '%') + '</p></div></article>';
}

function renderTrend(trend) {
  var width = 1100, height = 260, left = 42, right = 26, top = 20, bottom = 35;
  var values = trend.actual.concat(trend.forecastLow, trend.forecastHigh);
  var maximum = Math.max.apply(null, values) + 5;
  var x = function (index) { return left + index * (width - left - right) / 6; };
  var y = function (value) { return top + (maximum - value) * (height - top - bottom) / maximum; };
  var path = function (items) {
    return items.map(function (value, index) { return (index ? 'L' : 'M') + x(index).toFixed(1) + ' ' + y(value).toFixed(1); }).join(' ');
  };
  var reversedLow = trend.forecastLow.slice().reverse().map(function (value, reverseIndex) {
    var index = 6 - reverseIndex;
    return 'L' + x(index).toFixed(1) + ' ' + y(value).toFixed(1);
  }).join(' ');
  var band = path(trend.forecastHigh) + ' ' + reversedLow + ' Z';
  var midLine = path(trend.forecastHigh.map(function (value, index) { return (value + trend.forecastLow[index]) / 2; }));
  var labels = trend.days.map(function (day, index) {
    return '<text class="axis-label" x="' + x(index).toFixed(1) + '" y="248" text-anchor="middle">週' + day + '</text>';
  }).join('');
  var grids = [0.25, 0.5, 0.75, 1].map(function (part) {
    var gridY = top + (height - top - bottom) * part;
    return '<line class="grid" x1="' + left + '" y1="' + gridY + '" x2="' + (width - right) + '" y2="' + gridY + '"></line>';
  }).join('');
  return '<div class="chart-heading"><h2>實際 vs 預估</h2><div class="chart-legend">'
    + '<span class="chart-key"><i class="chart-line"></i>實際</span>'
    + '<span class="chart-key"><i class="chart-line chart-line--dashed"></i>預估中線</span>'
    + '<span class="chart-key"><i class="chart-band"></i>預估區間</span></div></div>'
    + '<svg class="trend-chart" viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="實際與預估趨勢圖">'
    + grids + '<path class="forecast-band" d="' + band + '"></path>'
    + '<path class="forecast-line" d="' + midLine + '"></path>'
    + '<path class="actual-line" d="' + path(trend.actual) + '"></path>' + labels + '</svg>';
}

function renderPlatformResult(item) {
  return '<article class="platform-result-card card"><h2>' + item.platform + '</h2><dl>'
    + '<dt>花費</dt><dd>' + money(item.spend) + '</dd>'
    + '<dt>成交</dt><dd>' + item.orders + ' 筆</dd>'
    + '<dt>CPA</dt><dd>' + money(item.cac) + '</dd>'
    + '<dt>ROAS</dt><dd>' + item.roas.toFixed(2) + '×</dd></dl></article>';
}

function nextMonthTips(brand) {
  return brand.act3.weeklyProposals.map(function (proposal) {
    return proposal.action + '「' + proposal.target + '」：' + proposal.reason;
  });
}

function renderT2(brand) {
  var perf = currentPerformance(brand);
  var tips = nextMonthTips(brand).map(function (tip) { return '<li>' + escapeHtml(tip) + '</li>'; }).join('');
  return '<section class="overview-grid">' + renderKpis(perf) + renderGoalMeter(perf.goalRate) + '</section>'
    + '<section class="chart-card card">' + renderTrend(perf.trend) + '</section>'
    + '<section class="section-block"><h2>三平台成效</h2>'
    + '<div class="platform-result-grid">' + perf.byPlatform.map(renderPlatformResult).join('') + '</div></section>'
    + '<section class="section-block"><h2>下月怎麼改</h2><ul class="next-month-list">' + tips + '</ul></section>';
}

/* ---- T3 長期系統 ---- */

function renderT3(brand) {
  var cards = brand.act3.legacy.map(function (item, index) {
    var built = item.status === 'built';
    var statusHtml = built
      ? '<span class="legacy-card__status legacy-card__status--built">已建立</span>'
      : '<span class="legacy-card__status legacy-card__status--suggest">建議啟用</span>';
    var actionBtn = built ? ''
      : '<button class="button button--small button--quiet" type="button" data-action="enable-legacy" data-index="' + index + '">啟用</button>';
    return '<article class="legacy-card card"><h3>' + item.name + '</h3>' + statusHtml + actionBtn + '</article>';
  }).join('');
  return '<p class="legacy-subtitle">廣告不再每次重來</p><div class="legacy-grid">' + cards + '</div>';
}

/* ---- T4 KOL 任務 ---- */

function renderT4(brand) {
  var cards = brand.act3.kolTasks.map(function (task) {
    return '<article class="kol-card card"><div class="kol-card__body"><strong>' + escapeHtml(task.who) + '</strong>'
      + '<p>談：' + escapeHtml(task.topic) + '</p><p>預期：' + escapeHtml(task.expectedEffect) + '</p></div>'
      + '<span class="kol-card__status kol-card__status--' + task.status + '">' + task.status + '</span>'
      + '<span class="kol-card__manual">執行靠人</span></article>';
  }).join('');
  return '<div class="kol-list">' + cards + '</div>';
}

/* ---- 動作 ---- */

function countUpKpis(previous, next) {
  var starts = [previous.spend, previous.orders, previous.cac, previous.roas];
  var ends = [next.spend, next.orders, next.cac, next.roas];
  var started = window.performance.now();
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
  window.setTimeout(function () {
    document.querySelectorAll('.kpi-value').forEach(function (element) { element.classList.remove('is-improved'); });
  }, 800);
}

function applyWeeklyProposals() {
  var brand = currentBrand();
  var before = currentPerformance(brand);
  state.ui.s3.executingWeekly = true;
  render();
  window.setTimeout(function () {
    state.ui.s3.executingWeekly = false;
    state.ui.s3.optimized = true;
    state.ui.s3.activeTab = 't2';
    brand.monthSummary = { spend: brand.act3.performance.after.spend, result: brand.act3.performance.after.orders };
    render();
    window.scrollTo({ top: 0, behavior: 'smooth' });
    countUpKpis(before, currentPerformance(brand));
  }, 400);
}

function onAct3Action(action, el) {
  if (action === 's3-tab') { state.ui.s3.activeTab = el.dataset.tab; render(); return true; }
  if (action === 'apply-weekly') { applyWeeklyProposals(); return true; }
  if (action === 'confirm-good-customer') { currentBrand().act3.todo3.goodCustomerDefined = true; render(); return true; }
  if (action === 'enable-legacy') { currentBrand().act3.legacy[Number(el.dataset.index)].status = 'built'; render(); return true; }
  return false;
}

function onAct3Change(event) {
  if (event.target.dataset.action !== 'toggle-proposal') return;
  var brand = currentBrand();
  brand.act3.weeklyProposals[Number(event.target.dataset.index)].selected = event.target.checked;
}
