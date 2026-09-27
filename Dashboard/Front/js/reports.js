(function() {
  'use strict';

  const reportsState = {
    overviewTx: [],
    summaryCards: { totalProcessed: 0, suspicious: 0, falsePositives: 0, fraudRatio: 0 },
    fraudTrendData: [],
    recentSuspicious: [],
    allSuspicious: [],
    rulesTriggered: {},
    processedBarData: [],
    bubbleData: [],
    topMerchants: [],
    peakHours: [],
    trendPeriod: 'weekly',
    charts: {},
    initialized: false
  };

  function getToken() { return localStorage.getItem('token'); }
  function getUser() {
    try { return JSON.parse(localStorage.getItem('user') || 'null'); } catch { return null; }
  }
  function formatCurrency(n) { return (n || 0).toLocaleString(); }
  function formatDateShort(iso) {
    if (!iso) return 'N/A';
    try { return new Date(iso).toLocaleDateString(); } catch { return 'N/A'; }
  }
  function getWeekNumber(d) {
    d = new Date(d);
    d.setHours(0,0,0,0);
    d.setDate(d.getDate() + 3 - (d.getDay() + 6) % 7);
    var week1 = new Date(d.getFullYear(), 0, 4);
    return 1 + Math.round(((d - week1) / 86400000 - 3 + (week1.getDay() + 6) % 7) / 7);
  }

  // ---- Date range helpers ----
  function getWindowRange(period) {
    const end = new Date();
    const start = new Date(end);
    if (period === 'weekly') start.setDate(end.getDate() - 7);
    else if (period === 'monthly') start.setMonth(end.getMonth() - 1);
    else if (period === 'yearly') start.setFullYear(end.getFullYear() - 1);
    else start.setDate(end.getDate() - 30); // default overview window
    return { start, end };
  }

  function getTrendRange(period) {
    const end = new Date();
    const start = new Date(end);
    if (period === 'weekly') start.setDate(end.getDate() - 7 * 12);      // 12 weeks
    else if (period === 'monthly') start.setMonth(end.getMonth() - 12); // 12 months
    else start.setFullYear(end.getFullYear() - 5);                     // 5 years
    return { start, end };
  }

  // ---- Core fetch + merge ----
  async function fetchMerged(startDate, endDate) {
    const token = getToken();
    if (!token) throw new Error('Not authenticated. Please log in.');

    const start = startDate.toISOString();
    const end = endDate.toISOString();
    const qs = `start_date=${encodeURIComponent(start)}&end_date=${encodeURIComponent(end)}&limit=10000`;

    const [ruledRes, processedRes] = await Promise.all([
      fetch(`/dashboard/ruled-transactions?${qs}`, { headers: { Authorization: 'Bearer ' + token } }),
      fetch(`/dashboard/reports/recommendations?${qs}`, { headers: { Authorization: 'Bearer ' + token } })
    ]);

    if (!ruledRes.ok || !processedRes.ok) {
      throw new Error('Failed to fetch data from server.');
    }

    const ruledData = await ruledRes.json();
    const processedData = await processedRes.json();

    const ruledMap = {};
    ruledData.forEach(tx => { ruledMap[tx.id] = tx; });

    return (processedData.transactions || []).map(tx => {
      const ruled = ruledMap[tx.id] || {};
      return {
        ...tx,
        risk: ruled.risk || tx.risk || null,
        flagged: ruled.flagged || false,
        triggered_rules: ruled.triggered_rules || [],
        risk_score: ruled.risk_score || tx.risk_score || 0,
        merchant: ruled.merchant || tx.merchant || null,
        sender: ruled.sender || tx.sender || null,
        receiver: ruled.receiver || tx.receiver || null,
        description: ruled.description || tx.description || null,
        transaction_type: ruled.transaction_type || tx.transaction_type || null
      };
    });
  }

  function showError(msg) {
    const container = document.querySelector('.reports');
    if (container) {
      container.innerHTML = `
        <div class="error-msg" style="padding:2rem;text-align:center;background:var(--white);border-radius:12px;">
          <h3> ${msg}</h3>
          <button class="refresh-btn" onclick="window.refreshReportsData()" style="margin-top:1rem;">Retry</button>
        </div>
      `;
    }
  }

  // ============================================================
  // SECTION LOADERS
  // ============================================================

  async function loadOverview(range) {
    const { start, end } = range || getWindowRange('overview');
    const tx = await fetchMerged(start, end);
    reportsState.overviewTx = tx;

    const total = tx.length;
    const fraud = tx.filter(t => t.verdict === 'fraud').length;
    const falsePos = tx.filter(t => t.verdict === 'false_positive').length;
    const suspicious = tx.filter(t =>
      t.flagged || t.verdict === 'fraud' || t.verdict === 'suspicious' ||
      t.risk === 'high' || t.risk === 'critical'
    ).length;

    reportsState.summaryCards = {
      totalProcessed: total,
      suspicious,
      falsePositives: falsePos,
      fraudRatio: total > 0 ? ((fraud / total) * 100).toFixed(1) : 0
    };

    const suspiciousTxns = tx.filter(t =>
      t.flagged || t.risk === 'high' || t.risk === 'critical' ||
      t.verdict === 'fraud' || t.verdict === 'suspicious'
    );
    suspiciousTxns.sort((a, b) => new Date(b.date) - new Date(a.date));
    reportsState.recentSuspicious = suspiciousTxns.slice(0, 10);

    const procMap = {};
    tx.forEach(t => {
      if (!t.date) return;
      const key = new Date(t.date).toISOString().split('T')[0];
      procMap[key] = (procMap[key] || 0) + 1;
    });
    reportsState.processedBarData = Object.keys(procMap).sort().map(k => ({ date: k, count: procMap[k] }));

    const methodMap = {};
    tx.forEach(t => {
      const method = t.transaction_type || t.payment_method || t.type || 'Other';
      if (!methodMap[method]) methodMap[method] = { count: 0, amount: 0 };
      methodMap[method].count += 1;
      methodMap[method].amount += t.amount || 0;
    });
    reportsState.bubbleData = Object.entries(methodMap).map(([type, d]) => ({ type, count: d.count, amount: d.amount }));

    // Only count merchants thathave a name
    const merchantMap = {};
    tx.filter(t => (t.flagged || t.verdict === 'fraud' || t.verdict === 'suspicious') && t.merchant && t.merchant.trim()).forEach(t => {
      merchantMap[t.merchant] = (merchantMap[t.merchant] || 0) + 1;
    });
    reportsState.topMerchants = Object.entries(merchantMap).sort((a,b) => b[1]-a[1]).slice(0,5).map(([name,count]) => ({name,count}));

    const hourMap = {};
    tx.filter(t => t.flagged || t.verdict === 'fraud' || t.verdict === 'suspicious').forEach(t => {
      if (!t.date) return;
      const h = new Date(t.date).getHours();
      hourMap[h] = (hourMap[h] || 0) + 1;
    });
    reportsState.peakHours = Object.entries(hourMap).sort((a,b)=>b[1]-a[1]).slice(0,3).map(([hour,count]) => ({hour:parseInt(hour),count}));
  }

  function generatePeriodKeys(start, end, period) {
    const keys = [];
    const cur = new Date(start);
    if (period === 'weekly') {
      while (cur <= end) {
        keys.push(cur.getFullYear() + '-W' + String(getWeekNumber(cur)).padStart(2, '0'));
        cur.setDate(cur.getDate() + 7);
      }
    } else if (period === 'monthly') {
      while (cur <= end) {
        keys.push(cur.getFullYear() + '-' + String(cur.getMonth() + 1).padStart(2, '0'));
        cur.setMonth(cur.getMonth() + 1);
      }
    } else {
      while (cur <= end) {
        keys.push(String(cur.getFullYear()));
        cur.setFullYear(cur.getFullYear() + 1);
      }
    }
    return keys;
  }

  async function loadTrend(period) {
    reportsState.trendPeriod = period;
    const { start, end } = getTrendRange(period);
    const tx = await fetchMerged(start, end);

    const trendMap = {};
    tx.forEach(t => {
      const isFraudOrSuspicious = (t.verdict === 'fraud' || t.verdict === 'suspicious' ||
        t.risk === 'high' || t.risk === 'critical' || t.flagged === true);
      if (!isFraudOrSuspicious || !t.date) return;
      const d = new Date(t.date);
      let key;
      if (period === 'weekly') key = d.getFullYear() + '-W' + String(getWeekNumber(d)).padStart(2, '0');
      else if (period === 'monthly') key = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
      else key = String(d.getFullYear());
      if (!trendMap[key]) trendMap[key] = { fraud: 0, suspicious: 0 };
      if (t.verdict === 'fraud') trendMap[key].fraud += 1; else trendMap[key].suspicious += 1;
    });

    const allKeys = generatePeriodKeys(start, end, period);
    allKeys.forEach(k => { if (!trendMap[k]) trendMap[k] = { fraud: 0, suspicious: 0 }; });

    reportsState.fraudTrendData = allKeys.map(k => ({ date: k, fraud: trendMap[k].fraud, suspicious: trendMap[k].suspicious }));
    renderFraudTrendChart();
  }

  async function loadRules(startStr, endStr) {
    const start = startStr ? new Date(startStr) : (() => { const d = new Date(); d.setDate(d.getDate()-30); return d; })();
    const end = endStr ? new Date(endStr + 'T23:59:59') : new Date();
    const tx = await fetchMerged(start, end);

    const rulesMap = {};
    tx.forEach(t => {
      (t.triggered_rules || []).forEach(rule => {
        const name = typeof rule === 'string' ? rule : (rule.rule_name || rule.rule_id || 'Unknown');
        rulesMap[name] = (rulesMap[name] || 0) + 1;
      });
    });
    reportsState.rulesTriggered = rulesMap;
    renderRulesBarChart();
  }

  async function loadAllTransactions(period, verdictFilter) {
    const { start, end } = getWindowRange(period);
    const tx = await fetchMerged(start, end);
    let suspicious = tx.filter(t =>
      t.flagged || t.risk === 'high' || t.risk === 'critical' ||
      t.verdict === 'fraud' || t.verdict === 'suspicious'
    );
    reportsState.allSuspicious = suspicious;
    renderAllSuspiciousTable(verdictFilter);
  }

  // ============================================================
  // RENDER
  // ============================================================
  function renderDashboard() {
    renderSummaryCards();
    renderFraudTrendChart();
    renderFraudAlert();
    renderRecentSuspicious();
    renderRulesBarChart();
    renderProcessedBarChart();
    renderBubbleChart();
    renderAllSuspiciousTable();
    renderTopMerchants();
    renderPeakHours();

    const user = getUser();
    const sourceBadge = document.getElementById('reportSourceBadge');
    if (sourceBadge) sourceBadge.textContent = 'Data source: ' + (user?.source_system || 'Not set');
    const lastUpdated = document.getElementById('reportLastUpdated');
    if (lastUpdated) lastUpdated.textContent = 'Last updated: ' + new Date().toLocaleTimeString();
  }

  function renderSummaryCards() {
    const container = document.getElementById('summaryCards');
    if (!container) return;
    const c = reportsState.summaryCards;
    const items = [
      { label: 'Total Processed', value: c.totalProcessed, icon: 'fa-credit-card', cls: '' },
      { label: 'Suspicious Transactions', value: c.suspicious, icon: 'fa-exclamation-triangle', cls: 'red' },
      { label: 'False Positives', value: c.falsePositives, icon: 'fa-times-circle', cls: 'orange' },
      { label: 'Fraud Ratio', value: c.fraudRatio + '%', icon: 'fa-chart-line', cls: 'gold' }
    ];
    container.innerHTML = items.map(item => `
      <div class="summary-card">
        <div class="icon ${item.cls}"><i class="fas ${item.icon}"></i></div>
        <div class="info"><div class="label">${item.label}</div><div class="value">${item.value}</div></div>
      </div>`).join('');
  }

  function renderFraudTrendChart() {
    const canvas = document.getElementById('fraudTrendChart');
    if (!canvas) return;
    if (typeof Chart === 'undefined') { loadChartJs(() => renderFraudTrendChart()); return; }
    if (reportsState.charts.fraudTrend) reportsState.charts.fraudTrend.destroy();

    const data = reportsState.fraudTrendData || [];
    const labels = data.map(d => d.date);
    const ctx = canvas.getContext('2d');
    reportsState.charts.fraudTrend = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels.length ? labels : ['No data'],
        datasets: [
          { label: 'Fraud', data: labels.length ? data.map(d=>d.fraud) : [0], borderColor: '#e74c3c', backgroundColor: 'rgba(231,76,60,0.1)', fill: true, tension: 0.3, pointRadius: 2, borderWidth: 2 },
          { label: 'Suspicious', data: labels.length ? data.map(d=>d.suspicious) : [0], borderColor: '#f39c12', backgroundColor: 'rgba(243,156,18,0.1)', fill: true, tension: 0.3, pointRadius: 2, borderWidth: 2 }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { boxWidth: 10, font: { size: 9 }, usePointStyle: true } }, tooltip: { mode: 'index', intersect: false } },
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, font: { size: 8 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
          x: { grid: { display: false }, ticks: { font: { size: 7 }, maxRotation: 45 } }
        }
      }
    });
  }

  function renderFraudAlert() {
    const totalSuspicious = reportsState.summaryCards.suspicious || 0;
    const gauge = document.getElementById('fraudGauge');
    const label = document.getElementById('gaugeLabel');
    const totalEl = document.getElementById('totalSuspicious');
    if (totalEl) totalEl.textContent = `Total Suspicious: ${totalSuspicious}`;
    let level = 'Low', angle = -45, color = 'var(--success)';
    if (totalSuspicious > 20) { level = 'High'; angle = 45; color = 'var(--danger)'; }
    else if (totalSuspicious > 10) { level = 'Medium'; angle = 0; color = 'var(--warning)'; }
    if (gauge) { const needle = gauge.querySelector('.gauge-needle'); if (needle) needle.style.transform = `rotate(${angle}deg)`; }
    if (label) { label.textContent = level; label.style.color = color; }
  }

  function renderRecentSuspicious() {
    const container = document.getElementById('recentSuspiciousList');
    if (!container) return;
    const list = reportsState.recentSuspicious || [];
    if (!list.length) { container.innerHTML = '<p class="empty-message">No recent suspicious activity.</p>'; return; }
    let html = '<div class="recent-list">';
    list.forEach(tx => {
      const isFraud = (tx.verdict === 'fraud' || tx.risk === 'high' || tx.risk === 'critical');
      const riskClass = isFraud ? 'fraud' : 'suspicious';
      const riskLabel = isFraud ? 'Fraud' : 'Suspicious';
      const rules = (tx.triggered_rules || []).length;
      const score = tx.finalScore || tx.risk_score || tx.score || '—';
      html += `<div class="recent-item">
        <span class="tx-id">${tx.id || 'N/A'}</span>
        <span class="tx-risk ${riskClass}">${riskLabel}</span>
        <span class="tx-score">${score}</span>
        <span class="tx-rules">${rules} rules</span>
      </div>`;
    });
    html += '</div>';
    container.innerHTML = html;
  }

  function renderRulesBarChart() {
    const canvas = document.getElementById('rulesBarChart');
    if (!canvas) return;
    if (typeof Chart === 'undefined') { loadChartJs(() => renderRulesBarChart()); return; }
    if (reportsState.charts.rules) reportsState.charts.rules.destroy();

    const rules = reportsState.rulesTriggered || {};
    const sorted = Object.entries(rules).sort((a,b) => b[1]-a[1]);
    const labels = sorted.map(([name]) => name.length > 18 ? name.substring(0,16)+'…' : name);
    const counts = sorted.map(([,c]) => c);
    const fullLabels = sorted.map(([name]) => name);
    const palette = ['#116466','#3498db','#e67e22','#9b59b6','#1abc9c','#e74c3c','#2ecc71','#f39c12','#34495e','#16a085'];
    const barColors = counts.map((_, i) => palette[i % palette.length]);

    const ctx = canvas.getContext('2d');
    reportsState.charts.rules = new Chart(ctx, {
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
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => ctx.parsed.x + ' transactions', afterBody: items => 'Rule: ' + fullLabels[items[0].dataIndex] } }
        },
        scales: {
          x: { beginAtZero: true, ticks: { maxTicksLimit: 6, font: { size: 8 } }, grid: { color: 'rgba(0,0,0,0.04)' } },
          y: { grid: { display: false }, ticks: { font: { size: 8 } } }
        }
      }
    });
  }

  function renderProcessedBarChart() {
    const canvas = document.getElementById('processedBarChart');
    if (!canvas) return;
    if (typeof Chart === 'undefined') { loadChartJs(() => renderProcessedBarChart()); return; }
    if (reportsState.charts.processed) reportsState.charts.processed.destroy();

    const data = reportsState.processedBarData || [];
    const ctx = canvas.getContext('2d');
    reportsState.charts.processed = new Chart(ctx, {
      type: 'bar',
      data: { labels: data.length ? data.map(d=>d.date) : ['No data'], datasets: [{ label: 'Processed', data: data.length ? data.map(d=>d.count) : [0], backgroundColor: 'rgba(17,100,102,0.7)', borderColor: '#116466', borderWidth: 1, barPercentage: 0.35, categoryPercentage: 0.6, borderRadius: 2 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ctx.parsed.y + ' transactions' } } },
        scales: { y: { beginAtZero: true, ticks: { stepSize: 1, font: { size: 6 } }, grid: { color: 'rgba(0,0,0,0.05)' } }, x: { grid: { display: false }, ticks: { font: { size: 5 }, maxRotation: 45 } } }
      }
    });
  }

  function renderBubbleChart() {
    const canvas = document.getElementById('bubbleChart');
    if (!canvas) return;
    if (typeof Chart === 'undefined') { loadChartJs(() => renderBubbleChart()); return; }
    if (reportsState.charts.bubble) reportsState.charts.bubble.destroy();

    const data = reportsState.bubbleData || [];
    const colors = ['#e74c3c','#3498db','#2ecc71','#f39c12','#9b59b6','#1abc9c','#e67e22','#1dd1a1'];
    const maxAmount = Math.max(1, ...data.map(d => d.amount));
    const points = data.map(item => ({
      x: item.count,
      y: item.amount,
      r: Math.min(6 + Math.sqrt(item.count) * 1.5, 14),
      label: item.type
    }));

    const ctx = canvas.getContext('2d');
    reportsState.charts.bubble = new Chart(ctx, {
      type: 'bubble',
      data: {
        datasets: [{
          label: 'Transaction Types',
          data: points.length ? points : [{x:0,y:0,r:1}],
          backgroundColor: points.length ? points.map((_,i)=>colors[i%colors.length]+'CC') : ['#ccc'],
          borderColor: points.length ? points.map((_,i)=>colors[i%colors.length]) : ['#999'],
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { top: 6, bottom: 4, left: 4, right: 10 } },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => `${ctx.raw.label||'Type'}: ${ctx.raw.x} txns, $${ctx.raw.y.toFixed(0)}` } }
        },
        scales: {
          y: { suggestedMax: maxAmount * 1.25, title: { display: true, text: 'Amount ($)', font: { size: 7 } }, ticks: { font: { size: 6 } }, grid: { color: 'rgba(0,0,0,0.04)' } },
          x: { suggestedMin: 0, title: { display: true, text: 'Count', font: { size: 7 } }, ticks: { stepSize: 1, font: { size: 6 } }, grid: { color: 'rgba(0,0,0,0.04)' } }
        }
      }
    });
  }

  function renderAllSuspiciousTable(verdictOverride) {
    const tbody = document.querySelector('#allSuspiciousTable tbody');
    if (!tbody) return;
    const filter = verdictOverride || document.getElementById('verdictFilter')?.value || 'all';
    let data = reportsState.allSuspicious || [];
    if (filter === 'fraud') data = data.filter(t => t.verdict === 'fraud');
    else if (filter === 'suspicious') data = data.filter(t => t.verdict === 'suspicious');
    else if (filter === 'medium') data = data.filter(t => t.risk === 'medium');
    else if (filter === 'false_positive') data = data.filter(t => t.verdict === 'false_positive');

    data.sort((a,b) => new Date(b.date) - new Date(a.date));
    const rows = data.slice(0, 50);
    if (!rows.length) { tbody.innerHTML = '<tr><td colspan="5">No transactions match the filter.</td></tr>'; return; }

    tbody.innerHTML = rows.map(tx => {
      const riskClass = tx.verdict === 'fraud' ? 'fraud' : (tx.risk === 'high' ? 'high' : (tx.risk === 'medium' ? 'medium' : 'suspicious'));
      const riskLabel = tx.verdict || tx.risk || 'Suspicious';
      const rules = (tx.triggered_rules || []).map(r => typeof r === 'string' ? r : (r.rule_name || r.rule_id)).join(', ') || '—';
      const score = tx.finalScore || tx.risk_score || tx.score || '—';
      return `<tr>
        <td><strong>${tx.id || 'N/A'}</strong></td>
        <td><span class="risk-badge ${riskClass}">${riskLabel}</span></td>
        <td>${score}</td>
        <td>${rules}</td>
        <td>${tx.date ? formatDateShort(tx.date) : '—'}</td>
      </tr>`;
    }).join('');
  }

  function renderTopMerchants() {
    const container = document.getElementById('topMerchantsList');
    if (!container) return;
    const merchants = reportsState.topMerchants || [];
    container.innerHTML = merchants.length
      ? merchants.map(m => `<li><span class="merchant-name">${m.name}</span><span class="merchant-count">${m.count}</span></li>`).join('')
      : '<li style="opacity:0.6;">No merchant data available for flagged transactions</li>';
  }

  function renderPeakHours() {
    const container = document.getElementById('peakHoursInfo');
    if (!container) return;
    const peaks = reportsState.peakHours || [];
    if (!peaks.length) { container.textContent = 'No data available.'; return; }
    const total = peaks.reduce((s,p) => s+p.count, 0);
    const text = peaks.map(p => `${p.hour}:00 (${p.count} txns)`).join('; ');
    container.innerHTML = `<div class="peak-info"><strong>Top Hours:</strong> ${text}</div><div class="peak-info"><strong>Total in peak:</strong> ${total} transactions</div>`;
  }

  function loadChartJs(callback) {
    if (typeof Chart !== 'undefined') { callback(); return; }
    const script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js';
    script.onload = callback;
    document.head.appendChild(script);
  }

  // ============================================================
  // PDF EXPORT
  // ============================================================
  async function exportPDF() {
    const btn = document.getElementById('pdfExportBtn');
    const periodSelect = document.getElementById('pdfPeriodSelect');
    const period = periodSelect?.value || 'monthly';

    if (btn) { btn.disabled = true; btn.dataset.originalText = btn.innerHTML; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...'; }

    try {
      const loadScript = (src) => new Promise((resolve, reject) => {
        const s = document.createElement('script'); s.src = src; s.onload = resolve; s.onerror = reject; document.head.appendChild(s);
      });
      if (typeof window.jspdf === 'undefined') await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js');
      if (typeof window.jspdf?.jsPDF?.prototype?.autoTable === 'undefined') await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.31/jspdf.plugin.autotable.min.js');
      if (typeof html2canvas === 'undefined') await loadScript('https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js');

      const windowRange = getWindowRange(period);
      await loadOverview(windowRange);
      renderSummaryCards();
      renderFraudAlert();
      renderRecentSuspicious();
      renderProcessedBarChart();
      renderBubbleChart();
      renderTopMerchants();
      renderPeakHours();
      await loadTrend(period === 'weekly' ? 'weekly' : (period === 'yearly' ? 'yearly' : 'monthly'));
      await loadRules(windowRange.start.toISOString().split('T')[0], windowRange.end.toISOString().split('T')[0]);
      await loadAllTransactions(period, 'all');

      await new Promise(r => setTimeout(r, 600));

      const { jsPDF } = window.jspdf;
      const doc = new jsPDF('l', 'mm', 'a4');

      const reportsElement = document.querySelector('.reports');
      const canvas = await html2canvas(reportsElement, { scale: 1.8, useCORS: true, logging: false, backgroundColor: '#ffffff', windowHeight: reportsElement.scrollHeight });
      const imgData = canvas.toDataURL('image/png');
      const imgWidth = 280;
      const imgHeight = (canvas.height * imgWidth) / canvas.width;
      doc.addImage(imgData, 'PNG', 5, 5, imgWidth, imgHeight);

      doc.addPage();
      doc.setFontSize(14);
      const periodLabel = period.charAt(0).toUpperCase() + period.slice(1);
      doc.text(`All Suspicious Transactions (${periodLabel} Report)`, 14, 15);
      const rows = (reportsState.allSuspicious || []).map(tx => [
        tx.id || 'N/A',
        tx.verdict || tx.risk || '—',
        tx.finalScore || tx.risk_score || tx.score || '—',
        (tx.triggered_rules || []).map(r => typeof r === 'string' ? r : (r.rule_name || r.rule_id)).join(', ') || '—',
        tx.date ? formatDateShort(tx.date) : '—'
      ]);
      doc.autoTable({
        startY: 22,
        head: [['ID','Risk','Score','Rules','Date']],
        body: rows,
        theme: 'striped',
        styles: { fontSize: 7 },
        headStyles: { fillColor: [44,53,49] },
        columnStyles: { 0:{cellWidth:30}, 1:{cellWidth:25}, 2:{cellWidth:20}, 3:{cellWidth:100}, 4:{cellWidth:30} }
      });

      doc.save(`fraud_report_${period}_${new Date().toISOString().slice(0,10)}.pdf`);

      await refreshReportsData();

    } catch (err) {
      console.error(err);
      alert('PDF export failed: ' + err.message);
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = btn.dataset.originalText || '<i class="fas fa-file-pdf"></i> Export PDF'; }
    }
  }

  // ============================================================
  // INIT
  // ============================================================
  async function refreshReportsData() {
    try {
      await Promise.all([
        loadOverview(getWindowRange('overview')),
        loadTrend(reportsState.trendPeriod),
        loadRules(document.getElementById('rulesStartDate')?.value, document.getElementById('rulesEndDate')?.value),
        loadAllTransactions(document.getElementById('dateFilterType')?.value || 'monthly', document.getElementById('verdictFilter')?.value || 'all')
      ]);
      renderDashboard();
    } catch (err) {
      console.error('Error fetching data:', err);
      showError(err.message || 'Could not load report data.');
    }
  }

  function initReports() {
    if (reportsState.initialized) { refreshReportsData(); return; }
    reportsState.initialized = true;

    const rulesEnd = document.getElementById('rulesEndDate');
    const rulesStart = document.getElementById('rulesStartDate');
    if (rulesEnd && !rulesEnd.value) rulesEnd.valueAsDate = new Date();
    if (rulesStart && !rulesStart.value) { const d = new Date(); d.setDate(d.getDate()-30); rulesStart.valueAsDate = d; }

    document.querySelectorAll('.trend-filter').forEach(btn => {
      btn.addEventListener('click', async function() {
        document.querySelectorAll('.trend-filter').forEach(b => b.classList.remove('active'));
        this.classList.add('active');
        await loadTrend(this.dataset.period);
      });
    });

    document.getElementById('rulesApplyBtn')?.addEventListener('click', async function() {
      await loadRules(document.getElementById('rulesStartDate')?.value, document.getElementById('rulesEndDate')?.value);
    });

    document.getElementById('allTransactionsApplyBtn')?.addEventListener('click', async function() {
      const period = document.getElementById('dateFilterType')?.value || 'monthly';
      const verdict = document.getElementById('verdictFilter')?.value || 'all';
      await loadAllTransactions(period, verdict);
    });

    document.getElementById('verdictFilter')?.addEventListener('change', () => renderAllSuspiciousTable());

    document.getElementById('pdfExportBtn')?.addEventListener('click', exportPDF);
    document.getElementById('reportsRefreshBtn')?.addEventListener('click', refreshReportsData);

    document.getElementById('viewAllBtn')?.addEventListener('click', function() {
      document.querySelector('.all-transactions .table-scroll')?.scrollIntoView({ behavior: 'smooth' });
    });

    refreshReportsData();
    console.log('Reports initialized — real data, real date filters.');
  }

  if (document.getElementById('page-reports')?.classList.contains('active-page')) {
    initReports();
  } else {
    document.addEventListener('click', function(e) {
      const link = e.target.closest('[data-page="reports"]');
      if (link) {
        setTimeout(() => {
          if (document.getElementById('page-reports')?.classList.contains('active-page')) {
            if (!reportsState.initialized) initReports(); else refreshReportsData();
          }
        }, 200);
      }
    });
  }

  window.initReports = initReports;
  window.refreshReportsData = refreshReportsData;

})();