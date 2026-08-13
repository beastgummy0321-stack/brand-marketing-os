(function () {
  "use strict";

  const app = document.getElementById("app");
  const modalRoot = document.getElementById("modal-root");
  const toast = document.getElementById("toast");
  let toastTimer;

  const ICON_PATHS = {
    plug: '<path d="M8 3v5M16 3v5M6 8h12v2a6 6 0 0 1-6 6v5M9 21h6"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    play: '<path d="m8 5 11 7-11 7Z"/>',
    bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.37a1.7 1.7 0 0 0-1 .63 1.7 1.7 0 0 0-.4 1.1V21h-4v-.09A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.13 15a1.7 1.7 0 0 0-.63-1 1.7 1.7 0 0 0-1.1-.4H2v-4h.4A1.7 1.7 0 0 0 4.13 9a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 8.5 4.6a1.7 1.7 0 0 0 1-.63 1.7 1.7 0 0 0 .4-1.1V3h4v.09A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.17.42.4.76.63 1 .31.3.7.4 1.1.4H22v4h-.87a1.7 1.7 0 0 0-1.73.6Z"/>',
    trend: '<path d="M4 17 10 11l4 4 6-8"/><path d="M15 7h5v5"/>',
    pause: '<rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/>',
    refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 8.5A7 7 0 0 1 18.7 7L20 12M4 12l1.3 5A7 7 0 0 0 17.9 15.5"/>',
    warning: '<path d="M10.3 3.6 2.5 17.1A2 2 0 0 0 4.2 20h15.6a2 2 0 0 0 1.7-2.9L13.7 3.6a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
    x: '<path d="m6 6 12 12M18 6 6 18"/>',
    back: '<path d="m15 18-6-6 6-6"/>',
    arrow: '<path d="M5 12h14M14 7l5 5-5 5"/>',
    meta: '<path d="M4 16c2.2-7.5 4-10 6-10 2.8 0 4.4 8 6.8 8 1.1 0 2-1 3.2-4M4 16c-.8 2.5-2.5 2.5-2-.5C3 10.5 5.5 6 8 6c3.5 0 5.5 12 8.5 12 2.2 0 3.8-3.5 3.5-8"/>',
    google: '<path d="M20 12h-8M20 12a8 8 0 1 1-2.3-5.7"/>',
    tiktok: '<path d="M14 4v11a4 4 0 1 1-4-4M14 4c.6 3 2.5 4.5 5 5"/>',
    inbox: '<path d="M4 4h16v16H4Z"/><path d="M4 14h4l2 3h4l2-3h4"/>'
  };

  function icon(name, extraClass) {
    return `<svg class="icon ${extraClass || ""}" viewBox="0 0 24 24" aria-hidden="true">${ICON_PATHS[name] || ICON_PATHS.inbox}</svg>`;
  }

  function createInitialState() {
    return {
      view: "onboarding",
      onboardingStep: 1,
      accounts: { meta: false, google: false, tiktok: false },
      busyAccounts: { meta: false, google: false, tiktok: false },
      trackingDetected: false,
      trackingBusy: false,
      trackingUrl: MOCK.tracking.url,
      pitch: MOCK.brandInput.pitch,
      analyzed: false,
      analysisBusy: false,
      batchIndex: { meta: 0, google: 0, tiktok: 0 },
      launching: false,
      stage: "setup",
      remainingProposalIds: MOCK.decisionInbox.map((proposal) => proposal.id),
      appliedProposalIds: [],
      isOptimized: false,
      performanceMode: "before",
      autoPilot: true,
      settings: { ...MOCK.launchSettings },
      modal: null,
      lastUpdated: new Date()
    };
  }

  window.state = createInitialState();
  const getState = () => window.state;
  const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
  const number = (value) => new Intl.NumberFormat("zh-TW").format(value);
  const money = (value) => `NT$${number(value)}`;

  function platformIcon(key, extraClass) {
    return icon(key, extraClass);
  }

  function renderBrand() {
    return `<div class="brand-lockup">
      <span class="brand-mark">${icon("trend")}</span>
      <div><div class="brand-name">沐光咖啡 <span>LumiBrew</span></div></div>
    </div>`;
  }

  function renderStepDots(current) {
    return `<div class="step-dots" aria-label="啟用進度">${[1, 2, 3, 4].map((step) => `<span class="step-dot ${step === current ? "is-active" : ""} ${step < current ? "is-done" : ""}" aria-label="第 ${step} 步"></span>`).join("")}</div>`;
  }

  function renderStepHeading(step, title, subtitle) {
    return `<header class="step-heading"><span class="step-count">${step} / 4</span><h1>${title}</h1><p>${subtitle}</p></header>`;
  }

  function onboardingFrame(content) {
    const state = getState();
    return `<section class="screen onboarding-shell" data-screen="onboarding">
      <header class="onboarding-header">
        <div class="onboarding-brand">${renderBrand()}<span class="onboarding-title">啟用自動駕駛</span></div>
        <div class="topbar-actions">${renderStepDots(state.onboardingStep)}<button class="ghost-button" type="button" data-action="open-reset">重設示範</button></div>
      </header>
      <main class="onboarding-content">${content}</main>
    </section>`;
  }

  function renderAccountCard(key, name) {
    const state = getState();
    const connected = state.accounts[key];
    const busy = state.busyAccounts[key];
    const label = MOCK.accounts[key].label;
    let button = "連結";
    if (busy) button = `${'<span class="spinner"></span>'}連接中…`;
    if (connected) button = `${icon("check")}已連結`;
    return `<article class="account-card ${connected ? "is-connected" : ""}">
      <span class="platform-symbol">${platformIcon(key)}</span>
      <div class="account-copy"><strong>${name}</strong><span>${escapeHtml(label)}</span></div>
      <button class="secondary-button" type="button" data-action="connect" data-platform="${key}" ${busy || connected ? "disabled" : ""}>${button}</button>
    </article>`;
  }

  function renderStepOne() {
    const state = getState();
    const ready = Object.values(state.accounts).every(Boolean) && state.trackingDetected;
    return onboardingFrame(`${renderStepHeading(1, "連結廣告帳號", "三個平台都要連上才能開始")}
      <div class="stack">
        ${renderAccountCard("meta", "Meta")}
        ${renderAccountCard("google", "Google")}
        ${renderAccountCard("tiktok", "TikTok")}
      </div>
      <div class="section-divider"></div>
      <div class="field-group">
        <label for="tracking-url">追蹤碼精靈</label>
        <div class="input-row">
          <input id="tracking-url" type="text" value="${escapeHtml(state.trackingUrl)}" autocomplete="url">
          <button class="secondary-button" type="button" data-action="detect-tracking" ${state.trackingBusy ? "disabled" : ""}>${state.trackingBusy ? '<span class="spinner"></span>偵測中…' : "偵測追蹤碼"}</button>
        </div>
        <p class="result-line" role="status">${state.trackingDetected ? "已偵測到追蹤碼 ✓" : ""}</p>
      </div>
      <div class="step-actions"><button class="primary-button" type="button" data-action="next-step" ${ready ? "" : "disabled"}>下一步 ${icon("arrow")}</button></div>`);
  }

  function renderAnalysis() {
    const analysis = MOCK.aiAnalysis;
    const column = (title, items) => `<section class="analysis-column"><h3>${title}</h3><ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>`;
    const split = MOCK.strategy.budgetSplit;
    return `<div class="analysis-grid">
      ${column("賣點", analysis.sellingPoints)}
      ${column("受眾", analysis.audiences)}
      ${column("競品", analysis.competitors)}
    </div>
    <section class="strategy-panel">
      <h3>投放策略</h3>
      <span class="field-label">預算分配</span>
      <div class="budget-segments" aria-label="Meta 45%，Google 35%，TikTok 20%"><span></span><span></span><span></span></div>
      <div class="budget-legend mono"><span>Meta ${split.meta}%</span><span>Google ${split.google}%</span><span>TikTok ${split.tiktok}%</span></div>
      <div class="strategy-facts">
        <div><span class="fact-label">投放目標</span><span class="fact-value">${MOCK.strategy.objective}</span></div>
        <div><span class="fact-label">預估成果</span><span class="fact-value mono">${MOCK.strategy.forecastOrders.low}-${MOCK.strategy.forecastOrders.high} 筆/月</span></div>
        <div><span class="fact-label">預估 ROAS</span><span class="fact-value mono">${MOCK.strategy.forecastRoas.low}-${MOCK.strategy.forecastRoas.high}</span></div>
      </div>
    </section>`;
  }

  function renderStepTwo() {
    const state = getState();
    return onboardingFrame(`${renderStepHeading(2, "產品與策略", "一句話，AI幫你分析")}
      <div class="field-group">
        <label for="brand-pitch">產品介紹</label>
        <div class="input-row">
          <input id="brand-pitch" type="text" value="${escapeHtml(state.pitch)}">
          <button class="primary-button" type="button" data-action="analyze" ${state.analysisBusy ? "disabled" : ""}>${state.analysisBusy ? '<span class="spinner"></span>分析中…' : "分析"}</button>
        </div>
      </div>
      ${state.analysisBusy ? '<div class="skeleton" aria-label="分析中"><span></span><span></span><span></span></div>' : ""}
      ${state.analyzed ? renderAnalysis() : ""}
      <div class="step-actions"><button class="ghost-button" type="button" data-action="previous-step">${icon("back")}上一步</button><button class="primary-button" type="button" data-action="next-step" ${state.analyzed ? "" : "disabled"}>下一步 ${icon("arrow")}</button></div>`);
  }

  function renderCreativeCard(platform, item) {
    if (platform === "meta") {
      return `<article class="creative-card meta-card"><div class="creative-thumb" style="background:${item.thumbColor}"></div><div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.body)}</p></div></article>`;
    }
    if (platform === "google") {
      return `<article class="creative-card"><span class="ad-url mono">${escapeHtml(item.url)}</span><h3>${escapeHtml(item.headline)}</h3><p>${escapeHtml(item.desc)}</p></article>`;
    }
    return `<article class="creative-card script-card"><div class="script-cover" style="background:${item.coverColor}"></div><ol class="script-lines">${item.script.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ol></article>`;
  }

  function renderCreativeSection(platform, title) {
    const state = getState();
    const batch = MOCK.creatives[platform][state.batchIndex[platform]];
    return `<section class="creative-section" data-creative="${platform}">
      <div class="creative-header"><h2>${title}</h2><button class="secondary-button" type="button" data-action="swap-batch" data-platform="${platform}">${icon("refresh")}換一批</button></div>
      <div class="creative-content">${batch.map((item) => renderCreativeCard(platform, item)).join("")}</div>
    </section>`;
  }

  function renderStepThree() {
    return onboardingFrame(`${renderStepHeading(3, "素材產線", "每個平台先給你兩則，看不順眼就換")}
      ${renderCreativeSection("meta", "Meta 圖文")}
      ${renderCreativeSection("google", "Google 搜尋廣告")}
      ${renderCreativeSection("tiktok", "TikTok 短影音")}
      <div class="step-actions"><button class="ghost-button" type="button" data-action="previous-step">${icon("back")}上一步</button><button class="primary-button" type="button" data-action="next-step">下一步 ${icon("arrow")}</button></div>`);
  }

  function renderStepFour() {
    const state = getState();
    return onboardingFrame(`${renderStepHeading(4, "核可上線", "確認預算與煞車設定")}
      <h2>投放總覽</h2>
      <table class="overview-table">
        <tbody>
          <tr><th scope="row">月預算</th><td class="table-number">NT$30,000</td></tr>
          <tr><th scope="row">平台分配</th><td class="table-number">Meta 13,500 · Google 10,500 · TikTok 6,000</td></tr>
          <tr><th scope="row">投放目標</th><td>${MOCK.strategy.objective}</td></tr>
          <tr><th scope="row">排程</th><td>今日起持續投放</td></tr>
        </tbody>
      </table>
      <section class="settings-panel"><h2>煞車設定</h2>
        <div class="settings-grid">
          <div class="field-group"><label for="daily-cap">日上限</label><div class="input-with-unit"><input id="daily-cap" class="mono" type="number" min="100" step="100" value="${state.settings.dailyCapNT}"><span class="input-unit">元</span></div></div>
          <div class="field-group"><label for="pause-hours">無轉換自動暫停</label><div class="input-with-unit"><input id="pause-hours" class="mono" type="number" min="1" value="${state.settings.noConversionPauseHours}"><span class="input-unit">小時</span></div></div>
        </div>
      </section>
      <button class="primary-button full-width launch-button" type="button" data-action="launch" ${state.launching ? "disabled" : ""}>${state.launching ? '<span class="spinner"></span>投放啟動中…' : `${icon("play")}開始投放`}</button>
      <div class="step-actions"><button class="ghost-button" type="button" data-action="previous-step" ${state.launching ? "disabled" : ""}>${icon("back")}上一步</button></div>`);
  }

  function renderOnboarding() {
    const step = getState().onboardingStep;
    if (step === 1) return renderStepOne();
    if (step === 2) return renderStepTwo();
    if (step === 3) return renderStepThree();
    return renderStepFour();
  }

  function healthDetails() {
    const state = getState();
    if (!state.autoPilot) return { health: "amber", label: "手動接管中" };
    const data = MOCK.cockpit[state.isOptimized ? "after" : "before"];
    const labels = { green: "正常運作", amber: "需留意", red: "已停止" };
    return { health: data.health, label: labels[data.health] };
  }

  function renderCockpit() {
    const state = getState();
    const data = MOCK.cockpit[state.isOptimized ? "after" : "before"];
    const status = healthDetails();
    const pending = state.remainingProposalIds.length;
    const time = state.lastUpdated.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", hour12: false });
    return `<section class="screen cockpit-shell" data-screen="cockpit">
      <header class="cockpit-topbar">
        <div class="cockpit-status"><span class="status-light ${status.health}"></span><div class="status-copy"><strong>${status.label}</strong><span class="update-time">最後更新 ${time}</span></div></div>
        <div class="topbar-actions">
          <button class="icon-button inbox-button" type="button" data-action="open-inbox" aria-label="決策收件匣，${pending}則待處理" title="${pending}則待處理">${icon("bell", "icon-lg")}${pending ? `<span class="count-badge">${pending}</span>` : ""}</button>
          <button class="icon-button" type="button" data-action="open-cruise" aria-label="巡航設定" title="巡航設定">${icon("gear", "icon-lg")}</button>
          <button class="ghost-button" type="button" data-action="open-reset">重設示範</button>
        </div>
      </header>
      <main class="cockpit-main">
        <div class="section-title-row">${renderBrand()}${state.isOptimized ? '<span class="optimized-badge">已套用優化</span>' : ""}</div>
        <section class="metrics-grid" aria-label="今日成效摘要">
          <div class="metric"><span class="metric-label">今日花費</span><strong class="metric-value">${money(data.spendToday)}</strong><p class="metric-explain">花${number(data.spendToday)}元帶來${data.ordersToday}筆訂單</p></div>
          <div class="metric"><span class="metric-label">今日訂單</span><strong class="metric-value">${data.ordersToday}<small> 筆</small></strong><p class="metric-explain">每筆成本 ${money(Math.round(data.spendToday / data.ordersToday))}</p></div>
          <div class="metric"><span class="metric-label">ROAS</span><strong class="metric-value">${data.roas.toFixed(1)}</strong><p class="metric-explain">每花1元，帶回${data.roas.toFixed(1)}元營收</p></div>
        </section>
        <section class="platform-section">
          <div class="section-title-row"><h2>三平台即時狀態</h2></div>
          <table class="platform-table"><thead><tr><th>平台</th><th>花費</th><th>訂單</th><th>CPO</th><th>狀態</th></tr></thead><tbody>
            ${data.platforms.map((platform) => `<tr><td><span class="platform-name">${platformIcon(platform.key)}${platform.name}</span></td><td class="table-number">${money(platform.spend)}</td><td class="table-number">${platform.orders}</td><td class="table-number">${money(platform.cpo)}</td><td><span class="platform-name"><span class="status-light ${platform.health}"></span>${({ green: "正常", amber: "留意", red: "已停止" })[platform.health]}</span></td></tr>`).join("")}
          </tbody></table>
        </section>
        <div class="cockpit-footer-link"><button class="text-link" type="button" data-action="open-performance">查看完整成效 ${icon("arrow")}</button></div>
      </main>
    </section>`;
  }

  function chartSvg(performance) {
    const width = 760;
    const height = 240;
    const left = 34;
    const right = 22;
    const top = 24;
    const bottom = 48;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const pointString = (values) => {
      const max = Math.max(...values) * 1.08;
      return values.map((value, index) => `${left + (index * plotWidth / 6)},${top + plotHeight - (value / max * plotHeight)}`).join(" ");
    };
    const circles = (values, className) => {
      const max = Math.max(...values) * 1.08;
      return values.map((value, index) => `<circle class="${className}" cx="${left + (index * plotWidth / 6)}" cy="${top + plotHeight - (value / max * plotHeight)}" r="3"/>`).join("");
    };
    return `<svg class="trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="chart-title chart-desc">
      <title id="chart-title">近7日花費與訂單趨勢</title><desc id="chart-desc">藍線為花費，綠線為訂單。</desc>
      ${[0, 1, 2, 3].map((row) => `<line class="chart-grid" x1="${left}" x2="${width - right}" y1="${top + row * plotHeight / 3}" y2="${top + row * plotHeight / 3}"/>`).join("")}
      <polyline class="chart-spend" points="${pointString(performance.spend)}"/>${circles(performance.spend, "chart-point-spend")}
      <polyline class="chart-orders" points="${pointString(performance.orders)}"/>${circles(performance.orders, "chart-point-orders")}
      ${performance.days.map((day, index) => `<text class="chart-label" x="${left + index * plotWidth / 6}" y="${height - 14}" text-anchor="middle">${day}</text>`).join("")}
    </svg>`;
  }

  function renderPerformance() {
    const state = getState();
    const mode = state.performanceMode;
    const performance = MOCK.performance[mode];
    const data = MOCK.cockpit[mode];
    return `<section class="screen performance-shell" data-screen="performance">
      <header class="subpage-topbar">
        <div class="back-title"><button class="ghost-button" type="button" data-action="back-cockpit">${icon("back")}返回駕駛艙</button><h1>成效</h1></div>
        <div class="segment-control" role="group" aria-label="成效資料版本"><button class="segment-button ${mode === "before" ? "is-active" : ""}" type="button" data-action="performance-mode" data-mode="before">優化前</button><button class="segment-button ${mode === "after" ? "is-active" : ""}" type="button" data-action="performance-mode" data-mode="after">優化後</button></div>
        ${state.isOptimized ? '<span class="optimized-badge">已套用優化</span>' : "<span></span>"}
      </header>
      <main class="performance-main"><div class="performance-content">
        <p class="plain-summary">${performance.summary}</p>
        <section class="chart-panel"><div class="chart-header"><h2>近7日趨勢</h2><div class="chart-legend"><span class="legend-item"><span class="legend-line"></span>花費</span><span class="legend-item"><span class="legend-line orders"></span>訂單</span></div></div>${chartSvg(performance)}</section>
        <section class="performance-table-wrap"><div class="section-title-row"><h2>三平台分列</h2></div><table class="performance-table"><thead><tr><th>平台</th><th>花費</th><th>訂單</th><th>每筆成本</th><th>ROAS</th></tr></thead><tbody>
          ${data.platforms.map((platform) => `<tr><td><span class="platform-name">${platformIcon(platform.key)}${platform.name}</span></td><td class="table-number">${money(platform.spend)}</td><td class="table-number">${platform.orders}</td><td class="table-number">${money(platform.cpo)}</td><td class="table-number">${platform.roas.toFixed(1)}</td></tr>`).join("")}
        </tbody></table></section>
      </div></main>
    </section>`;
  }

  function renderProposal(proposal) {
    return `<article class="proposal-card" data-proposal-id="${proposal.id}">
      <div class="proposal-main"><span class="proposal-icon">${icon(proposal.icon)}</span><div class="proposal-copy"><h3>${proposal.title}</h3><p>${proposal.reason}</p></div><span class="impact-pill ${proposal.type}">${proposal.impact}</span></div>
      <div class="proposal-actions"><button class="ghost-button button-danger" type="button" data-action="reject-proposal" data-id="${proposal.id}">${icon("x")}駁回</button><button class="primary-button" type="button" data-action="approve-proposal" data-id="${proposal.id}">${icon("check")}核可</button></div>
    </article>`;
  }

  function renderInbox() {
    const state = getState();
    const proposals = MOCK.decisionInbox.filter((proposal) => state.remainingProposalIds.includes(proposal.id));
    return `<section class="screen inbox-shell" data-screen="inbox">
      <header class="subpage-topbar">
        <button class="ghost-button" type="button" data-action="back-cockpit">${icon("back")}返回駕駛艙</button>
        <div class="inbox-title-row"><h1>決策收件匣</h1><span class="remaining-count">${proposals.length}則待處理</span></div>
        <button class="primary-button" type="button" data-action="approve-all" ${proposals.length ? "" : "disabled"}>${icon("check")}全部核可</button>
      </header>
      <main class="inbox-main">${proposals.length ? `<div class="proposal-list">${proposals.map(renderProposal).join("")}</div>` : `<div class="empty-state"><div class="empty-state-inner"><span class="empty-icon">${icon("check", "icon-lg")}</span><p>目前沒有待處理提案，系統持續監控中</p></div></div>`}</main>
    </section>`;
  }

  function render() {
    const view = getState().view;
    app.innerHTML = view === "onboarding" ? renderOnboarding() : view === "cockpit" ? renderCockpit() : view === "performance" ? renderPerformance() : renderInbox();
    renderModal();
  }

  function renderModal() {
    const state = getState();
    document.body.style.overflow = state.modal ? "hidden" : "";
    if (!state.modal) {
      modalRoot.innerHTML = "";
      return;
    }
    if (state.modal === "reset") {
      modalRoot.innerHTML = `<div id="modal-backdrop" class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="reset-title"><header class="modal-header"><h2 id="reset-title">重設示範</h2><button class="icon-button" type="button" data-action="close-modal" aria-label="關閉">${icon("x")}</button></header><div class="modal-body"><p>確認要重新開始整個示範流程嗎？</p></div><footer class="modal-footer"><button class="secondary-button" type="button" data-action="close-modal">取消</button><button class="primary-button" type="button" data-action="confirm-reset">確認重設</button></footer></section></div>`;
    } else {
      modalRoot.innerHTML = `<div id="modal-backdrop" class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="cruise-title"><header class="modal-header"><h2 id="cruise-title">巡航設定</h2><button class="icon-button" type="button" data-action="close-modal" aria-label="關閉">${icon("x")}</button></header><div class="modal-body">
        <div class="field-group"><label for="modal-daily-cap">日上限</label><div class="input-with-unit"><input id="modal-daily-cap" class="mono" type="number" min="100" step="100" value="${state.settings.dailyCapNT}"><span class="input-unit">元</span></div></div>
        <div class="field-group"><label for="modal-pause-hours">無轉換自動暫停</label><div class="input-with-unit"><input id="modal-pause-hours" class="mono" type="number" min="1" value="${state.settings.noConversionPauseHours}"><span class="input-unit">小時</span></div></div>
        <div class="switch-row"><span>自動駕駛</span><label class="switch"><input id="auto-pilot-toggle" type="checkbox" ${state.autoPilot ? "checked" : ""}><span class="switch-track"></span></label></div>
      </div><footer class="modal-footer"><button class="secondary-button" type="button" data-action="close-modal">取消</button><button class="primary-button" type="button" data-action="save-cruise">儲存</button></footer></section></div>`;
    }
    window.setTimeout(() => modalRoot.querySelector("button, input")?.focus(), 0);
  }

  function showToast(message) {
    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("is-visible");
    toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 3000);
  }

  function transition(change) {
    const screen = app.querySelector(".screen");
    if (screen) screen.classList.add("is-leaving");
    window.setTimeout(() => {
      change();
      render();
    }, reducedMotion() ? 0 : 150);
  }

  function removeProposal(id, approved) {
    const state = getState();
    const proposal = MOCK.decisionInbox.find((item) => item.id === id);
    const card = app.querySelector(`[data-proposal-id="${id}"]`);
    card?.classList.add("is-removing");
    window.setTimeout(() => {
      state.remainingProposalIds = state.remainingProposalIds.filter((proposalId) => proposalId !== id);
      if (approved && !state.appliedProposalIds.includes(id)) state.appliedProposalIds.push(id);
      if (!state.remainingProposalIds.length && state.appliedProposalIds.length === MOCK.decisionInbox.length) {
        state.isOptimized = true;
        state.performanceMode = "after";
      }
      render();
      showToast(approved ? `已核可：${proposal.title}` : "已駁回，24小時內不再提醒");
    }, reducedMotion() ? 0 : 250);
  }

  function approveAll() {
    const state = getState();
    const cards = [...app.querySelectorAll(".proposal-card")];
    cards.forEach((card, index) => window.setTimeout(() => card.classList.add("is-removing"), reducedMotion() ? 0 : index * 60));
    const totalDelay = reducedMotion() ? 0 : cards.length * 60 + 250;
    window.setTimeout(() => {
      state.remainingProposalIds.forEach((id) => {
        if (!state.appliedProposalIds.includes(id)) state.appliedProposalIds.push(id);
      });
      state.remainingProposalIds = [];
      state.isOptimized = true;
      state.performanceMode = "after";
      state.lastUpdated = new Date();
      render();
      showToast("已核可全部提案，成效資料已切換");
    }, totalDelay);
  }

  app.addEventListener("input", (event) => {
    const state = getState();
    if (event.target.id === "tracking-url") state.trackingUrl = event.target.value;
    if (event.target.id === "brand-pitch") state.pitch = event.target.value;
    if (event.target.id === "daily-cap") state.settings.dailyCapNT = Number(event.target.value) || MOCK.launchSettings.dailyCapNT;
    if (event.target.id === "pause-hours") state.settings.noConversionPauseHours = Number(event.target.value) || MOCK.launchSettings.noConversionPauseHours;
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    const state = getState();
    if (!button || button.disabled) {
      if (event.target.id === "modal-backdrop") {
        state.modal = null;
        renderModal();
      }
      return;
    }
    const action = button.dataset.action;
    if (action === "connect") {
      const platform = button.dataset.platform;
      state.busyAccounts[platform] = true;
      render();
      window.setTimeout(() => { state.busyAccounts[platform] = false; state.accounts[platform] = true; render(); }, 900);
    } else if (action === "detect-tracking") {
      state.trackingBusy = true;
      state.trackingDetected = false;
      render();
      window.setTimeout(() => { state.trackingBusy = false; state.trackingDetected = true; render(); }, 700);
    } else if (action === "next-step") {
      transition(() => { state.onboardingStep = Math.min(4, state.onboardingStep + 1); });
    } else if (action === "previous-step") {
      transition(() => { state.onboardingStep = Math.max(1, state.onboardingStep - 1); });
    } else if (action === "analyze") {
      state.analysisBusy = true;
      state.analyzed = false;
      render();
      window.setTimeout(() => { state.analysisBusy = false; state.analyzed = true; render(); }, 900);
    } else if (action === "swap-batch") {
      const platform = button.dataset.platform;
      app.querySelector(`[data-creative="${platform}"] .creative-content`)?.classList.add("is-swapping");
      window.setTimeout(() => { state.batchIndex[platform] ^= 1; render(); }, reducedMotion() ? 0 : 150);
    } else if (action === "launch") {
      state.launching = true;
      render();
      window.setTimeout(() => {
        state.stage = "live";
        state.launching = false;
        state.view = "cockpit";
        state.lastUpdated = new Date();
        render();
        showToast("系統已接管，開始自動投放");
      }, 1200);
    } else if (action === "open-inbox") {
      transition(() => { state.view = "inbox"; });
    } else if (action === "open-performance") {
      transition(() => { state.performanceMode = state.isOptimized ? "after" : "before"; state.view = "performance"; });
    } else if (action === "back-cockpit") {
      transition(() => { state.view = "cockpit"; });
    } else if (action === "approve-proposal") {
      removeProposal(button.dataset.id, true);
    } else if (action === "reject-proposal") {
      removeProposal(button.dataset.id, false);
    } else if (action === "approve-all") {
      approveAll();
    } else if (action === "performance-mode") {
      const content = app.querySelector(".performance-content");
      content?.classList.add("is-changing");
      window.setTimeout(() => { state.performanceMode = button.dataset.mode; render(); }, reducedMotion() ? 0 : 150);
    } else if (action === "open-cruise") {
      state.modal = "cruise";
      renderModal();
    } else if (action === "open-reset") {
      state.modal = "reset";
      renderModal();
    } else if (action === "close-modal") {
      state.modal = null;
      renderModal();
    } else if (action === "save-cruise") {
      state.settings.dailyCapNT = Number(document.getElementById("modal-daily-cap").value) || state.settings.dailyCapNT;
      state.settings.noConversionPauseHours = Number(document.getElementById("modal-pause-hours").value) || state.settings.noConversionPauseHours;
      state.autoPilot = document.getElementById("auto-pilot-toggle").checked;
      state.modal = null;
      state.lastUpdated = new Date();
      render();
      showToast("巡航設定已儲存");
    } else if (action === "confirm-reset") {
      state.modal = null;
      renderModal();
      transition(() => { window.state = createInitialState(); });
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && getState().modal) {
      getState().modal = null;
      renderModal();
    }
  });

  render();
}());
