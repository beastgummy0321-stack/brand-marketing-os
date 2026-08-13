/* 核心：狀態、畫面切換、共用 header／小工具。S1/S2/S3 各自畫面邏輯在 act1.js／act2.js／act3.js。 */

var state;
var appEl = document.getElementById('app');
var headerInnerEl = document.getElementById('headerInner');
var progressTrackEl = document.getElementById('progressTrack');
var progressStepsEl = document.getElementById('progressSteps');
var launchOverlayEl = document.getElementById('launchOverlay');

var STAGE_BADGE = { onboarding: '開戶訪談中', proposal: '提案書待核可', operating: '營運中' };
var BRAND_ORDER = ['lumibrew', 'misttea', 'sunbook'];
var S1_STEP_NAMES = ['聽產品', '目標變數字', '描述買的人', '健檢'];

function clone(data) {
  return JSON.parse(JSON.stringify(data));
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

function defaultUi() {
  return {
    brandMenuOpen: false,
    s1PersonaBatch: 'batch1',
    s1SuggestionOpen: {},
    s2: { activePlatform: 'meta', activeBatches: { meta: 'batch1', google: 'batch1', tiktok: 'batch1' }, dailyCapError: false },
    s3: { activeTab: 't1', optimized: false, executingWeekly: false }
  };
}

function resetState() {
  state = {
    brandId: null,
    screen: 's0',
    brands: clone(mockData.brands),
    draftSeq: 0,
    ui: defaultUi()
  };
}

function currentBrand() {
  return state.brandId ? state.brands[state.brandId] : null;
}

function screenForBrand(brand) {
  if (brand.stage === 'onboarding') return 's1-' + brand.onboardingStep;
  if (brand.stage === 'proposal') return 's2';
  return 's3';
}

function enterBrand(brandId) {
  state.brandId = brandId;
  state.ui = defaultUi();
  state.screen = screenForBrand(state.brands[brandId]);
  render();
  window.scrollTo({ top: 0, behavior: 'auto' });
}

function backToList() {
  state.brandId = null;
  state.screen = 's0';
  state.ui = defaultUi();
  render();
  window.scrollTo({ top: 0, behavior: 'auto' });
}

function addNewBrand() {
  state.draftSeq += 1;
  var id = 'draft' + state.draftSeq;
  state.brands[id] = clone(mockData.draftBrandTemplate);
  enterBrand(id);
}

/* ---- render 分派 ---- */

function render() {
  renderHeader();
  renderProgressTrack();
  if (state.screen === 's0') appEl.innerHTML = renderS0();
  else if (state.screen.indexOf('s1-') === 0) appEl.innerHTML = renderAct1(state.screen);
  else if (state.screen === 's2') appEl.innerHTML = renderAct2();
  else if (state.screen === 's3') appEl.innerHTML = renderAct3();
}

function renderHeader() {
  var screen = state.screen;
  if (screen === 's0') {
    headerInnerEl.innerHTML = '<a class="brand" href="#top">代操中控台</a>'
      + '<button class="button button--quiet" type="button" data-action="new-brand">＋新品牌</button>';
    return;
  }
  if (screen.indexOf('s1-') === 0) {
    headerInnerEl.innerHTML = '<a class="brand" href="#top">代操中控台</a><span></span>';
    return;
  }
  var brand = currentBrand();
  var menuOpen = state.ui.brandMenuOpen;
  var items = BRAND_ORDER.map(function (id) {
    var b = state.brands[id];
    return '<button class="brand-switcher__item" type="button" data-action="select-brand" data-brand="' + id + '">'
      + '<span>' + escapeHtml(b.name) + '</span>'
      + '<span class="badge badge--' + b.stage + '">' + STAGE_BADGE[b.stage] + '</span></button>';
  }).join('');
  headerInnerEl.innerHTML = '<button class="text-button" type="button" data-action="back-to-list">← 返回列表</button>'
    + '<div class="header-mid"><div class="brand-switcher' + (menuOpen ? ' is-open' : '') + '">'
    + '<button class="brand-switcher__trigger" type="button" data-action="toggle-brand-menu" aria-expanded="' + menuOpen + '">'
    + escapeHtml(brand.name) + ' ⌄</button>'
    + '<div class="brand-switcher__menu" role="menu">' + items + '</div></div></div>'
    + '<div class="header-right">'
    + '<span class="health-dot health-dot--' + brand.healthLight + '" title="健康燈"></span>'
    + '<button class="text-button" type="button" data-action="reset">重設示範</button></div>';
}

function renderProgressTrack() {
  if (state.screen.indexOf('s1-') !== 0) {
    progressTrackEl.classList.add('is-hidden');
    return;
  }
  progressTrackEl.classList.remove('is-hidden');
  var brand = currentBrand();
  var current = Number(state.screen.split('-')[1]);
  var maxReached = brand.onboardingStep;
  progressStepsEl.innerHTML = S1_STEP_NAMES.map(function (name, index) {
    var n = index + 1;
    var reached = n <= maxReached;
    var isCurrent = n === current;
    var clickable = reached && !isCurrent && !state.ui.s1Generating;
    var mark = isCurrent ? String(n) : (reached ? '✓' : String(n));
    var inner = '<span class="step-dot">' + mark + '</span>' + name;
    var content = clickable
      ? '<button class="step-track-item" type="button" data-action="goto-step" data-step="' + n + '">' + inner + '</button>'
      : '<span class="step-track-item">' + inner + '</span>';
    return '<li class="' + (reached ? 'is-complete' : '') + (clickable ? ' is-clickable' : '') + '">' + content + '</li>';
  }).join('');
}

/* ---- S0 品牌列表 ---- */

function renderS0() {
  var cards = BRAND_ORDER.map(function (id) { return brandCard(id, state.brands[id]); }).join('');
  return '<div class="s0-header"><div><h1>你的品牌</h1><p>共 3 個品牌</p></div></div>'
    + '<div class="brand-grid">' + cards + '</div>';
}

function brandCard(id, brand) {
  var summary = brand.stage === 'operating'
    ? '本月花費 ' + money(brand.monthSummary.spend) + '／成果 ' + brand.monthSummary.result + ' 筆'
    : '尚未開始投放';
  return '<button class="brand-card card" type="button" data-action="enter-brand" data-brand="' + id + '">'
    + '<div class="brand-card__top"><span class="brand-card__name">' + escapeHtml(brand.name) + '</span>'
    + '<span class="badge badge--' + brand.stage + '">' + STAGE_BADGE[brand.stage] + '</span></div>'
    + '<div class="brand-card__meta"><span class="health-dot health-dot--' + brand.healthLight + '"></span>'
    + '<span>' + summary + '</span></div></button>';
}

function onS0Action(action, el) {
  if (action === 'enter-brand') { enterBrand(el.dataset.brand); return true; }
  if (action === 'new-brand') { addNewBrand(); return true; }
  return false;
}

/* ---- 全畫面共用動作（header 上的按鈕，任何畫面都可能觸發） ---- */

function onGlobalAction(action, el) {
  if (action === 'back-to-list') { backToList(); return true; }
  if (action === 'reset') { resetState(); render(); window.scrollTo({ top: 0, behavior: 'auto' }); return true; }
  if (action === 'toggle-brand-menu') { state.ui.brandMenuOpen = !state.ui.brandMenuOpen; render(); return true; }
  if (action === 'select-brand') { enterBrand(el.dataset.brand); return true; }
  return false;
}

/* ---- 事件委派 ---- */

document.addEventListener('click', function (event) {
  var el = event.target.closest('[data-action]');
  if (!el || el.disabled) return;
  var action = el.dataset.action;
  if (onGlobalAction(action, el)) return;
  if (state.screen === 's0' && onS0Action(action, el)) return;
  if (state.screen.indexOf('s1-') === 0) onAct1Action(action, el);
  else if (state.screen === 's2') onAct2Action(action, el);
  else if (state.screen === 's3') onAct3Action(action, el);
});

document.addEventListener('input', function (event) {
  var slider = event.target.closest('[data-slider]');
  if (!slider) return;
  var out = slider.parentElement.querySelector('.slider-value');
  var suffix = slider.dataset.suffix || '';
  var prefix = slider.dataset.prefix || '';
  if (out) out.textContent = prefix + formatNumber(slider.value) + suffix;
});

document.addEventListener('blur', function (event) {
  if (state.screen === 's2') onAct2Blur(event);
}, true);

document.addEventListener('change', function (event) {
  if (state.screen === 's3') onAct3Change(event);
});

resetState();
render();
