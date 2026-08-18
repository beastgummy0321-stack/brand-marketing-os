/* 第一幕：開戶訪談 S1-1～S1-4。只透過 app.js 的全域 state／render／helpers 溝通。 */

var GOAL_TYPES = ['更多人認識', '更多私訊', '更多到店', '直接成交'];

function renderAct1(screen) {
  if (screen === 's1-1') return renderS1_1();
  if (screen === 's1-2') return renderS1_2();
  if (screen === 's1-3') return renderS1_3();
  return renderS1_4();
}

function textField(id, label, value) {
  return '<div class="field">'
    + '<div class="field-top-row"><label for="' + id + '">' + label + '</label>'
    + '<span class="field-hint">AI 已分析網址填入</span></div>'
    + '<input id="' + id + '" value="' + escapeHtml(value) + '"></div>';
}

function sliderField(id, label, value, min, max, step, prefix, suffix) {
  return '<div class="field slider-field"><label for="' + id + '">' + label + '</label>'
    + '<div class="slider-row">'
    + '<input id="' + id + '" type="range" data-slider min="' + min + '" max="' + max + '" step="' + step + '"'
    + ' value="' + value + '" data-prefix="' + prefix + '" data-suffix="' + suffix + '">'
    + '<span class="slider-value mono">' + prefix + formatNumber(value) + suffix + '</span>'
    + '</div></div>';
}

function renderS1_1() {
  var brand = currentBrand();
  var p = brand.act1.product;
  var goalCards = GOAL_TYPES.map(function (type) {
    var selected = brand.act1.goalType === type;
    return '<button class="goal-type-option' + (selected ? ' is-selected' : '') + '" type="button"'
      + ' data-action="select-goal-type" data-type="' + escapeHtml(type) + '">' + type + '</button>';
  }).join('');
  return '<section data-screen="s1-1"><h1>聽產品：先搞懂你在賣什麼</h1>'
    + '<div class="onboard-card card">'
    + textField('p-desc', '產品', p.desc)
    + textField('p-price', '定價', p.price)
    + textField('p-margin', '毛利', p.margin)
    + textField('p-stock', '庫存狀況', p.stock)
    + textField('p-customers', '目前客源', p.customers)
    + textField('p-competitors', '競品', p.competitors.join('、'))
    + textField('p-story', '品牌故事', p.story)
    + textField('p-problem', '目前遇到的問題', p.problem)
    + '<div class="field"><label>目標型態</label><div class="goal-type-grid">' + goalCards + '</div></div>'
    + '<button class="button" type="button" data-action="s1-next">下一步</button>'
    + '</div></section>';
}

function renderS1_2() {
  var brand = currentBrand();
  var g = brand.act1.goalNumber;
  var b = brand.act1.budget;
  return '<section data-screen="s1-2"><div class="onboard-card card">'
    + '<h1>把願望翻成數字</h1><p class="page-intro">例：三個月 300 筆有效詢問</p>'
    + '<div class="field"><label for="goalTarget">' + escapeHtml(g.label) + '</label>'
    + '<input id="goalTarget" type="number" min="0" value="' + g.target + '"></div>'
    + sliderField('budgetTotal', '廣告總預算', b.total, 0, 100000, 1000, 'NT$', '')
    + sliderField('budgetMonthlyCap', '每月上限', b.monthlyCap, 0, 100000, 1000, 'NT$', '')
    + sliderField('maxCac', '單筆詢問最高取得成本', b.maxCacPerLead, 0, 2000, 10, 'NT$', '')
    + '<div class="generate-bar">'
    + '<button class="button button--quiet" type="button" data-action="s1-back">上一步</button>'
    + '<button class="button" type="button" data-action="s1-next">下一步</button>'
    + '</div></div></section>';
}

function personaCard(item) {
  return '<article class="persona-card card"><h3>' + escapeHtml(item.title) + '</h3><dl>'
    + '<dt>何時需要</dt><dd>' + escapeHtml(item.whenNeeded) + '</dd>'
    + '<dt>在意什麼</dt><dd>' + escapeHtml(item.careAbout) + '</dd>'
    + '<dt>為何猶豫</dt><dd>' + escapeHtml(item.hesitation) + '</dd>'
    + '<dt>在哪看資訊</dt><dd>' + escapeHtml(item.whereToFind) + '</dd>'
    + '</dl></article>';
}

function renderS1_3() {
  var brand = currentBrand();
  var items = brand.act1.personas[state.ui.s1PersonaBatch];
  return '<section data-screen="s1-3"><h1>這個人是誰</h1><p class="page-intro">不是年齡層，是情境</p>'
    + '<div class="persona-toolbar"><span></span>'
    + '<button class="button button--quiet" type="button" data-action="refresh-personas">換一批</button></div>'
    + '<div id="personaGrid" class="persona-grid">' + items.map(personaCard).join('') + '</div>'
    + '<div class="generate-bar">'
    + '<button class="button button--quiet" type="button" data-action="s1-back">上一步</button>'
    + '<button class="button" type="button" data-action="s1-next">下一步</button>'
    + '</div></section>';
}

function healthRow(item, index) {
  var open = !!state.ui.s1SuggestionOpen[index];
  return '<div class="check-row card">'
    + '<span class="light-dot light-dot--' + item.light + '"></span>'
    + '<strong>' + escapeHtml(item.channel) + '</strong>'
    + '<span class="check-row__consequence">' + escapeHtml(item.consequence) + '</span>'
    + '<button class="check-row__suggestion-link" type="button" data-action="toggle-suggestion"'
    + ' data-index="' + index + '" aria-expanded="' + open + '">修正建議'
    + '<span class="suggestion-arrow">›</span></button>'
    + '<div class="suggestion-body' + (open ? ' is-open' : '') + '"><span class="suggestion-inner">' + escapeHtml(item.suggestion) + '</span></div>'
    + '</div>';
}

function renderS1_4() {
  var brand = currentBrand();
  var rows = brand.act1.healthCheck.map(healthRow).join('');
  var hasWarning = brand.act1.healthCheck.some(function (item) { return item.light === 'yellow' || item.light === 'red'; });
  var notice = hasWarning ? '<div class="notice-bar">有項目待改善，仍可繼續，先看提案書</div>' : '';
  var generating = !!state.ui.s1Generating;
  var btnLabel = generating ? '<span class="spinner" aria-hidden="true"></span>分析中' : '產生提案書';
  return '<section data-screen="s1-4"><h1>廣告把人帶來之後呢</h1><p class="page-intro">這裡不順，廣告等於白花</p>'
    + notice
    + '<div class="check-list">' + rows + '</div>'
    + '<div class="generate-bar">'
    + '<button class="button button--quiet" type="button" data-action="s1-back"' + (generating ? ' disabled' : '') + '>上一步</button>'
    + '<button class="button" type="button" data-action="generate-proposal" '
    + (generating ? 'disabled' : '') + '>' + btnLabel + '</button></div>'
    + '</section>';
}

/* ---- 動作 ---- */

function readVal(id, fallback) {
  var el = document.getElementById(id);
  if (!el) return fallback;
  var value = el.value.trim();
  return value === '' ? fallback : value;
}

function saveS1Step() {
  var brand = currentBrand();
  var screen = state.screen;
  if (screen === 's1-1') {
    var p = brand.act1.product;
    p.desc = readVal('p-desc', p.desc);
    p.price = readVal('p-price', p.price);
    p.margin = readVal('p-margin', p.margin);
    p.stock = readVal('p-stock', p.stock);
    p.customers = readVal('p-customers', p.customers);
    var competitorsText = readVal('p-competitors', p.competitors.join('、'));
    p.competitors = competitorsText.split(/[、,，]/).map(function (item) { return item.trim(); }).filter(Boolean);
    p.story = readVal('p-story', p.story);
    p.problem = readVal('p-problem', p.problem);
  } else if (screen === 's1-2') {
    var g = brand.act1.goalNumber;
    g.target = Number(readVal('goalTarget', g.target)) || g.target;
    var b = brand.act1.budget;
    b.total = Number(readVal('budgetTotal', b.total));
    b.monthlyCap = Number(readVal('budgetMonthlyCap', b.monthlyCap));
    b.maxCacPerLead = Number(readVal('maxCac', b.maxCacPerLead));
  }
}

function advanceS1() {
  saveS1Step();
  var brand = currentBrand();
  var current = Number(state.screen.split('-')[1]);
  var next = current + 1;
  if (next > brand.onboardingStep) brand.onboardingStep = next;
  state.screen = 's1-' + next;
  render();
}

function backS1() {
  if (state.ui.s1Generating) return;
  var current = Number(state.screen.split('-')[1]);
  if (current <= 1) return;
  saveS1Step();
  state.screen = 's1-' + (current - 1);
  render();
}

function goToS1Step(step) {
  if (state.ui.s1Generating) return;
  var brand = currentBrand();
  if (step > brand.onboardingStep) return;
  var current = Number(state.screen.split('-')[1]);
  if (step === current) return;
  saveS1Step();
  state.screen = 's1-' + step;
  render();
}

function refreshPersonas() {
  var grid = document.getElementById('personaGrid');
  grid.classList.add('is-refreshing');
  window.setTimeout(function () {
    state.ui.s1PersonaBatch = state.ui.s1PersonaBatch === 'batch1' ? 'batch2' : 'batch1';
    grid.innerHTML = currentBrand().act1.personas[state.ui.s1PersonaBatch].map(personaCard).join('');
    grid.classList.remove('is-refreshing');
  }, 150);
}

function generateProposal() {
  state.ui.s1Generating = true;
  render();
  window.setTimeout(function () {
    var brand = currentBrand();
    brand.stage = 'proposal';
    state.ui.s1Generating = false;
    state.screen = 's2';
    render();
  }, 1200);
}

function onAct1Action(action, el) {
  if (action === 'select-goal-type') { currentBrand().act1.goalType = el.dataset.type; render(); return true; }
  if (action === 's1-next') { advanceS1(); return true; }
  if (action === 's1-back') { backS1(); return true; }
  if (action === 'goto-step') { goToS1Step(Number(el.dataset.step)); return true; }
  if (action === 'refresh-personas') { refreshPersonas(); return true; }
  if (action === 'toggle-suggestion') {
    var index = el.dataset.index;
    state.ui.s1SuggestionOpen[index] = !state.ui.s1SuggestionOpen[index];
    render();
    return true;
  }
  if (action === 'generate-proposal') { generateProposal(); return true; }
  return false;
}
