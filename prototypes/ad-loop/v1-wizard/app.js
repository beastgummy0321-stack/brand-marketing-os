/* PROTOTYPE: 所有業務資料皆由 mock-data.js 的 AD_LOOP_DATA 提供。 */
(function () {
  'use strict';

  const data = window.AD_LOOP_DATA;
  const stageLabels = ['帳號', '策略', '素材', '上線', '成效', '優化'];
  const stepTotal = stageLabels.length;
  const currency = new Intl.NumberFormat('zh-TW');
  let lifecycle = 0;
  let state = createInitialState();

  function createInitialState() {
    return {
      currentStep: 1,
      maxReached: 1,
      accountStatuses: Object.fromEntries(data.accounts.map((account) => [account.id, account.status])),
      trackingStatus: data.tracking.status,
      trackingUrl: data.tracking.url,
      analysisSet: 0,
      analysing: false,
      creativeBatches: Object.fromEntries(data.accounts.map((account) => [account.id, 'batchA'])),
      swappingPlatform: '',
      dailyCap: data.launchDefaults.dailyCap,
      pauseDays: data.launchDefaults.pauseThresholdDays,
      launching: false,
      launchNotice: false,
      selectedSuggestions: Object.fromEntries(data.suggestions.map((item) => [item.id, item.defaultChecked])),
      applying: false,
      suggestionsApplied: false,
      resetOpen: false
    };
  }

  function formatCurrency(value) {
    return `NT$${currency.format(value)}`;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (character) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    })[character]);
  }

  function icon(name) {
    const paths = {
      check: '<path d="M4 12.5 9.2 17 20 6" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5"/>',
      link: '<path d="M9.5 14.5 14.5 9.5M8 17H6.5a3.5 3.5 0 0 1 0-7H10M16 7h1.5a3.5 3.5 0 0 1 0 7H14" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="2"/>',
      meta: '<path d="M3.6 15.4 8.8 7c.8-1.3 2.1-1.3 2.9 0l1.4 2.2L15.3 6c.8-1.2 2.1-1.2 2.8.1l2.3 3.8c.8 1.3.2 2.1-1.3 2.1h-3.4l-1.8-2.8-2.6 4.1c-.8 1.2-2 1.2-2.8 0l-2.1-3.4-2.1 3.3c-.9 1.4-1.9 1.1-.7 2.2Z" fill="currentColor"/>',
      google: '<path d="M20.5 12.2c0-.6-.1-1.1-.2-1.6H12v3.1h4.8a4.1 4.1 0 0 1-1.8 2.7v2h2.9c1.7-1.6 2.6-3.8 2.6-6.2Z" fill="currentColor"/><path d="M12 20.8c2.4 0 4.4-.8 5.9-2.2l-2.9-2a5.3 5.3 0 0 1-7.9-2.8H4v2.1a8.9 8.9 0 0 0 8 4.9Z" fill="currentColor" opacity=".78"/><path d="M7.1 13.8a5.3 5.3 0 0 1 0-3.5V8.2H4A8.8 8.8 0 0 0 4 15.9l3.1-2.1Z" fill="currentColor" opacity=".56"/><path d="M12 5.2c1.5 0 2.9.5 4 1.6l3-2.9C16.4 1.5 14.4.6 12 .6A8.9 8.9 0 0 0 4 5.5l3.1 2.1A5.3 5.3 0 0 1 12 5.2Z" fill="currentColor" opacity=".9"/>',
      tiktok: '<path d="M14.8 3v11.1a3.6 3.6 0 1 1-3-3.5V7.9a6.3 6.3 0 1 0 5.7 6.3V9.3c1 .9 2.3 1.5 3.7 1.7V8.1a4.8 4.8 0 0 1-3.7-2.2A5.5 5.5 0 0 1 17 3h-2.2Z" fill="currentColor"/>',
      coffee: '<path d="M5 8h12v5.2A4.8 4.8 0 0 1 12.2 18H9.8A4.8 4.8 0 0 1 5 13.2V8Zm12 1.5h1.2a2.3 2.3 0 0 1 0 4.5H17M7 21h10M8 4c0 1 .8 1.5.8 2.5M12 4c0 1 .8 1.5.8 2.5" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"/>',
      pause: '<path d="M8 6v12M16 6v12" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="2.5"/>',
      boost: '<path d="M5 16 10 11l3 3 6-7M15 7h4v4" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.2"/>',
      swap: '<path d="M7 7h10l-2.5-2.5M17 17H7l2.5 2.5M17 7l-2.5 2.5M7 17l2.5-2.5" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>'
    };
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.link}</svg>`;
  }

  function statusText(status) {
    return { idle: '尚未連結', connecting: '連結中…', connected: '已連結' }[status];
  }

  function strategyForCurrentAnalysis() {
    return state.analysisSet === 0 ? data.strategy : data.strategyAlternate;
  }

  function selectedCount() {
    return Object.values(state.selectedSuggestions).filter(Boolean).length;
  }

  function allAccountsConnected() {
    return Object.values(state.accountStatuses).every((status) => status === 'connected');
  }

  function canAdvanceFromStepOne() {
    return allAccountsConnected() && state.trackingStatus === 'done';
  }

  function renderProgress() {
    const progress = document.querySelector('#progress');
    progress.innerHTML = stageLabels.map((label, index) => {
      const step = index + 1;
      const completed = step < state.maxReached && step !== state.currentStep;
      const current = step === state.currentStep;
      const canReturn = step !== state.currentStep && step <= state.maxReached;
      const node = canReturn ? 'button' : 'span';
      const action = canReturn ? `data-action="go-to-step" data-step="${step}"` : '';
      const check = completed ? icon('check') : '';
      return `<div class="progress-item ${completed ? 'is-complete' : ''} ${current ? 'is-current' : ''}">
        <${node} class="progress-node" ${action} ${canReturn ? 'type="button"' : ''}>
          <span class="progress-dot">${check}</span><span class="progress-label">${label}</span>
        </${node}>
        ${step < stepTotal ? '<span class="progress-line" aria-hidden="true"></span>' : ''}
      </div>`;
    }).join('');
  }

  function renderStepHeading(id, title, subtitle) {
    return `<header class="step-heading"><h1 id="${id}" tabindex="-1">${title}</h1><p>${subtitle}</p></header>`;
  }

  function renderAccount(account) {
    const status = state.accountStatuses[account.id];
    const loading = status === 'connecting';
    const connected = status === 'connected';
    const buttonContent = loading ? '<span class="button-spinner" aria-hidden="true"></span>連結中…' : connected ? `<span class="button-check">${icon('check')}</span>已連結` : '連結';
    return `<article class="account-card ${connected ? 'is-connected' : ''}">
      <span class="platform-icon">${icon(account.platform)}</span>
      <h2>${escapeHtml(account.label)}</h2>
      <p class="account-status">${statusText(status)}</p>
      <button class="secondary-button" type="button" data-action="connect" data-account="${account.id}" ${loading || connected ? 'disabled' : ''}>${buttonContent}</button>
    </article>`;
  }

  function renderStepOne() {
    const scanLoading = state.trackingStatus === 'scanning';
    const scanLabel = scanLoading ? '<span class="button-spinner" aria-hidden="true"></span>掃描中…' : '掃描追蹤碼';
    const scanResult = state.trackingStatus === 'done' ? `<p class="tracking-result">${icon('check')}已偵測到追蹤碼</p>` : '';
    return `<div class="step-card">
      ${renderStepHeading('step-1-title', '先接上帳號', 'AI 才看得到你的成效，三個平台都要接')}
      <div class="account-grid">${data.accounts.map(renderAccount).join('')}</div>
      <div class="divider"></div>
      <div class="tracking-area">
        <label><span class="field-label">貼上你的網站</span><input class="url-input" data-field="tracking-url" value="${escapeHtml(state.trackingUrl)}" aria-label="網站網址"></label>
        <button class="secondary-button" type="button" data-action="scan" ${scanLoading ? 'disabled' : ''}>${scanLabel}</button>
      </div>
      ${scanResult}
    </div>${renderFooter(1)}`;
  }

  function renderAnalysisTags(label, values) {
    return `<div class="tag-group"><span class="tag-label">${label}</span><div class="pill-row">${values.map((value) => `<span class="pill">${escapeHtml(value)}</span>`).join('')}</div></div>`;
  }

  function renderStrategy(strategy) {
    const segments = data.accounts.map((account) => {
      const percentage = strategy.split[account.platform];
      return `<span class="budget-segment ${account.platform}" style="width:${percentage}%">${escapeHtml(account.label)} ${percentage}%</span>`;
    }).join('');
    const amounts = data.accounts.map((account) => {
      const amount = Math.round(strategy.budgetTotal * strategy.split[account.platform] / 100);
      return `<span>${escapeHtml(account.label)} ${formatCurrency(amount)}</span>`;
    }).join('');
    return `<section class="strategy-card">
      <h2 class="section-title">預算怎麼分</h2>
      <div class="budget-stack" aria-label="三平台預算比例">${segments}</div>
      <div class="budget-amounts">${amounts}</div>
      <div class="strategy-summary">
        <div><span>投放目標</span><strong>${escapeHtml(strategy.goal)}</strong></div>
        <div><span>預估成果</span><strong>${strategy.estimate.ordersLow}–${strategy.estimate.ordersHigh} 筆／CPA ${formatCurrency(strategy.estimate.cpaLow)}–${formatCurrency(strategy.estimate.cpaHigh)}</strong></div>
      </div>
    </section>`;
  }

  function renderStepTwo() {
    if (state.analysing) {
      return `<div class="step-card">${renderStepHeading('step-2-title', 'AI 已經看過你的網站', '策略也幫你算好了，一鍵採用')}
        <div class="analysis-url"><span>${escapeHtml(state.trackingUrl || data.productUrl)}</span><button class="text-button" type="button" disabled>重新分析</button></div>
        <div class="launch-loading"><span class="skeleton"></span><span class="skeleton"></span><span class="skeleton"></span></div></div>${renderFooter(2)}`;
    }
    const analysis = data.productAnalysisSets[state.analysisSet];
    return `<div class="step-card">
      ${renderStepHeading('step-2-title', 'AI 已經看過你的網站', '策略也幫你算好了，一鍵採用')}
      <div class="analysis-url"><span>${escapeHtml(state.trackingUrl || data.productUrl)}</span><button class="text-button" type="button" data-action="reanalyze">重新分析</button></div>
      <section class="analysis-card"><h2 class="section-title">賣點與受眾</h2>
        ${renderAnalysisTags('賣點', analysis.sellingPoints)}
        ${renderAnalysisTags('受眾', analysis.audiences)}
        ${renderAnalysisTags('競品', analysis.competitors)}
      </section>
      ${renderStrategy(strategyForCurrentAnalysis())}
    </div>${renderFooter(2)}`;
  }

  function renderMetaCreative(item) {
    return `<article class="creative-card"><div class="meta-preview"><span class="meta-art">${icon('coffee')}</span><div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.body)}</p><span class="readonly-cta">${escapeHtml(item.cta)}</span></div></div></article>`;
  }

  function renderGoogleCreative(item) {
    return `<article class="creative-card google-card"><h3>${escapeHtml(item.headline1)}</h3><h3>${escapeHtml(item.headline2)}</h3><p class="display-url">${escapeHtml(item.displayUrl)}</p><p>${escapeHtml(item.description)}</p></article>`;
  }

  function renderTiktokCreative(item) {
    return `<article class="creative-card"><div class="tiktok-preview"><div class="tiktok-cover">${escapeHtml(item.coverLabel)}</div><div><ol class="script-list">${item.script.map((line) => `<li>${escapeHtml(line)}</li>`).join('')}</ol><span class="duration-pill">${escapeHtml(item.duration)}</span></div></div></article>`;
  }

  function renderCreativePlatform(account) {
    const batch = data.creatives[account.platform][state.creativeBatches[account.id]];
    const renderCard = { meta: renderMetaCreative, google: renderGoogleCreative, tiktok: renderTiktokCreative }[account.platform];
    return `<section class="creative-platform"><div class="creative-platform-header"><h2>${escapeHtml(account.label)}</h2><button class="secondary-button" type="button" data-action="swap-creative" data-platform="${account.id}">換一批</button></div>
      <div class="creative-grid ${state.swappingPlatform === account.id ? 'is-swapping' : ''}">${batch.map(renderCard).join('')}</div></section>`;
  }

  function renderStepThree() {
    return `<div class="step-card">${renderStepHeading('step-3-title', '素材已經生好了', '不滿意就換一批，AI 立刻重寫')}${data.accounts.map(renderCreativePlatform).join('')}</div>${renderFooter(3)}`;
  }

  function renderLaunchSummary(strategy) {
    const distribution = data.accounts.map((account) => `${account.label} ${strategy.split[account.platform]}%`).join('／');
    return `<div class="review-list">
      <div class="review-row"><span class="review-label">月預算</span><span class="review-value">${formatCurrency(strategy.budgetTotal)}<small>${distribution}</small></span></div>
      <div class="review-row"><span class="review-label">排程</span><span class="review-value">${data.launchDefaults.scheduleStart}–${data.launchDefaults.scheduleEnd}<small>共 ${data.launchDefaults.scheduleDays} 天</small></span></div>
      <div class="review-row"><span class="review-label">煞車設定</span><span class="review-value">每日上限與無轉換自動暫停</span></div>
    </div>`;
  }

  function renderStepFour() {
    if (state.launching) {
      return `<div class="step-card">${renderStepHeading('step-4-title', '正在建立投放', '保留已核可的預算與煞車設定')}
        <div class="launch-loading"><span class="skeleton"></span><span class="skeleton"></span><span class="skeleton"></span></div></div>${renderFooter(4)}`;
    }
    const limits = data.launchDefaults;
    return `<div class="step-card">
      ${renderStepHeading('step-4-title', '最後看一眼，就能上線', '預算與煞車設定已由 AI 先填好')}
      ${renderLaunchSummary(strategyForCurrentAnalysis())}
      <section class="control-block"><h2>煞車設定</h2><div class="launch-controls">
        <div><span class="field-label">日上限</span><div class="stepper"><button type="button" data-action="daily-cap" data-direction="down" ${state.dailyCap <= limits.dailyCapMin ? 'disabled' : ''} aria-label="降低日上限">−</button><output>${formatCurrency(state.dailyCap)}</output><button type="button" data-action="daily-cap" data-direction="up" ${state.dailyCap >= limits.dailyCapMax ? 'disabled' : ''} aria-label="提高日上限">＋</button></div></div>
        <label><span class="field-label">無轉換自動暫停</span><select class="select-control" data-field="pause-days">${limits.pauseThresholdOptions.map((days) => `<option value="${days}" ${state.pauseDays === days ? 'selected' : ''}>${days} 天</option>`).join('')}</select></label>
      </div></section>
    </div>${renderFooter(4)}`;
  }

  function renderTrend(trend) {
    const values = trend.map((point) => point.orders);
    const maxValue = Math.max(...values);
    const minValue = Math.min(...values);
    const range = maxValue - minValue || 1;
    const chartWidth = 700;
    const chartHeight = 160;
    const padding = { top: 16, right: 18, bottom: 28, left: 18 };
    const usableWidth = chartWidth - padding.left - padding.right;
    const usableHeight = chartHeight - padding.top - padding.bottom;
    const points = trend.map((point, index) => ({
      x: padding.left + usableWidth * index / (trend.length - 1),
      y: padding.top + usableHeight * (1 - (point.orders - minValue) / range),
      day: point.day
    }));
    const path = points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ');
    return `<svg class="trend-chart" viewBox="0 0 ${chartWidth} ${chartHeight}" role="img" aria-label="近七日訂單趨勢">
      <line class="trend-axis" x1="${padding.left}" x2="${chartWidth - padding.right}" y1="${chartHeight - padding.bottom}" y2="${chartHeight - padding.bottom}"/>
      <path class="trend-path" d="${path}"/>
      ${points.map((point) => `<circle class="trend-point" cx="${point.x}" cy="${point.y}" r="4"/><text class="trend-day" x="${point.x}" y="${chartHeight - 5}">${escapeHtml(point.day)}</text>`).join('')}
    </svg>`;
  }

  function renderMetricCards(dashboard, after) {
    const metrics = [
      { key: 'spend', label: '花費', value: formatCurrency(dashboard.spend) },
      { key: 'orders', label: '成交數', value: `${dashboard.orders} 筆` },
      { key: 'cpa', label: '每筆成本', value: formatCurrency(dashboard.cpa) },
      { key: 'roas', label: 'ROAS', value: `${dashboard.roas}×` }
    ];
    return metrics.map((metric) => `<article class="metric-card"><p class="metric-label">${metric.label}</p><p class="metric-value">${metric.value}</p>${after ? `<span class="pill is-after metric-after">優化後</span><span class="metric-comparison">${escapeHtml(dashboard.comparisons[metric.key])}</span>` : ''}</article>`).join('');
  }

  function renderPlatformBreakdown(dashboard) {
    return `<div class="platform-breakdown"><div class="platform-breakdown-head"><span>平台</span><span>花費</span><span>訂單</span><span>CPA</span><span>ROAS</span></div>${dashboard.platforms.map((item) => `<div class="platform-breakdown-row"><strong>${escapeHtml(item.name)}</strong><span>${formatCurrency(item.spend)}</span><span>${item.orders}</span><span>${formatCurrency(item.cpa)}</span><span>${item.roas}×</span></div>`).join('')}</div>`;
  }

  function renderStepFive() {
    const after = state.suggestionsApplied;
    const dashboard = after ? data.dashboardAfter : data.dashboardBefore;
    return `<div class="step-card">
      ${renderStepHeading('step-5-title', '這是目前的成績', `花 ${formatCurrency(dashboard.spend)} 元，帶來 ${dashboard.orders} 筆訂單`)}
      <div class="metrics-grid">${renderMetricCards(dashboard, after)}</div>
      <section class="trend-card"><h2>近 7 日趨勢</h2>${renderTrend(dashboard.trend7d)}</section>
      ${renderPlatformBreakdown(dashboard)}
    </div>${renderFooter(5)}`;
  }

  function renderSuggestion(item) {
    const checked = state.selectedSuggestions[item.id];
    return `<article class="suggestion-card ${checked ? 'is-selected' : ''} ${state.suggestionsApplied ? 'is-applied' : ''}">
      <span class="suggestion-icon">${icon(item.type)}</span><div><h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.reason)}</p><span class="suggestion-impact">${escapeHtml(item.impact)}</span></div>
      ${state.suggestionsApplied ? '<span class="pill is-after">已套用</span>' : `<label class="check-wrap"><input type="checkbox" data-suggestion="${item.id}" ${checked ? 'checked' : ''} aria-label="選擇${escapeHtml(item.title)}"></label>`}
    </article>`;
  }

  function renderStepSix() {
    const suggestions = state.applying ? '<div class="suggestions is-applying">' + data.suggestions.map(renderSuggestion).join('') + '</div>' : `<div class="suggestions">${data.suggestions.map(renderSuggestion).join('')}</div>`;
    return `<div class="step-card">${renderStepHeading('step-6-title', 'AI 準備了三個調整', '勾選你要的，一鍵套用')}${suggestions}</div>${renderFooter(6)}`;
  }

  function primaryFooterButton(step) {
    if (step === 1) return `<button class="primary-button" type="button" data-action="next" ${canAdvanceFromStepOne() ? '' : 'disabled'}>下一步</button>`;
    if (step === 2) return `<button class="primary-button" type="button" data-action="next" ${state.analysing ? 'disabled' : ''}>採用建議，下一步</button>`;
    if (step === 3) return '<button class="primary-button" type="button" data-action="next">下一步</button>';
    if (step === 4) return `<button class="primary-button" type="button" data-action="launch" ${state.launching ? 'disabled' : ''}>${state.launching ? '<span class="button-spinner" aria-hidden="true"></span>投放中…' : '開始投放'}</button>`;
    if (step === 5) return '<button class="primary-button" type="button" data-action="next">進到優化建議</button>';
    const count = selectedCount();
    return `<button class="primary-button" type="button" data-action="apply" ${count === 0 || state.applying || state.suggestionsApplied ? 'disabled' : ''}>${state.applying ? '<span class="button-spinner" aria-hidden="true"></span>套用中…' : `一鍵核可（${count} 項）`}</button>`;
  }

  function renderFooter(step) {
    const back = step === 1 ? '<span></span>' : '<button class="text-button" type="button" data-action="back">上一步</button>';
    return `<footer class="wizard-footer">${back}${primaryFooterButton(step)}</footer>`;
  }

  function renderSteps() {
    const renderers = [renderStepOne, renderStepTwo, renderStepThree, renderStepFour, renderStepFive, renderStepSix];
    renderers.forEach((renderer, index) => {
      const step = index + 1;
      const element = document.querySelector(`#step-${step}`);
      element.dataset.active = String(state.currentStep === step);
      element.setAttribute('aria-hidden', String(state.currentStep !== step));
      element.innerHTML = renderer();
    });
  }

  function renderNotice() {
    const notice = document.querySelector('#launch-notice');
    const visible = state.launchNotice && state.currentStep === 5;
    notice.className = `launch-notice ${visible ? 'is-visible' : ''}`;
    notice.innerHTML = visible ? `${icon('check')}已成功上線` : '';
  }

  function renderDialog() {
    document.querySelector('#reset-dialog').hidden = !state.resetOpen;
  }

  function render(focusCurrentStep) {
    renderProgress();
    renderNotice();
    renderSteps();
    renderDialog();
    if (focusCurrentStep) {
      requestAnimationFrame(() => document.querySelector(`#step-${state.currentStep} h1`)?.focus());
    }
  }

  function advance() {
    if (state.currentStep === 1 && !canAdvanceFromStepOne()) return;
    if (state.currentStep < stepTotal) {
      state.currentStep += 1;
      state.maxReached = Math.max(state.maxReached, state.currentStep);
      render(true);
    }
  }

  function goToStep(step) {
    if (step !== state.currentStep && step <= state.maxReached) {
      state.currentStep = step;
      render(true);
    }
  }

  function runLater(callback, delay) {
    const activeLifecycle = lifecycle;
    window.setTimeout(() => {
      if (activeLifecycle === lifecycle) callback();
    }, delay);
  }

  function beginLaunch() {
    state.launching = true;
    render();
    runLater(() => {
      state.launching = false;
      state.currentStep = 5;
      state.maxReached = Math.max(state.maxReached, state.currentStep);
      state.launchNotice = true;
      render(true);
      runLater(() => {
        state.launchNotice = false;
        render();
      }, 3000);
    }, 1500);
  }

  function applySuggestions() {
    if (selectedCount() === 0 || state.suggestionsApplied) return;
    state.applying = true;
    render();
    runLater(() => {
      state.applying = false;
      state.suggestionsApplied = true;
      state.currentStep = 5;
      render(true);
    }, 1200);
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-action]');
    if (!button || button.disabled) return;
    const action = button.dataset.action;
    if (action === 'connect') {
      const account = button.dataset.account;
      state.accountStatuses[account] = 'connecting';
      render();
      runLater(() => { state.accountStatuses[account] = 'connected'; render(); }, 1000);
    }
    if (action === 'scan') {
      state.trackingStatus = 'scanning';
      render();
      runLater(() => { state.trackingStatus = 'done'; render(); }, 800);
    }
    if (action === 'reanalyze') {
      state.analysing = true;
      render();
      runLater(() => { state.analysisSet = state.analysisSet === 0 ? 1 : 0; state.analysing = false; render(); }, 1000);
    }
    if (action === 'swap-creative') {
      const platform = button.dataset.platform;
      state.swappingPlatform = platform;
      render();
      runLater(() => {
        state.creativeBatches[platform] = state.creativeBatches[platform] === 'batchA' ? 'batchB' : 'batchA';
        state.swappingPlatform = '';
        render();
      }, 150);
    }
    if (action === 'daily-cap') {
      const direction = button.dataset.direction === 'up' ? 1 : -1;
      const limits = data.launchDefaults;
      state.dailyCap = Math.min(limits.dailyCapMax, Math.max(limits.dailyCapMin, state.dailyCap + direction * limits.dailyCapStep));
      render();
    }
    if (action === 'next') advance();
    if (action === 'back' && state.currentStep > 1) { state.currentStep -= 1; render(true); }
    if (action === 'go-to-step') goToStep(Number(button.dataset.step));
    if (action === 'launch') beginLaunch();
    if (action === 'apply') applySuggestions();
    if (action === 'request-reset') { state.resetOpen = true; render(); }
    if (action === 'cancel-reset') { state.resetOpen = false; render(); }
    if (action === 'confirm-reset') { lifecycle += 1; state = createInitialState(); render(true); }
  });

  document.addEventListener('input', (event) => {
    if (event.target.dataset.field === 'tracking-url') state.trackingUrl = event.target.value;
  });

  document.addEventListener('change', (event) => {
    if (event.target.dataset.field === 'pause-days') state.pauseDays = Number(event.target.value);
    if (event.target.dataset.suggestion && !state.suggestionsApplied) state.selectedSuggestions[event.target.dataset.suggestion] = event.target.checked;
    render();
  });

  render(true);
}());
