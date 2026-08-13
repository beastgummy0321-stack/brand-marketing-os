const STAGES = ["連結帳號", "產品與策略", "素材產線", "核可上線", "成效儀表", "優化循環"];
const PLATFORM_IDS = ["meta", "google", "tiktok"];

let state = createInitialState();

function createInitialState() {
  return {
    runId: 0,
    messages: [{ id: "account-card", type: "account" }, { id: "tracking-card", type: "tracking" }],
    connections: { meta: "unconnected", google: "unconnected", tiktok: "unconnected" },
    trackingInput: "",
    trackingVerified: false,
    trackingVerifying: false,
    setupComplete: false,
    currentStage: 1,
    composerEnabled: false,
    composerValue: "",
    analysisRunning: false,
    strategyApproved: false,
    materialTab: "meta",
    materialBatches: { meta: 0, google: 0, tiktok: 0 },
    materialFlash: false,
    materialApproved: false,
    launching: false,
    launched: false,
    performanceTab: "overview",
    optimized: false,
    recommendationApproved: [false, false, false],
    applyingOptimization: false,
    sidebarOpen: false
  };
}

function formatMoney(value) {
  return `NT$${new Intl.NumberFormat("zh-TW").format(value)}`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

function icon(name) {
  const icons = {
    check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"></path></svg>',
    refresh: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14.8-4L4 9"></path><path d="M4 4v5h5"></path><path d="M4 13a8 8 0 0 0 14.8 4L20 15"></path><path d="M20 20v-5h-5"></path></svg>',
    cup: '<svg viewBox="0 0 48 48" aria-hidden="true"><path d="M12 17h20v10a9 9 0 0 1-9 9h-2a9 9 0 0 1-9-9V17Z"></path><path d="M32 20h3a5 5 0 0 1 0 10h-3"></path><path d="M17 12h10"></path><path d="M15 39h14"></path></svg>',
    play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z"></path></svg>'
  };
  return icons[name] || "";
}

function platformById(id) {
  return MOCK_DATA.platforms.find((platform) => platform.id === id);
}

function pushMessage(type, extra = {}) {
  state.messages.push({ id: `${type}-${Date.now()}-${Math.random().toString(16).slice(2)}`, type, ...extra });
}

function render(autoScroll = false) {
  const conversation = document.getElementById("conversation");
  conversation.innerHTML = state.messages.map(renderMessage).join("");
  renderSidebar();
  renderComposer();
  renderApprovalBar();
  if (autoScroll) requestAnimationFrame(() => { conversation.scrollTop = conversation.scrollHeight; });
}

function renderMessage(message) {
  if (message.type === "user") return `<div class="message user"><div class="bubble-wrap"><div class="bubble">${escapeHtml(message.text)}</div><div class="message-meta">你</div></div></div>`;
  if (message.type === "text") return `<div class="message"><div class="avatar" aria-hidden="true">L</div><div class="bubble-wrap"><div class="bubble">${escapeHtml(message.text)}</div></div></div>`;
  const body = {
    account: renderAccountCard(),
    tracking: renderTrackingCard(),
    skeleton: renderSkeletonCard(),
    analysis: renderAnalysisCard(),
    strategy: renderStrategyCard(),
    materials: renderMaterialsCard(),
    overview: renderOverviewCard(),
    performance: renderPerformanceCard(),
    recommendations: renderRecommendations()
  }[message.type];
  return `<div class="message"><div class="avatar" aria-hidden="true">L</div><div class="bubble-wrap">${body}</div></div>`;
}

function renderAccountCard() {
  const complete = state.setupComplete;
  const rows = MOCK_DATA.platforms.map((platform) => {
    const status = state.connections[platform.id];
    let control = `<button class="button" type="button" data-action="connect" data-platform="${platform.id}" ${status !== "unconnected" ? "disabled" : ""}>連結</button>`;
    if (status === "loading") control = `<span class="platform-status is-loading"><span class="spinner" aria-hidden="true"></span>連結中</span>`;
    if (status === "connected") control = `<span class="platform-status is-connected">${icon("check")}已連結</span>`;
    return `<div class="platform-row"><span class="platform-name"><span class="platform-mark ${platform.id}">${platform.glyph}</span>${platform.name}</span>${control}</div>`;
  }).join("");
  return `<article class="message-card ${complete ? "is-approved" : ""}">
    <div class="card-heading"><div><h2 class="card-title">先接上三個廣告帳號</h2><p class="card-subtitle">先把資料接好，我才能幫你看懂成效。</p></div>${complete ? '<span class="status-chip">已完成</span>' : ""}</div>
    <div class="platform-list">${rows}</div>
  </article>`;
}

function renderTrackingCard() {
  const verifyButton = state.trackingVerifying ? '<span class="platform-status is-loading"><span class="spinner" aria-hidden="true"></span>驗證中</span>' : `<button class="button" type="button" data-action="verify-tracking" ${state.trackingVerified || state.trackingInput.trim() === "" ? "disabled" : ""}>驗證追蹤碼</button>`;
  return `<article class="message-card ${state.trackingVerified ? "is-approved" : ""}">
    <div class="card-heading"><div><h2 class="card-title">埋碼精靈</h2><p class="card-subtitle">確認網站有追蹤碼，之後每筆訂單才找得到來源。</p></div>${state.trackingVerified ? '<span class="status-chip">已完成</span>' : ""}</div>
    <div class="tracking-form"><input class="input" id="tracking-input" value="${escapeHtml(state.trackingInput)}" placeholder="貼上 lumibrew.example.com" aria-label="網站網址" ${state.trackingVerified || state.trackingVerifying ? "disabled" : ""}>${verifyButton}</div>
    ${state.trackingVerified ? `<div class="tracking-result"><span class="check">${icon("check")}</span>${MOCK_DATA.tracking.successText}</div>` : ""}
  </article>`;
}

function renderSkeletonCard() {
  return `<article class="skeleton-card"><h2 class="card-title">分析中</h2><div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div></article>`;
}

function renderAnalysisCard() {
  const data = MOCK_DATA.analysis;
  return `<article class="message-card"><div class="card-heading"><div><h2 class="card-title">產品分析</h2><p class="card-subtitle">我先把這個品牌整理成可以投放的語言。</p></div></div><div class="analysis-grid">
    <div class="analysis-column"><p class="section-label">賣點</p><ul class="analysis-list">${data.sellingPoints.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>
    <div class="analysis-column"><p class="section-label">受眾</p><ul class="analysis-list">${data.audiences.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>
    <div class="analysis-column"><p class="section-label">競品</p><div class="competitor-list">${data.competitors.map((item) => `<div class="competitor-item"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.difference)}</span></div>`).join("")}</div></div>
  </div></article>`;
}

function renderStrategyCard() {
  const data = MOCK_DATA.strategy;
  const segments = data.budgets.map((budget) => `<div class="budget-segment ${budget.tone}" style="width:${budget.percent}%">${formatMoney(budget.amount)}<br>${budget.percent}%</div>`).join("");
  const legend = data.budgets.map((budget) => `<span class="legend-item"><i class="legend-dot ${budget.tone}"></i>${budget.name}</span>`).join("");
  return `<article class="message-card ${state.strategyApproved ? "is-approved" : ""}"><div class="card-heading"><div><h2 class="card-title">投放策略</h2><p class="card-subtitle">先用三個平台測出會成交的訊息。</p></div></div><div class="budget-bar">${segments}</div><div class="budget-legend">${legend}</div><div class="strategy-meta"><div><p class="section-label">投放目標</p><div class="meta-value">${escapeHtml(data.objective)}</div></div><div><p class="section-label">預估成果區間</p><div class="meta-value">${escapeHtml(data.forecast)}</div></div></div><div class="card-actions"><button class="button" type="button" data-action="reanalyse">重新分析</button><button class="button primary" type="button" data-action="approve-strategy" ${state.strategyApproved ? "disabled" : ""}>${state.strategyApproved ? `${icon("check")}已核准` : "核准策略"}</button></div></article>`;
}

function renderMaterialsCard() {
  const tab = state.materialTab;
  const batch = state.materialBatches[tab];
  const title = batch === 1 ? "廣告素材（第二批）" : "廣告素材（第一批）";
  const tabs = PLATFORM_IDS.map((id) => `<button class="tab-button ${id === tab ? "is-active" : ""}" type="button" data-action="material-tab" data-tab="${id}">${platformById(id).name}</button>`).join("");
  let panel = renderMetaMaterials(batch);
  if (tab === "google") panel = renderGoogleMaterials(batch);
  if (tab === "tiktok") panel = renderTikTokMaterials(batch);
  return `<article class="message-card ${state.materialApproved ? "is-approved" : ""}"><div class="card-heading"><div><h2 class="card-title">${title}</h2><p class="card-subtitle">每個平台各放兩個方向，先看哪個更像你的品牌。</p></div><button class="button refresh-button" type="button" data-action="swap-materials">${icon("refresh")}${state.materialFlash ? "已換一批" : "換一批"}</button></div><div class="tabs">${tabs}</div><div class="tab-panel" key="${tab}-${batch}">${panel}</div><p class="material-note">示意素材僅用來確認方向，正式素材會再依核准的策略製作。</p><div class="card-actions"><button class="button primary" type="button" data-action="approve-materials" ${state.materialApproved ? "disabled" : ""}>${state.materialApproved ? `${icon("check")}已核可` : "核可素材"}</button></div></article>`;
}

function renderMetaMaterials(batch) {
  return `<div class="material-grid">${MOCK_DATA.materials.meta[batch].map((item) => `<div class="material-item"><div class="material-visual" role="img" aria-label="${escapeHtml(item.visual)}">${icon("cup")}</div><div class="material-copy"><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.body)}</p></div></div>`).join("")}</div>`;
}

function renderGoogleMaterials(batch) {
  return `<div class="search-grid">${MOCK_DATA.materials.google[batch].map((item) => `<div class="search-ad"><div class="search-title">${escapeHtml(item.title)}</div><div class="search-url">${escapeHtml(item.url)}</div><div class="search-description">${escapeHtml(item.lines[0])}<br>${escapeHtml(item.lines[1])}</div></div>`).join("")}</div>`;
}

function renderTikTokMaterials(batch) {
  return `<div class="video-grid">${MOCK_DATA.materials.tiktok[batch].map((item) => `<div class="video-item"><div class="video-cover" role="img" aria-label="${escapeHtml(item.cover)}">${icon("play")}</div><div class="script-list"><div class="script-line"><strong>開場鉤子</strong> ${escapeHtml(item.hook.replace("開場鉤子：", ""))}</div><div class="script-line"><strong>賣點</strong> ${escapeHtml(item.point.replace("賣點：", ""))}</div><div class="script-line"><strong>CTA</strong> ${escapeHtml(item.cta.replace("CTA：", ""))}</div></div></div>`).join("")}</div>`;
}

function renderOverviewCard() {
  const launch = MOCK_DATA.launch;
  return `<article class="message-card"><div class="card-heading"><div><h2 class="card-title">上線前總覽</h2><p class="card-subtitle">最後確認一次，按下後就會開始累積成效。</p></div>${state.launched ? '<span class="live-badge"><i class="live-dot"></i>投放中</span>' : ""}</div><div class="overview-grid"><div class="overview-cell"><p class="section-label">月預算</p><div class="overview-value">${formatMoney(MOCK_DATA.brand.monthlyBudget)}</div></div><div class="overview-cell"><p class="section-label">排程</p><div class="overview-value">${escapeHtml(launch.schedule)}</div></div><div class="overview-cell"><p class="section-label">煞車</p><div class="overview-value">日上限 ${formatMoney(launch.dailyCap)}／無轉換 ${launch.defaultPauseHours} 小時自動暫停</div></div></div><div class="control-grid"><div class="control"><label for="daily-cap">日上限</label><div class="range-row"><input id="daily-cap" type="range" min="800" max="2500" step="100" value="${launch.dailyCap}" aria-label="日上限"><span class="range-value" id="daily-cap-value">${formatMoney(launch.dailyCap)}</span></div></div><div class="control"><label for="pause-hours">無轉換自動暫停</label><select class="select" id="pause-hours" aria-label="無轉換自動暫停門檻">${launch.pauseOptions.map((hours) => `<option value="${hours}" ${hours === launch.defaultPauseHours ? "selected" : ""}>${hours} 小時</option>`).join("")}</select></div></div>${state.launched ? "" : `<div class="card-actions overview-actions"><button class="button primary launch-button" type="button" data-action="launch" ${state.launching ? "disabled" : ""}>${state.launching ? '<span class="spinner"></span>投放中…' : "開始投放"}</button></div>`}</article>`;
}

function getPerformanceData() {
  const group = state.optimized ? MOCK_DATA.performance.after : MOCK_DATA.performance.before;
  return group[state.performanceTab];
}

function renderPerformanceCard() {
  const data = getPerformanceData();
  const tabs = ["overview", ...PLATFORM_IDS].map((id) => `<button class="tab-button ${id === state.performanceTab ? "is-active" : ""}" type="button" data-action="performance-tab" data-tab="${id}">${id === "overview" ? "總覽" : platformById(id).name}</button>`).join("");
  const changes = state.optimized ? data.changes : null;
  const spendBadge = changes ? renderChangeBadge("花費", changes.spend) : "";
  const conversionBadge = changes ? renderChangeBadge("成交數", changes.conversions) : "";
  const costBadge = changes ? renderChangeBadge("每筆成本", changes.cost) : "";
  return `<article class="message-card"><div class="card-heading"><div><h2 class="card-title">這幾天的成效</h2><p class="card-subtitle">把數字換成你真正會在意的答案。</p></div><div class="tabs performance-tabs">${tabs}</div></div><div class="stat-row"><div class="stat"><span class="stat-label">花費</span>${spendBadge}<div class="stat-value">${formatMoney(data.spend)}<span class="stat-unit">本期</span></div></div><div class="stat"><span class="stat-label">成交數</span>${conversionBadge}<div class="stat-value">${data.conversions}<span class="stat-unit">筆訂單</span></div></div><div class="stat"><span class="stat-label">每筆成本</span>${costBadge}<div class="stat-value">${formatMoney(data.cost)}<span class="stat-unit">平均</span></div></div></div><p class="plain-summary">${MOCK_DATA.copy.summary.replace("{spend}", formatMoney(data.spend)).replace("{conversions}", data.conversions)}</p><p class="trend-title">近 7 日趨勢</p>${renderTrend(data.trend)}<p class="roas-line">投資報酬率 ROAS <strong>${data.roas} 倍</strong></p></article>`;
}

function renderChangeBadge(label, change) {
  if (!change || change.percent === 0) return "";
  const arrow = change.direction === "down" ? "↓" : "↑";
  const isWorse = label === "花費" && change.direction === "up";
  return `<span class="change-badge is-visible ${isWorse ? "is-worse" : ""}">${escapeHtml(MOCK_DATA.copy.changeBadge.replace("{label}", label).replace("{arrow}", arrow).replace("{percent}", change.percent))}</span>`;
}

function renderTrend(values) {
  const width = 620;
  const height = 116;
  const padX = 8;
  const padY = 12;
  const max = Math.max(...values, 1);
  const min = Math.min(...values);
  const range = Math.max(max - min, 1);
  const points = values.map((value, index) => {
    const x = padX + ((width - padX * 2) * index / (values.length - 1));
    const y = height - padY - ((value - min) / range) * (height - padY * 2 - 18);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const circles = points.map((point) => { const [x, y] = point.split(","); return `<circle class="trend-point" cx="${x}" cy="${y}" r="3"></circle>`; }).join("");
  return `<svg class="trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="近七日趨勢折線圖"><polyline class="trend-line" points="${points.join(" ")}"></polyline>${circles}<text class="trend-label" x="8" y="111">7 日前</text><text class="trend-label" text-anchor="end" x="612" y="111">今天</text></svg>`;
}

function renderRecommendations() {
  const cards = MOCK_DATA.recommendations.map((item, index) => {
    const approved = state.recommendationApproved[index];
    return `<article class="recommendation-card ${approved ? "is-approved" : ""}"><span class="tag ${item.tone}">${escapeHtml(item.type)}</span><h3 class="recommendation-title">${escapeHtml(item.title)}</h3><span class="recommendation-label">理由</span><p class="recommendation-copy">${escapeHtml(item.reason)}</p><span class="recommendation-label">預期影響</span><p class="recommendation-copy">${escapeHtml(item.impact)}</p><button class="button" type="button" data-action="approve-recommendation" data-index="${index}" ${approved ? "disabled" : ""}>${approved ? `${icon("check")}已核准` : "核准"}</button></article>`;
  }).join("");
  return `<article class="message-card"><div class="card-heading"><div><h2 class="card-title">本週優化建議</h2><p class="card-subtitle">每張提案都先寫清楚原因，你只要決定要不要做。</p></div></div><div class="recommendation-grid">${cards}</div></article>`;
}

function renderSidebar() {
  const sidebar = document.getElementById("sidebar-content");
  const spent = state.optimized ? MOCK_DATA.performance.after.overview.spend : state.launched ? MOCK_DATA.performance.before.overview.spend : MOCK_DATA.sidebar.spent;
  const budgetPercent = Math.min(100, Math.round(spent / MOCK_DATA.brand.monthlyBudget * 100));
  const connectionRows = MOCK_DATA.platforms.map((platform) => `<div class="connection-item"><span class="connection-name"><i class="connection-dot ${state.connections[platform.id] === "connected" ? "connected" : ""}"></i>${platform.name}</span><span>${state.connections[platform.id] === "connected" ? "已連結" : "待連結"}</span></div>`).join("");
  const stages = STAGES.map((label, index) => { const stage = index + 1; const className = stage < state.currentStage ? "is-done" : stage === state.currentStage ? "is-current" : ""; return `<div class="stage-item ${className}"><span class="stage-dot">${stage < state.currentStage ? "✓" : stage}</span>${label}</div>`; }).join("");
  sidebar.innerHTML = `<div class="sidebar-block"><h2 class="sidebar-heading">帳號連線</h2><div class="connection-list">${connectionRows}</div></div><div class="sidebar-block"><h2 class="sidebar-heading">本月預算</h2><div class="budget-copy"><span class="budget-amount">${formatMoney(spent)}</span><span class="budget-percent">${budgetPercent}%</span></div><div class="progress-track"><div class="progress-value" style="width:${budgetPercent}%"></div></div></div><div class="sidebar-block"><h2 class="sidebar-heading">六站進度</h2><div class="stage-list">${stages}</div></div><div class="sidebar-block"><h2 class="sidebar-heading">最後更新</h2><div class="updated-at">今天 ${MOCK_DATA.sidebar.updatedAt}</div></div>`;
  document.getElementById("status-sidebar").classList.toggle("is-open", state.sidebarOpen);
  document.getElementById("sidebar-toggle").setAttribute("aria-expanded", String(state.sidebarOpen));
}

function renderComposer() {
  const input = document.getElementById("composer-input");
  const send = document.getElementById("send-button");
  input.disabled = !state.composerEnabled;
  input.placeholder = state.composerEnabled ? "例：lumibrew.example.com" : "完成前面的步驟後，這裡會告訴你下一步";
  if (document.activeElement !== input) input.value = state.composerValue;
  send.disabled = !state.composerEnabled || state.composerValue.trim() === "";
}

function renderApprovalBar() {
  const bar = document.getElementById("approval-bar");
  const count = state.recommendationApproved.filter(Boolean).length;
  if (!state.launched || count === 0 || state.optimized) { bar.hidden = true; bar.classList.remove("is-closing"); return; }
  bar.hidden = false;
  bar.classList.toggle("is-closing", state.applyingOptimization);
  bar.innerHTML = `<span class="approval-count">${MOCK_DATA.copy.approved.replace("{count}", count)}</span><button class="button primary" type="button" data-action="apply-optimization">套用優化</button>`;
}

function setupCompleteIfReady(runId) {
  if (runId !== state.runId || state.setupComplete) return;
  if (!PLATFORM_IDS.every((id) => state.connections[id] === "connected") || !state.trackingVerified) return;
  state.setupComplete = true;
  state.currentStage = 2;
  state.composerEnabled = true;
  pushMessage("text", { text: "都接好了，接下來看看你的產品" });
  pushMessage("text", { text: "貼你的網址，或一句話說說你在賣什麼" });
}

function handleConnect(id) {
  if (state.connections[id] !== "unconnected") return;
  const runId = state.runId;
  state.connections[id] = "loading";
  render();
  setTimeout(() => {
    if (runId !== state.runId) return;
    state.connections[id] = "connected";
    setupCompleteIfReady(runId);
    render(true);
  }, platformById(id).connectMs);
}

function handleTrackingVerify() {
  if (state.trackingVerified || state.trackingInput.trim() === "") return;
  const runId = state.runId;
  state.trackingInput = state.trackingInput.trim();
  state.trackingVerifying = true;
  render();
  setTimeout(() => {
    if (runId !== state.runId) return;
    state.trackingVerifying = false;
    state.trackingVerified = true;
    setupCompleteIfReady(runId);
    render(true);
  }, MOCK_DATA.tracking.verifyMs);
}

function handleSubmit() {
  const text = state.composerValue.trim();
  if (!state.composerEnabled || state.analysisRunning || !text) return;
  const runId = state.runId;
  state.composerEnabled = false;
  state.analysisRunning = true;
  state.messages = state.messages.filter((message) => !["analysis", "strategy", "skeleton"].includes(message.type));
  pushMessage("user", { text });
  pushMessage("skeleton");
  render(true);
  setTimeout(() => {
    if (runId !== state.runId) return;
    state.analysisRunning = false;
    state.composerValue = "";
    state.currentStage = 2;
    state.messages = state.messages.filter((message) => message.type !== "skeleton");
    pushMessage("analysis");
    pushMessage("strategy");
    render(true);
  }, 800);
}

function approveStrategy() {
  if (state.strategyApproved) return;
  state.strategyApproved = true;
  state.currentStage = 3;
  pushMessage("text", { text: "策略定了，我來做素材" });
  pushMessage("materials");
  render(true);
}

function approveMaterials() {
  if (state.materialApproved) return;
  state.materialApproved = true;
  state.currentStage = 4;
  pushMessage("overview");
  render(true);
}

function launchCampaign() {
  if (state.launching || state.launched) return;
  const runId = state.runId;
  state.launching = true;
  render();
  setTimeout(() => {
    if (runId !== state.runId) return;
    state.launching = false;
    state.launched = true;
    state.currentStage = 5;
    pushMessage("performance");
    pushMessage("text", { text: "數字先跑起來，這是我這週想做的調整" });
    pushMessage("recommendations");
    state.currentStage = 6;
    render(true);
  }, 1000);
}

function approveRecommendation(index) {
  if (state.recommendationApproved[index]) return;
  state.recommendationApproved[index] = true;
  render();
}

function applyOptimization() {
  if (state.optimized || state.applyingOptimization) return;
  state.applyingOptimization = true;
  render();
  const runId = state.runId;
  setTimeout(() => {
    if (runId !== state.runId) return;
    state.applyingOptimization = false;
    state.optimized = true;
    pushMessage("text", { text: "優化上線了，數字馬上更新給你看" });
    render(true);
    document.querySelectorAll(".stat-value").forEach((element) => {
      element.classList.add("is-changing");
      setTimeout(() => element.classList.remove("is-changing"), 220);
    });
  }, 160);
}

function resetDemo() {
  if (!window.confirm("要重新走一次示範嗎？目前的對話會清空")) return;
  const nextRunId = state.runId + 1;
  state = createInitialState();
  state.runId = nextRunId;
  render();
}

document.addEventListener("click", (event) => {
  const actionTarget = event.target.closest("[data-action]");
  if (actionTarget) {
    const action = actionTarget.dataset.action;
    if (action === "connect") handleConnect(actionTarget.dataset.platform);
    if (action === "verify-tracking") handleTrackingVerify();
    if (action === "approve-strategy") approveStrategy();
    if (action === "reanalyse") { state.composerEnabled = true; state.composerValue = ""; render(); document.getElementById("composer-input").focus(); }
    if (action === "material-tab") { state.materialTab = actionTarget.dataset.tab; render(); }
    if (action === "swap-materials") { state.materialBatches[state.materialTab] = state.materialBatches[state.materialTab] === 0 ? 1 : 0; state.materialFlash = true; render(); setTimeout(() => { state.materialFlash = false; render(); }, 700); }
    if (action === "approve-materials") approveMaterials();
    if (action === "launch") launchCampaign();
    if (action === "performance-tab") { state.performanceTab = actionTarget.dataset.tab; render(); }
    if (action === "approve-recommendation") approveRecommendation(Number(actionTarget.dataset.index));
    if (action === "apply-optimization") applyOptimization();
  }
  if (event.target.closest("#sidebar-toggle")) { state.sidebarOpen = !state.sidebarOpen; renderSidebar(); }
  if (state.sidebarOpen && !event.target.closest("#status-sidebar") && !event.target.closest("#sidebar-toggle")) { state.sidebarOpen = false; renderSidebar(); }
});

document.getElementById("composer-form").addEventListener("submit", (event) => {
  event.preventDefault();
  handleSubmit();
});

document.addEventListener("input", (event) => {
  if (event.target.id === "tracking-input") {
    state.trackingInput = event.target.value;
    const verifyButton = event.target.closest(".tracking-form")?.querySelector('[data-action="verify-tracking"]');
    if (verifyButton) verifyButton.disabled = state.trackingInput.trim() === "" || state.trackingVerified || state.trackingVerifying;
  }
  if (event.target.id === "composer-input") {
    state.composerValue = event.target.value;
    document.getElementById("send-button").disabled = !state.composerEnabled || state.composerValue.trim() === "";
  }
  if (event.target.id === "daily-cap") document.getElementById("daily-cap-value").textContent = formatMoney(Number(event.target.value));
});

document.getElementById("reset-demo").addEventListener("click", resetDemo);

render();
