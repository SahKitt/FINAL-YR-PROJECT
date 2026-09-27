(function() {
  'use strict';

  // ---------- STATE ----------
  const state = {
    currentPage: 'overview',
    user: null,
    stats: { totalRaw: 0, totalRuled: 0, totalBad: 0, totalProcessed: 0, highRisk: 0, flagged: 0, fraud: 0, normal: 0, falsePositive: 0 },
    dataTabs: ['raw', 'ruled', 'bad', 'processed'],
    activeDataTab: 'raw',
    rawData: [],
    ruledData: [],
    badData: [],
    processedData: [],
    mergedData: [],
    suspicious: [],
    filterType: 'all',
    reportSourceFilter: 'all',
    reportDateWindow: 'monthly',
    trendPeriod: 'weekly',
    charts: {},

    summaryCards: { totalProcessed: 0, suspicious: 0, falsePositives: 0, fraudRatio: 0 },
    fraudTrendData: [],
    recentSuspicious: [],
    allSuspicious: [],
    rulesTriggered: {},
    processedBarData: [],
    bubbleData: [],
    topMerchants: [],
    peakHours: [],

    allUsers: [],
    users: [],
    expanded: {},
    containers: [],
    lastUpdated: null,
    loading: true,
    error: '',
    intervals: [],
    _adminReportsEventsBound: false,

    // audit logs
    auditLogs: []
  };

  // ---------- DOM REFS ----------
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);

  const adminWelcome = $('#adminWelcome');
  const adminSidebar = $('#adminSidebar');
  const mobileMenuBtn = $('#adminMobileMenuBtn');
  const logoutBtn = $('#adminLogoutBtn');

  // ---------- UTILITY ----------
  function getToken() { return localStorage.getItem('token'); }
  function getUser() {
    try { return JSON.parse(localStorage.getItem('user') || 'null'); } catch { return null; }
  }
  function formatDateShort(iso) {
    if (!iso) return 'N/A';
    try { return new Date(iso).toLocaleDateString(); } catch { return 'N/A'; }
  }
  function formatCurrency(n) { return (n || 0).toLocaleString(); }
  function getWeekNumber(d) {
    d = new Date(d);
    d.setHours(0,0,0,0);
    d.setDate(d.getDate() + 3 - (d.getDay() + 6) % 7);
    var week1 = new Date(d.getFullYear(), 0, 4);
    return 1 + Math.round(((d - week1) / 86400000 - 3 + (week1.getDay() + 6) % 7) / 7);
  }

  function getWindowRange(period) {
    const end = new Date();
    const start = new Date(end);
    if (period === 'weekly') start.setDate(end.getDate() - 7);
    else if (period === 'monthly') start.setMonth(end.getMonth() - 1);
    else if (period === 'yearly') start.setFullYear(end.getFullYear() - 1);
    else start.setDate(end.getDate() - 30);
    return { start, end };
  }

  function getTrendRange(period) {
    const end = new Date();
    const start = new Date(end);
    if (period === 'weekly') start.setDate(end.getDate() - 7 * 12);
    else if (period === 'monthly') start.setMonth(end.getMonth() - 12);
    else start.setFullYear(end.getFullYear() - 5);
    return { start, end };
  }

  function generatePeriodKeys(start, end, period) {
    const keys = [];
    const cur = new Date(start);
    if (period === 'weekly') {
      while (cur <= end) { keys.push(cur.getFullYear() + '-W' + String(getWeekNumber(cur)).padStart(2,'0')); cur.setDate(cur.getDate() + 7); }
    } else if (period === 'monthly') {
      while (cur <= end) { keys.push(cur.getFullYear() + '-' + String(cur.getMonth() + 1).padStart(2,'0')); cur.setMonth(cur.getMonth() + 1); }
    } else {
      while (cur <= end) { keys.push(String(cur.getFullYear())); cur.setFullYear(cur.getFullYear() + 1); }
    }
    return keys;
  }

  // ---------- AUTH ----------
  function loadUser() {
    const u = getUser();
    state.user = u;
    adminWelcome.textContent = 'Welcome: ' + (u?.organization_name || u?.email || 'Admin');
  }

  function handleLogout() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.href = '/login';
  }

  // ---------- NAVIGATION ----------
  function navigateTo(page) {
    state.currentPage = page;
    $$('.page-section').forEach(el => el.classList.remove('active-page'));
    const target = document.getElementById('page-' + page);
    if (target) target.classList.add('active-page');

    $$('.admin-sidebar li a').forEach(el => el.classList.remove('active-link'));
    const link = document.querySelector('.admin-sidebar li a[data-page="' + page + '"]');
    if (link) link.classList.add('active-link');

    state.mobileMenuOpen = false;
    adminSidebar.classList.remove('mobile-open');

    if (page === 'overview') fetchOverview();
    else if (page === 'data') fetchDataTab(state.activeDataTab);
    else if (page === 'reports') initAdminReports();
    else if (page === 'user-management') fetchUsers();
    else if (page === 'sys-health') fetchHealth();
    else if (page === 'audit-trail') fetchAuditLogs();
  }

  // ---------- OVERVIEW ----------
  async function fetchOverview() {
    try {
      const token = getToken();
      if (!token) throw new Error('No token');
      const res = await fetch('/admin/stats/overview', {
        headers: { Authorization: 'Bearer ' + token }
      });
      if (!res.ok) throw new Error('Failed to fetch stats');
      const data = await res.json();
      state.stats = data;
      renderOverview();
    } catch (err) {
      console.error(err);
      const header = document.querySelector('#page-overview .overview-header');
      if (header) {
        header.insertAdjacentHTML('afterend', '<div class="error-msg">' + err.message + '</div>');
      }
    }
  }

 
  function animateCount(el, target, duration = 800) {
    if (!el) return;
    target = target || 0;
    const startTime = performance.now();
    function tick(now) {
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(target * eased).toLocaleString();
      if (progress < 1) requestAnimationFrame(tick);
      else el.textContent = target.toLocaleString();
    }
    requestAnimationFrame(tick);
  }

  function renderOverview() {
    const s = state.stats;

    animateCount(document.getElementById('statRaw'), s.totalRaw);
    animateCount(document.getElementById('statRuled'), s.totalRuled);
    animateCount(document.getElementById('statBad'), s.totalBad);
    animateCount(document.getElementById('statProcessed'), s.totalProcessed);
    animateCount(document.getElementById('statFlagged'), s.flagged);
    animateCount(document.getElementById('statHighRisk'), s.highRisk);
    animateCount(document.getElementById('statFraud'), s.fraud);
    animateCount(document.getElementById('statFalsePositive'), s.falsePositive);
    animateCount(document.getElementById('statNormal'), s.normal);

    // Quick insight rates
    const fraudRate = s.totalProcessed > 0 ? (s.fraud / s.totalProcessed) * 100 : 0;
    const flagRate = s.totalRuled > 0 ? (s.flagged / s.totalRuled) * 100 : 0;
    const coverage = s.totalRaw > 0 ? (s.totalProcessed / s.totalRaw) * 100 : 0;

    const fraudBar = document.getElementById('ovFraudRateBar');
    const flagBar = document.getElementById('ovFlagRateBar');
    const covBar = document.getElementById('ovCoverageBar');
    // slight delay so the width transition animates from 0
    setTimeout(() => {
      if (fraudBar) fraudBar.style.width = Math.min(fraudRate, 100) + '%';
      if (flagBar) flagBar.style.width = Math.min(flagRate, 100) + '%';
      if (covBar) covBar.style.width = Math.min(coverage, 100) + '%';
    }, 100);

    const fraudVal = document.getElementById('ovFraudRateValue');
    const flagVal = document.getElementById('ovFlagRateValue');
    const covVal = document.getElementById('ovCoverageValue');
    if (fraudVal) fraudVal.textContent = fraudRate.toFixed(1) + '%';
    if (flagVal) flagVal.textContent = flagRate.toFixed(1) + '%';
    if (covVal) covVal.textContent = coverage.toFixed(1) + '%';

    state.lastUpdated = new Date();
    const updatedEl = document.getElementById('overviewLastUpdated');
    if (updatedEl) updatedEl.textContent = 'Last updated: ' + state.lastUpdated.toLocaleTimeString();
  }

  // ---------- DATA CENTER ----------
  async function fetchDataTab(tab) {
    state.activeDataTab = tab;
    const container = document.getElementById('dataContent');
    if (!container) return;
    container.innerHTML = '<div class="loading">Loading...</div>';
    try {
      const token = getToken();
      const res = await fetch('/admin/data/' + tab, {
        headers: { Authorization: 'Bearer ' + token }
      });
      if (!res.ok) throw new Error('Failed to load ' + tab + ' data');
      const data = await res.json();
      if (tab === 'raw') state.rawData = data;
      else if (tab === 'ruled') state.ruledData = data;
      else if (tab === 'bad') state.badData = data;
      else if (tab === 'processed') state.processedData = data;
      state.lastUpdated = new Date();
      const updatedEl = document.getElementById('dataLastUpdated');
      if (updatedEl) updatedEl.textContent = 'Last updated: ' + state.lastUpdated.toLocaleTimeString();
      renderDataTab(tab);
    } catch (err) {
      container.innerHTML = '<div class="error-msg">' + err.message + '</div>';
    }
  }

  function renderDataTab(tab) {
    const container = document.getElementById('dataContent');
    if (!container) return;
    let data = [];
    let columns = [];
    let headerMap = {};

    if (tab === 'raw') {
      data = state.rawData;
      columns = ['transaction_id', 'source_system', 'actor.name', 'counterparty.name', 'transaction_amount', 'status', 'normalized_timestamp'];
      headerMap = {
        'transaction_id': 'Transaction ID',
        'source_system': 'Source',
        'actor.name': 'Actor Name',
        'counterparty.name': 'Counterparty Name',
        'transaction_amount': 'Amount',
        'status': 'Status',
        'normalized_timestamp': 'Timestamp'
      };
    } else if (tab === 'ruled') {
      data = state.ruledData;
      columns = ['transaction_id', 'amount', 'timestamp', 'risk_level', 'total_risk_score', 'is_flagged'];
      headerMap = {
        'transaction_id': 'Transaction ID',
        'amount': 'Amount',
        'timestamp': 'Timestamp',
        'risk_level': 'Risk Level',
        'total_risk_score': 'Risk Score',
        'is_flagged': 'Flagged'
      };
    } else if (tab === 'bad') {
      data = state.badData;
      columns = ['transaction_id', 'error_message', 'error_timestamp', 'source'];
      headerMap = {
        'transaction_id': 'Transaction ID',
        'error_message': 'Error Message',
        'error_timestamp': 'Error Timestamp',
        'source': 'Source'
      };
    } else if (tab === 'processed') {
      data = state.processedData;
      columns = ['transaction_id', 'amount', 'timestamp', 'verdict', 'final_score', 'ml_score', 'correlation_score'];
      headerMap = {
        'transaction_id': 'Transaction ID',
        'amount': 'Amount',
        'timestamp': 'Timestamp',
        'verdict': 'Verdict',
        'final_score': 'Final Score',
        'ml_score': 'ML Score',
        'correlation_score': 'Correlation Score'
      };
    }

    if (!data || data.length === 0) {
      container.innerHTML = '<p class="empty-message">No data found.</p>';
      return;
    }

    let html = '<table class="admin-data-table"><thead><tr>';
    columns.forEach(col => { html += '<th>' + (headerMap[col] || col) + '</th>'; });
    html += '</tr></thead><tbody>';
    data.forEach(row => {
      html += '<tr>';
      columns.forEach(col => {
        let val = getNestedValue(row, col);
        if (col === 'transaction_amount' || col === 'amount') val = '$' + formatCurrency(val);
        else if (col === 'normalized_timestamp' || col === 'timestamp') val = formatDateShort(val);
        else if (col === 'is_flagged') val = val ? 'Yes' : 'No';
        else if (val === undefined || val === null) val = '';
        html += '<td>' + val + '</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
  }

  function getNestedValue(obj, path) {
    if (!obj) return '';
    const parts = path.split('.');
    let current = obj;
    for (let p of parts) {
      if (current === undefined || current === null) return '';
      current = current[p];
    }
    return current;
  }

  // ===================== ADMIN REPORTS + CHARTS =====================
  async function initAdminReports() {
    await loadAdminReportData();
    populateSourceDropdown();
    applySourceFilterAndRenderAll();

    if (!state._adminReportsEventsBound) {
      bindAdminReportEvents();
      state._adminReportsEventsBound = true;
    }
  }

  async function loadAdminReportData() {
    const token = getToken();
    if (!token) return;
    try {
      const [ruledRes, processedRes] = await Promise.all([
        fetch('/admin/data/ruled?limit=10000', { headers: { Authorization: 'Bearer ' + token } }),
        fetch('/admin/data/processed?limit=10000', { headers: { Authorization: 'Bearer ' + token } })
      ]);
      if (!ruledRes.ok || !processedRes.ok) throw new Error('Failed to fetch data');

      const ruled = await ruledRes.json();
      const processed = await processedRes.json();

      const ruledMap = {};
      ruled.forEach(tx => { ruledMap[tx.transaction_id] = tx; });

      state.mergedData = processed.map(pTx => {
        const rTx = ruledMap[pTx.transaction_id] || {};
        return {
          ...pTx,
          risk_level: rTx.risk_level || 'unknown',
          risk_score: rTx.total_risk_score || 0,
          is_flagged: rTx.is_flagged || false,
          triggered_rules: rTx.triggered_rules || [],
          description: rTx.description || '',
          merchant_name: rTx.merchant_name || '',
          source_system: rTx.source_system || pTx.source_system || '',
          receiver_id: rTx.receiver_id || '',
          transaction_type: rTx.transaction_type || pTx.transaction_type || ''
        };
      });
    } catch (err) {
      console.error(err);
    }
  }

  function populateSourceDropdown() {
    const dropdown = document.getElementById('adminReportSource');
    if (!dropdown) return;
    const sources = [...new Set(state.mergedData.map(tx => tx.source_system).filter(Boolean))].sort();
    let html = '<option value="all">All Sources</option>';
    sources.forEach(src => {
      const selected = state.reportSourceFilter === src ? ' selected' : '';
      html += `<option value="${src}"${selected}>${src}</option>`;
    });
    dropdown.innerHTML = html;
    dropdown.value = state.reportSourceFilter;
  }

  function getFilteredData() {
    let data = state.mergedData;
    if (state.reportSourceFilter !== 'all') {
      data = data.filter(tx => tx.source_system === state.reportSourceFilter);
    }
    return data;
  }

  function applySourceFilterAndRenderAll() {
    const data = getFilteredData();

    const seen = new Set();
    const suspicious = data.filter(tx => {
      if (!tx.transaction_id || seen.has(tx.transaction_id)) return false;
      const keep =
        tx.verdict === 'fraud' ||
        tx.verdict === 'false_positive' ||
        tx.risk_level === 'high' ||
        tx.risk_level === 'critical' ||
        tx.risk_level === 'medium' ||
        tx.is_flagged === true;
      if (keep) seen.add(tx.transaction_id);
      return keep;
    });
    state.suspicious = suspicious;

    const total = data.length;
    const fraud = suspicious.filter(t => t.verdict === 'fraud').length;
    const falsePos = suspicious.filter(t => t.verdict === 'false_positive').length;
    const suspiciousCount = suspicious.filter(t =>
      t.flagged || t.verdict === 'fraud' || t.verdict === 'suspicious' ||
      t.risk === 'high' || t.risk === 'critical'
    ).length;

    state.summaryCards = {
      totalProcessed: total,
      suspicious: suspiciousCount,
      falsePositives: falsePos,
      fraudRatio: total > 0 ? ((fraud / total) * 100).toFixed(1) : 0
    };

    const recent = [...suspicious].sort((a,b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0,10);
    state.recentSuspicious = recent;

    const procMap = {};
    data.forEach(t => {
      if (!t.timestamp) return;
      const key = new Date(t.timestamp).toISOString().split('T')[0];
      procMap[key] = (procMap[key] || 0) + 1;
    });
    state.processedBarData = Object.keys(procMap).sort().map(k => ({ date: k, count: procMap[k] }));

    const methodMap = {};
    data.forEach(t => {
      const method = t.transaction_type || t.payment_method || t.type || 'Other';
      if (!methodMap[method]) methodMap[method] = { count: 0, amount: 0 };
      methodMap[method].count += 1;
      methodMap[method].amount += t.amount || 0;
    });
    state.bubbleData = Object.entries(methodMap).map(([type, d]) => ({ type, count: d.count, amount: d.amount }));

    const merchantMap = {};
    suspicious.filter(t => t.merchant_name).forEach(t => {
      merchantMap[t.merchant_name] = (merchantMap[t.merchant_name] || 0) + 1;
    });
    state.topMerchants = Object.entries(merchantMap).sort((a,b) => b[1]-a[1]).slice(0,5).map(([name,count]) => ({name,count}));

    const hourMap = {};
    suspicious.filter(t => t.timestamp).forEach(t => {
      const h = new Date(t.timestamp).getHours();
      hourMap[h] = (hourMap[h] || 0) + 1;
    });
    state.peakHours = Object.entries(hourMap).sort((a,b) => b[1]-a[1]).slice(0,3).map(([hour,count]) => ({hour:parseInt(hour),count}));

    const rulesMap = {};
    suspicious.forEach(t => {
      (t.triggered_rules || []).forEach(r => {
        const name = typeof r === 'string' ? r : (r.rule_name || r.rule_id || 'Unknown');
        rulesMap[name] = (rulesMap[name] || 0) + 1;
      });
    });
    state.rulesTriggered = rulesMap;

    loadTrend(state.trendPeriod);

    renderAllAdminReports();
  }

  async function loadTrend(period) {
    state.trendPeriod = period;
    const { start, end } = getTrendRange(period);
    const data = getFilteredData().filter(tx => {
      if (!tx.timestamp) return false;
      const d = new Date(tx.timestamp);
      return d >= start && d <= end;
    });

    const trendMap = {};
    data.forEach(t => {
      const isFraudOrSuspicious = (t.verdict === 'fraud' || t.verdict === 'suspicious' ||
        t.risk_level === 'high' || t.risk_level === 'critical' || t.is_flagged === true);
      if (!isFraudOrSuspicious || !t.timestamp) return;
      const d = new Date(t.timestamp);
      let key;
      if (period === 'weekly') key = d.getFullYear() + '-W' + String(getWeekNumber(d)).padStart(2,'0');
      else if (period === 'monthly') key = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2,'0');
      else key = String(d.getFullYear());
      if (!trendMap[key]) trendMap[key] = { fraud: 0, suspicious: 0 };
      if (t.verdict === 'fraud') trendMap[key].fraud += 1; else trendMap[key].suspicious += 1;
    });

    const allKeys = generatePeriodKeys(start, end, period);
    allKeys.forEach(k => { if (!trendMap[k]) trendMap[k] = { fraud: 0, suspicious: 0 }; });
    state.fraudTrendData = allKeys.map(k => ({ date: k, fraud: trendMap[k].fraud, suspicious: trendMap[k].suspicious }));
    renderFraudTrendChart();
  }

  // ---- RENDER ALL ----
  function renderAllAdminReports() {
    renderSummaryCards();
    renderFraudAlert();
    renderRecentSuspicious();
    renderRulesBarChart();
    renderProcessedBarChart();
    renderBubbleChart();
    renderAllSuspiciousTable();
    renderTopMerchants();
    renderPeakHours();

    const badge = document.getElementById('adminReportSourceBadge');
    if (badge) badge.textContent = 'Data source: ' + (state.reportSourceFilter === 'all' ? 'All Sources' : state.reportSourceFilter);
    const updated = document.getElementById('adminReportLastUpdated');
    if (updated) updated.textContent = 'Last updated: ' + new Date().toLocaleTimeString();
  }

  function renderSummaryCards() {
    const container = document.getElementById('adminSummaryCards');
    if (!container) return;
    const c = state.summaryCards;
    container.innerHTML = `
      <div class="summary-card"><div class="icon"><i class="fas fa-credit-card"></i></div><div class="info"><div class="label">Total Processed</div><div class="value">${c.totalProcessed}</div></div></div>
      <div class="summary-card"><div class="icon red"><i class="fas fa-exclamation-triangle"></i></div><div class="info"><div class="label">Suspicious</div><div class="value">${c.suspicious}</div></div></div>
      <div class="summary-card"><div class="icon orange"><i class="fas fa-times-circle"></i></div><div class="info"><div class="label">False Positives</div><div class="value">${c.falsePositives}</div></div></div>
      <div class="summary-card"><div class="icon gold"><i class="fas fa-chart-line"></i></div><div class="info"><div class="label">Fraud Ratio</div><div class="value">${c.fraudRatio}%</div></div></div>`;
  }

  function renderFraudAlert() {
    const totalSuspicious = state.summaryCards.suspicious || 0;
    const totalEl = document.getElementById('adminTotalSuspicious');
    if (totalEl) totalEl.textContent = `Total Suspicious: ${totalSuspicious}`;
    let level = 'Low', angle = -45, color = 'var(--success)';
    if (totalSuspicious > 20) { level = 'High'; angle = 45; color = 'var(--danger)'; }
    else if (totalSuspicious > 10) { level = 'Medium'; angle = 0; color = 'var(--warning)'; }
    const gauge = document.getElementById('adminFraudGauge');
    if (gauge) { const needle = gauge.querySelector('.gauge-needle'); if (needle) needle.style.transform = `rotate(${angle}deg)`; }
    const label = document.getElementById('adminGaugeLabel');
    if (label) { label.textContent = level; label.style.color = color; }
  }

  function renderRecentSuspicious() {
    const container = document.getElementById('adminRecentSuspiciousList');
    if (!container) return;
    const list = state.recentSuspicious;
    if (!list.length) { container.innerHTML = '<p class="empty-message">No recent suspicious activity.</p>'; return; }
    let html = '<div class="recent-list">';
    list.forEach(tx => {
      const isFraud = (tx.verdict === 'fraud' || tx.risk_level === 'high' || tx.risk_level === 'critical');
      const riskClass = isFraud ? 'fraud' : 'suspicious';
      const riskLabel = isFraud ? 'Fraud' : 'Suspicious';
      const rules = (tx.triggered_rules || []).length;
      const score = tx.final_score || tx.risk_score || '—';
      html += `<div class="recent-item">
        <span class="tx-id">${tx.transaction_id || 'N/A'}</span>
        <span class="tx-risk ${riskClass}">${riskLabel}</span>
        <span class="tx-score">${score}</span>
        <span class="tx-rules">${rules} rules</span>
      </div>`;
    });
    html += '</div>';
    container.innerHTML = html;
  }

  function renderFraudTrendChart() {
    const canvas = document.getElementById('adminFraudTrendChart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (state.charts.fraudTrend) state.charts.fraudTrend.destroy();
    const data = state.fraudTrendData || [];
    const ctx = canvas.getContext('2d');
    state.charts.fraudTrend = new Chart(ctx, {
      type: 'line',
      data: {
        labels: data.map(d => d.date),
        datasets: [
          { label: 'Fraud', data: data.map(d => d.fraud), borderColor: '#e74c3c', backgroundColor: 'rgba(231,76,60,0.1)', fill: true, tension: 0.3, pointRadius: 2, borderWidth: 2 },
          { label: 'Suspicious', data: data.map(d => d.suspicious), borderColor: '#f39c12', backgroundColor: 'rgba(243,156,18,0.1)', fill: true, tension: 0.3, pointRadius: 2, borderWidth: 2 }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { boxWidth: 10, font: { size: 9 }, usePointStyle: true } }, tooltip: { mode: 'index', intersect: false } },
        scales: { y: { beginAtZero: true, ticks: { stepSize: 1, font: { size: 8 } }, grid: { color: 'rgba(0,0,0,0.06)' } }, x: { grid: { display: false }, ticks: { font: { size: 7 }, maxRotation: 45 } } }
      }
    });
  }

  function renderRulesBarChart() {
    const canvas = document.getElementById('adminRulesBarChart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (state.charts.rules) state.charts.rules.destroy();
    const rules = state.rulesTriggered || {};
    const sorted = Object.entries(rules).sort((a,b) => b[1]-a[1]);
    const labels = sorted.map(([name]) => name.length > 18 ? name.substring(0,16)+'…' : name);
    const counts = sorted.map(([,c]) => c);
    const fullLabels = sorted.map(([name]) => name);
    const palette = ['#116466','#3498db','#e67e22','#9b59b6','#1abc9c','#e74c3c','#2ecc71','#f39c12','#34495e','#16a085'];
    const barColors = counts.map((_, i) => palette[i % palette.length]);

    const ctx = canvas.getContext('2d');
    state.charts.rules = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels.length ? labels : ['No rules'],
        datasets: [{
          label: 'Transactions Triggered',
          data: labels.length ? counts : [0],
          backgroundColor: labels.length ? barColors : ['#ccc'],
          borderRadius: 4,
          barPercentage: 0.55,
          categoryPercentage: 0.65
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ctx.parsed.x + ' transactions', afterBody: items => 'Rule: ' + fullLabels[items[0].dataIndex] } } },
        scales: { x: { beginAtZero: true, ticks: { maxTicksLimit: 6, font: { size: 8 } }, grid: { color: 'rgba(0,0,0,0.04)' } }, y: { grid: { display: false }, ticks: { font: { size: 8 } } } }
      }
    });
  }

  function renderProcessedBarChart() {
    const canvas = document.getElementById('adminProcessedBarChart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (state.charts.processed) state.charts.processed.destroy();
    const data = state.processedBarData || [];
    const ctx = canvas.getContext('2d');
    state.charts.processed = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.length ? data.map(d => d.date) : ['No data'],
        datasets: [{ label: 'Processed', data: data.length ? data.map(d => d.count) : [0], backgroundColor: 'rgba(17,100,102,0.7)', borderColor: '#116466', borderWidth: 1, barPercentage: 0.35, categoryPercentage: 0.6, borderRadius: 2 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ctx.parsed.y + ' transactions' } } },
        scales: { y: { beginAtZero: true, ticks: { stepSize: 1, font: { size: 6 } }, grid: { color: 'rgba(0,0,0,0.05)' } }, x: { grid: { display: false }, ticks: { font: { size: 5 }, maxRotation: 45 } } }
      }
    });
  }

  function renderBubbleChart() {
    const canvas = document.getElementById('adminBubbleChart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (state.charts.bubble) state.charts.bubble.destroy();
    const data = state.bubbleData || [];
    const colors = ['#e74c3c','#3498db','#2ecc71','#f39c12','#9b59b6','#1abc9c','#e67e22','#1dd1a1'];
    const maxAmount = Math.max(1, ...data.map(d => d.amount));
    const points = data.map(item => ({
      x: item.count,
      y: item.amount,
      r: Math.min(6 + Math.sqrt(item.count) * 1.5, 14),
      label: item.type
    }));

    const ctx = canvas.getContext('2d');
    state.charts.bubble = new Chart(ctx, {
      type: 'bubble',
      data: {
        datasets: [{
          label: 'Transaction Types',
          data: points.length ? points : [{x:0,y:0,r:1}],
          backgroundColor: points.length ? points.map((_,i) => colors[i % colors.length] + 'CC') : ['#ccc'],
          borderColor: points.length ? points.map((_,i) => colors[i % colors.length]) : ['#999'],
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { top: 6, bottom: 4, left: 4, right: 10 } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => `${ctx.raw.label||'Type'}: ${ctx.raw.x} txns, $${ctx.raw.y.toFixed(0)}` } } },
        scales: {
          y: { suggestedMax: maxAmount * 1.25, title: { display: true, text: 'Amount ($)', font: { size: 7 } }, ticks: { font: { size: 6 } }, grid: { color: 'rgba(0,0,0,0.04)' } },
          x: { suggestedMin: 0, title: { display: true, text: 'Count', font: { size: 7 } }, ticks: { stepSize: 1, font: { size: 6 } }, grid: { color: 'rgba(0,0,0,0.04)' } }
        }
      }
    });
  }

  function renderAllSuspiciousTable() {
    const tbody = document.querySelector('#adminAllSuspiciousTable tbody');
    if (!tbody) return;
    let data = state.suspicious;
    const verdictFilter = document.getElementById('adminVerdictFilter')?.value || 'all';
    if (verdictFilter === 'fraud') data = data.filter(t => t.verdict === 'fraud');
    else if (verdictFilter === 'suspicious') data = data.filter(t => t.verdict === 'suspicious');
    else if (verdictFilter === 'medium') data = data.filter(t => t.risk_level === 'medium');
    else if (verdictFilter === 'false_positive') data = data.filter(t => t.verdict === 'false_positive');

    const period = document.getElementById('adminDateFilterType')?.value || 'monthly';
    const { start, end } = getWindowRange(period);
    data = data.filter(tx => {
      if (!tx.timestamp) return false;
      const d = new Date(tx.timestamp);
      return d >= start && d <= end;
    });

    data.sort((a,b) => new Date(b.timestamp) - new Date(a.timestamp));
    const rows = data.slice(0, 50);
    if (!rows.length) { tbody.innerHTML = '<tr><td colspan="5">No transactions match the filter.</td></tr>'; return; }

    tbody.innerHTML = rows.map(tx => {
      const riskClass = tx.verdict === 'fraud' ? 'fraud' : (tx.risk_level === 'high' ? 'high' : (tx.risk_level === 'medium' ? 'medium' : 'suspicious'));
      const riskLabel = tx.verdict || tx.risk_level || 'Suspicious';
      const rules = (tx.triggered_rules || []).map(r => typeof r === 'string' ? r : (r.rule_name || r.rule_id)).join(', ') || '—';
      const score = tx.final_score || tx.risk_score || '—';
      return `<tr>
        <td><strong>${tx.transaction_id || 'N/A'}</strong></td>
        <td><span class="risk-badge ${riskClass}">${riskLabel}</span></td>
        <td>${score}</td>
        <td>${rules}</td>
        <td>${tx.timestamp ? formatDateShort(tx.timestamp) : '—'}</td>
      </tr>`;
    }).join('');
  }

  function renderTopMerchants() {
    const container = document.getElementById('adminTopMerchantsList');
    if (!container) return;
    const merchants = state.topMerchants;
    container.innerHTML = merchants.length
      ? merchants.map(m => `<li><span class="merchant-name">${m.name}</span><span class="merchant-count">${m.count}</span></li>`).join('')
      : '<li>No merchant data</li>';
  }

  function renderPeakHours() {
    const container = document.getElementById('adminPeakHoursInfo');
    if (!container) return;
    const peaks = state.peakHours;
    if (!peaks.length) { container.textContent = 'No data available.'; return; }
    const total = peaks.reduce((s,p) => s+p.count, 0);
    container.innerHTML = `<div class="peak-info"><strong>Top Hours:</strong> ${peaks.map(p => `${p.hour}:00 (${p.count} txns)`).join('; ')}</div>
      <div class="peak-info"><strong>Total in peak:</strong> ${total} transactions</div>`;
  }

  // ---- PDF EXPORT for Reports ----
  async function exportAdminReportPDF() {
    const btn = document.getElementById('adminReportPdfBtn');
    if (!btn) return;
    btn.disabled = true;
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';

    try {
      if (typeof window.jspdf === 'undefined') {
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js';
          s.onload = resolve; s.onerror = reject;
          document.head.appendChild(s);
        });
      }
      if (typeof window.jspdf?.jsPDF?.prototype?.autoTable === 'undefined') {
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.31/jspdf.plugin.autotable.min.js';
          s.onload = resolve; s.onerror = reject;
          document.head.appendChild(s);
        });
      }
      if (typeof html2canvas === 'undefined') {
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
          s.onload = resolve; s.onerror = reject;
          document.head.appendChild(s);
        });
      }

      await new Promise(r => setTimeout(r, 300));

      const { jsPDF } = window.jspdf;
      const doc = new jsPDF('l', 'mm', 'a4');

      const reportsElement = document.getElementById('page-reports');
      const canvas = await html2canvas(reportsElement, {
        scale: 1.8,
        useCORS: true,
        logging: false,
        backgroundColor: '#ffffff',
        windowHeight: reportsElement.scrollHeight
      });
      const imgData = canvas.toDataURL('image/png');
      const imgWidth = 280;
      const imgHeight = (canvas.height * imgWidth) / canvas.width;
      doc.addImage(imgData, 'PNG', 5, 5, imgWidth, imgHeight);

      const period = document.getElementById('adminPdfPeriodSelect')?.value || 'monthly';
      const { start, end } = getWindowRange(period);

      let pdfData = state.suspicious.filter(tx => {
        if (!tx.timestamp) return false;
        const d = new Date(tx.timestamp);
        return d >= start && d <= end;
      });

      doc.addPage();
      doc.setFontSize(14);
      const sourceLabel = state.reportSourceFilter === 'all' ? 'All Sources' : state.reportSourceFilter;
      const periodLabel = period.charAt(0).toUpperCase() + period.slice(1);
      doc.text(`Suspicious Transactions – ${sourceLabel} (${periodLabel} Report)`, 14, 15);

      const rows = pdfData.map(tx => [
        tx.transaction_id || 'N/A',
        tx.amount || 0,
        tx.timestamp ? new Date(tx.timestamp).toLocaleDateString() : 'N/A',
        tx.verdict || tx.risk_level || 'unknown',
        (tx.triggered_rules || []).map(r => r.rule_name || r.rule_id).join(', ') || 'None',
        tx.source_system || 'unknown'
      ]);

      doc.autoTable({
        startY: 22,
        head: [['ID', 'Amount', 'Date', 'Risk', 'Rules', 'Source']],
        body: rows,
        theme: 'striped',
        styles: { fontSize: 7 },
        headStyles: { fillColor: [44, 53, 49] },
        columnStyles: {
          0: { cellWidth: 30 },
          1: { cellWidth: 20 },
          2: { cellWidth: 25 },
          3: { cellWidth: 20 },
          4: { cellWidth: 70 },
          5: { cellWidth: 30 }
        }
      });

      const sourceSuffix = state.reportSourceFilter === 'all' ? '' : '_' + state.reportSourceFilter;
      doc.save(`admin_fraud_report${sourceSuffix}_${period}_${new Date().toISOString().slice(0,10)}.pdf`);

    } catch (err) {
      console.error(err);
      alert('PDF export failed: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }

  // ---- EVENT BINDING for Reports ----
  function bindAdminReportEvents() {
    document.querySelectorAll('#page-reports .trend-filter').forEach(btn => {
      btn.addEventListener('click', function() {
        document.querySelectorAll('#page-reports .trend-filter').forEach(b => b.classList.remove('active'));
        this.classList.add('active');
        loadTrend(this.dataset.period);
      });
    });

    document.getElementById('adminRulesApplyBtn')?.addEventListener('click', () => {
      const startStr = document.getElementById('adminRulesStartDate')?.value;
      const endStr = document.getElementById('adminRulesEndDate')?.value;
      if (!startStr && !endStr) { renderRulesBarChart(); return; }
      const start = startStr ? new Date(startStr) : new Date(0);
      const end = endStr ? new Date(endStr + 'T23:59:59') : new Date();
      const filtered = state.suspicious.filter(tx => {
        if (!tx.timestamp) return false;
        const d = new Date(tx.timestamp);
        return d >= start && d <= end;
      });
      const rulesMap = {};
      filtered.forEach(t => {
        (t.triggered_rules || []).forEach(r => {
          const name = typeof r === 'string' ? r : (r.rule_name || r.rule_id || 'Unknown');
          rulesMap[name] = (rulesMap[name] || 0) + 1;
        });
      });
      state.rulesTriggered = rulesMap;
      renderRulesBarChart();
    });

    document.getElementById('adminAllTransactionsApplyBtn')?.addEventListener('click', () => {
      renderAllSuspiciousTable();
    });

    document.getElementById('adminVerdictFilter')?.addEventListener('change', () => {
      renderAllSuspiciousTable();
    });

    document.getElementById('adminReportSource')?.addEventListener('change', function() {
      state.reportSourceFilter = this.value;
      applySourceFilterAndRenderAll();
    });

    document.getElementById('adminReportsRefreshBtn')?.addEventListener('click', async () => {
      await loadAdminReportData();
      populateSourceDropdown();
      applySourceFilterAndRenderAll();
    });

    document.getElementById('adminReportPdfBtn')?.addEventListener('click', exportAdminReportPDF);

    document.getElementById('adminViewAllBtn')?.addEventListener('click', () => {
      document.querySelector('#page-reports .all-transactions .table-scroll')?.scrollIntoView({ behavior: 'smooth' });
    });

    const endDateInput = document.getElementById('adminRulesEndDate');
    const startDateInput = document.getElementById('adminRulesStartDate');
    if (endDateInput && !endDateInput.value) endDateInput.valueAsDate = new Date();
    if (startDateInput && !startDateInput.value) {
      const d = new Date(); d.setDate(d.getDate() - 30); startDateInput.valueAsDate = d;
    }
  }

  // ---------- USER MANAGEMENT ----------
  async function fetchUsers() {
    const container = document.getElementById('userTableContainer');
    if (!container) return;
    container.innerHTML = '<div class="loading">Loading...</div>';
    try {
      const token = getToken();
      const res = await fetch('/admin/users', {
        headers: { Authorization: 'Bearer ' + token }
      });
      if (!res.ok) throw new Error('Failed to fetch users');
      const data = await res.json();
      state.allUsers = data;
      state.users = data.filter(u => u.role === 'user');
      state.lastUpdated = new Date();
      const updatedEl = document.getElementById('userLastUpdated');
      if (updatedEl) updatedEl.textContent = 'Last updated: ' + state.lastUpdated.toLocaleTimeString();
      renderUsers();
    } catch (err) {
      container.innerHTML = '<div class="error-msg">' + err.message + '</div>';
    }
  }

  function generateActionButtons(user) {
    const isApproveDisabled = (user.status !== 'pending' && user.status !== 'rejected');
    const isRejectDisabled = (user.status !== 'pending');
    const isActivateDisabled = (user.status !== 'inactive');
    const isDeactivateDisabled = (user.status !== 'active');
    return `
      <button class="activate-btn" data-user-id="${user.user_id}" data-action="approve" ${isApproveDisabled ? 'disabled' : ''}>Approve</button>
      <button class="deactivate-btn" data-user-id="${user.user_id}" data-action="reject" ${isRejectDisabled ? 'disabled' : ''}>Reject</button>
      <button class="activate-btn" data-user-id="${user.user_id}" data-action="activate" ${isActivateDisabled ? 'disabled' : ''}>Activate</button>
      <button class="deactivate-btn" data-user-id="${user.user_id}" data-action="deactivate" ${isDeactivateDisabled ? 'disabled' : ''}>Deactivate</button>
    `;
  }

  function truncateStr(str, max = 25) {
    if (!str) return '';
    return str.length > max ? str.substring(0, max-3) + '...' : str;
  }

  function renderUsers() {
    const container = document.getElementById('userTableContainer');
    if (!container) return;
    const users = state.users;
    if (!users || users.length === 0) {
      container.innerHTML = '<p class="empty-message">No users found.</p>';
      return;
    }

    let html = '<div class="user-table-wrap"><table class="user-table"><thead><tr>';
    html += '<th>Organization</th><th>Email</th><th>Status</th><th style="text-align:center;">Details</th></tr></thead><tbody>';

    users.forEach(u => {
      const isOpen = state.expanded[u.user_id] || false;
      const statusStyle = {
        pending: { background: '#f39c12', color: '#000' },
        active: { background: '#2ecc71', color: '#000' },
        inactive: { background: '#e74c3c', color: '#fff' },
        rejected: { background: '#c0392b', color: '#fff' }
      }[u.status] || { background: '#f39c12', color: '#000' };

      html += `
        <tr data-user-id="${u.user_id}" class="user-row">
          <td><strong>${u.organization_name || u.full_name}</strong></td>
          <td>${u.email}</td>
          <td><span class="status-badge-sm" style="background:${statusStyle.background};color:${statusStyle.color}">${u.status.toUpperCase()}</span></td>
          <td class="expand-cell"><span class="expand-icon ${isOpen ? 'open' : ''}">▼</span></td>
        </tr>
        <tr class="user-details-row" style="${isOpen ? '' : 'display:none;'}">
          <td colspan="4">
            <div class="user-details-inner">
              <div class="detail-item"><span class="label">User ID</span><span class="value">${u.user_id}</span></div>
              <div class="detail-item"><span class="label">Phone</span><span class="value">${u.contact_phone || '-'}</span></div>
              <div class="detail-item"><span class="label">Address</span><span class="value">${u.physical_address || '-'}</span></div>
              <div class="detail-item"><span class="label">Reg No</span><span class="value">${u.company_reg_no || '-'}</span></div>
              <div class="detail-item"><span class="label">KRA PIN</span><span class="value">${u.kra_pin || '-'}</span></div>
              <div class="detail-item"><span class="label">Source</span><span class="value">${u.source_system || '-'}</span></div>
              <div class="detail-item" style="grid-column: 1 / -1;">
                <span class="label">Reg Doc</span>
                <span class="value doc-links">
                  ${u.docs?.cert_file?.filename ? `<button class="link-button" data-user-id="${u.user_id}" data-doc="cert_file">${truncateStr(u.docs.cert_file.filename)}</button>` : '-'}
                </span>
              </div>
              <div class="detail-item" style="grid-column: 1 / -1;">
                <span class="label">KRA Doc</span>
                <span class="value doc-links">
                  ${u.docs?.kra_cert_file?.filename ? `<button class="link-button" data-user-id="${u.user_id}" data-doc="kra_cert_file">${truncateStr(u.docs.kra_cert_file.filename)}</button>` : '-'}
                </span>
              </div>
              <div class="detail-item" style="grid-column: 1 / -1; border-bottom: none;">
                <span class="label">Actions</span>
                <span class="value action-buttons">
                  ${generateActionButtons(u)}
                </span>
              </div>
            </div>
          </td>
        </tr>
      `;
    });

    html += '</tbody></table></div>';
    container.innerHTML = html;

    container.querySelectorAll('.user-row').forEach(row => {
      row.addEventListener('click', function(e) {
        const userId = this.dataset.userId;
        state.expanded[userId] = !state.expanded[userId];
        renderUsers();
      });
    });

    container.querySelectorAll('.action-buttons button[data-action]').forEach(btn => {
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (this.disabled) return;
        const userId = this.dataset.userId;
        const action = this.dataset.action;
        let newStatus = '';
        if (action === 'approve' || action === 'activate') {
          newStatus = 'active';
        } else if (action === 'deactivate') {
          newStatus = 'inactive';
        } else if (action === 'reject') {
          newStatus = 'rejected';
        }
        if (newStatus) {
          cycleUserStatus(userId, newStatus);
        }
      });
    });

    container.querySelectorAll('.link-button[data-doc]').forEach(btn => {
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        const userId = this.dataset.userId;
        const docType = this.dataset.doc;
        downloadDocument(userId, docType);
      });
    });
  }

  async function cycleUserStatus(userId, newStatus) {
    try {
      const token = getToken();
      const res = await fetch('/admin/users/' + userId + '/status', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error('Failed to update status');
      fetchUsers();
    } catch (err) {
      alert('Error updating status: ' + err.message);
    }
  }

  async function downloadDocument(userId, docType) {
    try {
      const token = getToken();
      const res = await fetch('/admin/users/' + userId + '/document/' + docType, {
        headers: { Authorization: 'Bearer ' + token }
      });
      if (!res.ok) throw new Error('Download failed');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      window.open(url, '_blank');
    } catch (err) {
      alert('Could not download document: ' + err.message);
    }
  }

  // ---------- SYS HEALTH ----------
  async function fetchHealth() {
    const container = document.getElementById('healthCardsContainer');
    if (!container) return;
    container.innerHTML = '<div class="loading">Loading...</div>';
    try {
      const token = getToken();
      const res = await fetch('/admin/syshealth', {
        headers: { Authorization: 'Bearer ' + token }
      });
      if (!res.ok) throw new Error('Failed to fetch health');
      const data = await res.json();
      state.containers = data;
      state.lastUpdated = new Date();
      const updatedEl = document.getElementById('healthLastUpdated');
      if (updatedEl) updatedEl.textContent = 'Last updated: ' + state.lastUpdated.toLocaleTimeString();
      renderHealth();
    } catch (err) {
      container.innerHTML = '<div class="error-msg">' + err.message + '</div>';
    }
  }

  function renderHealth() {
    const container = document.getElementById('healthCardsContainer');
    if (!container) return;
    const data = state.containers;
    if (!data || data.length === 0) {
      container.innerHTML = '<p class="empty-message">No health data available.</p>';
      return;
    }
    let html = '';
    data.forEach(c => {
      const color = c.status === 'active' ? 'var(--success)' : (c.status === 'degraded' ? 'var(--warning)' : 'var(--danger)');
      const icon = c.status === 'active' ? '●' : (c.status === 'degraded' ? '◐' : '○');
      html += `
        <div class="syshealth-card">
          <div class="syshealth-card-top">
            <span class="syshealth-status-icon" style="color:${color}">${icon}</span>
            <h3>${c.name}</h3>
          </div>
          <div class="syshealth-card-details">
            <div class="syshealth-metric"><span class="metric-label">Status</span><span class="metric-value" style="color:${color}">${c.status}</span></div>
            <div class="syshealth-metric"><span class="metric-label">Health</span><span class="metric-value">${c.health || 'OK'}</span></div>
          </div>
          <div class="syshealth-card-indicator" style="background-color:${color}"></div>
        </div>
      `;
    });
    container.innerHTML = html;
  }

  async function exportHealthPDF() {
    const btn = document.getElementById('healthCsvBtn');
    if (!btn) return;
    btn.disabled = true;
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';

    try {
      // Load jspdf and autoTable if not present
      if (typeof window.jspdf === 'undefined') {
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js';
          s.onload = resolve;
          s.onerror = reject;
          document.head.appendChild(s);
        });
      }
      if (typeof window.jspdf?.jsPDF?.prototype?.autoTable === 'undefined') {
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.31/jspdf.plugin.autotable.min.js';
          s.onload = resolve;
          s.onerror = reject;
          document.head.appendChild(s);
        });
      }

      await new Promise(r => setTimeout(r, 300));

      const { jsPDF } = window.jspdf;
      const doc = new jsPDF('p', 'mm', 'a4');
      const data = state.containers || [];

      doc.setFontSize(16);
      doc.text('System Health Report', 14, 20);
      doc.setFontSize(10);
      doc.text(`Generated: ${new Date().toLocaleString()}`, 14, 28);

      const rows = data.map(c => [c.name, c.status, c.health || 'OK']);

      doc.autoTable({
        startY: 35,
        head: [['Service', 'Status', 'Health']],
        body: rows,
        theme: 'striped',
        styles: { fontSize: 9 },
        headStyles: { fillColor: [44, 53, 49] },
        columnStyles: {
          0: { cellWidth: 60 },
          1: { cellWidth: 40 },
          2: { cellWidth: 50 }
        }
      });

      doc.save(`system_health_${new Date().toISOString().slice(0,10)}.pdf`);

    } catch (err) {
      console.error(err);
      alert('PDF export failed: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }

  // ---------- AUDIT TRAIL ----------
  async function fetchAuditLogs() {
    const container = document.getElementById('auditTableContainer');
    if (!container) return;
    container.innerHTML = '<div class="loading">Loading...</div>';
    try {
      const token = getToken();
      if (!token) {
        throw new Error('No authentication token found. Please log in again.');
      }

      const res = await fetch('/admin/audit-logs', {
        headers: { Authorization: 'Bearer ' + token }
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Server returned ${res.status} - ${text.substring(0, 100)}`);
      }

      const logs = await res.json();
      state.auditLogs = logs;
      state.lastUpdated = new Date();
      document.getElementById('auditLastUpdated').textContent = 'Last updated: ' + state.lastUpdated.toLocaleTimeString();
      renderAuditLogs();
    } catch (err) {
      console.error('❌ Audit logs error:', err);
      container.innerHTML = '<div class="error-msg">' + err.message + '</div>';
    }
  }

  function renderAuditLogs() {
    const container = document.getElementById('auditTableContainer');
    if (!container) return;
    const logs = state.auditLogs || [];
    if (!logs.length) {
      container.innerHTML = '<p class="empty-message">No audit records found.</p>';
      return;
    }
    let html = `
      <table class="audit-table">
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Action</th>
            <th>Email / Organization</th>
            <th>IP Address</th>
          </tr>
        </thead>
        <tbody>`;
    logs.forEach(log => {
      const timestamp = log.timestamp ? new Date(log.timestamp).toLocaleString() : '—';
      const action = log.action || '—';
      const identity = log.email || log.organization_name || '—';
      const ip = log.ip || '—';
      html += `
        <tr>
          <td>${timestamp}</td>
          <td><span class="audit-action audit-${action.toLowerCase()}">${action}</span></td>
          <td>${identity}</td>
          <td>${ip}</td>
        </tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
  }

  async function exportAuditPDF() {
    const btn = document.getElementById('auditPdfBtn');
    if (!btn) return;
    btn.disabled = true;
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';

    try {
      if (typeof window.jspdf === 'undefined') {
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js';
          s.onload = resolve;
          s.onerror = reject;
          document.head.appendChild(s);
        });
      }
      if (typeof window.jspdf?.jsPDF?.prototype?.autoTable === 'undefined') {
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.31/jspdf.plugin.autotable.min.js';
          s.onload = resolve;
          s.onerror = reject;
          document.head.appendChild(s);
        });
      }

      await new Promise(r => setTimeout(r, 300));

      const { jsPDF } = window.jspdf;
      const doc = new jsPDF('l', 'mm', 'a4'); 
      const logs = state.auditLogs || [];

      doc.setFontSize(16);
      doc.text('Audit Trail Report', 14, 20);
      doc.setFontSize(10);
      doc.text(`Generated: ${new Date().toLocaleString()}`, 14, 28);

      const rows = logs.map(log => [
        log.timestamp ? new Date(log.timestamp).toLocaleString() : '—',
        log.action || '—',
        log.email || log.organization_name || '—',
        log.ip || '—'
      ]);

      doc.autoTable({
        startY: 35,
        head: [['Timestamp', 'Action', 'Email / Organization', 'IP Address']],
        body: rows,
        theme: 'striped',
        styles: { fontSize: 7 },
        headStyles: { fillColor: [44, 53, 49] },
        columnStyles: {
          0: { cellWidth: 50 },
          1: { cellWidth: 30 },
          2: { cellWidth: 70 },
          3: { cellWidth: 40 }
        }
      });

      doc.save(`audit_trail_${new Date().toISOString().slice(0,10)}.pdf`);

    } catch (err) {
      console.error(err);
      alert('PDF export failed: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }

  // ---------- SETUP INTERVALS ----------
  function setupIntervals() {
    state.intervals.forEach(i => clearInterval(i));
    state.intervals = [];

    const overviewInterval = setInterval(() => {
      if (state.currentPage === 'overview') fetchOverview();
    }, 30000);
    state.intervals.push(overviewInterval);

    const dataInterval = setInterval(() => {
      if (state.currentPage === 'data') fetchDataTab(state.activeDataTab);
    }, 30000);
    state.intervals.push(dataInterval);

    const reportsInterval = setInterval(() => {
      if (state.currentPage === 'reports') initAdminReports();
    }, 30000);
    state.intervals.push(reportsInterval);

    const usersInterval = setInterval(() => {
      if (state.currentPage === 'user-management') fetchUsers();
    }, 30000);
    state.intervals.push(usersInterval);

    const healthInterval = setInterval(() => {
      if (state.currentPage === 'sys-health') fetchHealth();
    }, 10000);
    state.intervals.push(healthInterval);

    const auditInterval = setInterval(() => {
      if (state.currentPage === 'audit-trail') fetchAuditLogs();
    }, 30000);
    state.intervals.push(auditInterval);
  }

  // ---------- INIT ----------
  function init() {
    loadUser();
    navigateTo('overview');
    setupIntervals();

    const el = (id) => document.getElementById(id);

    document.querySelectorAll('.admin-sidebar li a').forEach(el => {
      el.addEventListener('click', function(e) {
        e.preventDefault();
        const page = this.dataset.page;
        if (page) navigateTo(page);
      });
    });

    if (mobileMenuBtn) {
      mobileMenuBtn.addEventListener('click', function() {
        adminSidebar.classList.toggle('mobile-open');
      });
    }

    if (logoutBtn) {
      logoutBtn.addEventListener('click', handleLogout);
    }

    el('overviewRefreshBtn')?.addEventListener('click', fetchOverview);

    document.querySelectorAll('#dataTabs .admin-tab').forEach(btn => {
      btn.addEventListener('click', function() {
        document.querySelectorAll('#dataTabs .admin-tab').forEach(b => b.classList.remove('active'));
        this.classList.add('active');
        const tab = this.dataset.tab;
        if (tab) fetchDataTab(tab);
      });
    });

    el('dataRefreshBtn')?.addEventListener('click', function() {
      fetchDataTab(state.activeDataTab);
    });

    el('userRefreshBtn')?.addEventListener('click', fetchUsers);
    el('healthRefreshBtn')?.addEventListener('click', fetchHealth);
    // Replace CSV export with PDF
    el('healthCsvBtn')?.addEventListener('click', exportHealthPDF);
    // New audit PDF button
    el('auditPdfBtn')?.addEventListener('click', exportAuditPDF);
    el('auditRefreshBtn')?.addEventListener('click', fetchAuditLogs);

    const neo4jBtn = el('neo4jBtn');
    if (neo4jBtn) {
      neo4jBtn.addEventListener('click', function() {
        window.open('http://localhost:7474/browser/', '_blank');
      });
    }

    console.log('Admin dashboard initialized.');
  }

  document.addEventListener('DOMContentLoaded', init);

})();