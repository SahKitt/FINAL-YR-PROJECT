(function() {
  'use strict';

  // ---------- STATE ----------
  const state = {
    currentPage: 'overview',
    user: null,
    sourceSystem: null,
    configured: null,
    stats: { totalTransactions: 0, totalFlagged: 0, highRisk: 0, lowRisk: 0, fraudCount: 0, normalCount: 0 },
    recentRuled: [],
    recentProcessed: [],
    ruledTransactions: [],
    processedTransactions: [],
    activeTab: 'ruled',
    url: '',
    anonKey: '',
    serviceRoleKey: '',
    configSource: '',
    activePanel: 'config',
    limit: 1000,
    running: false,
    progressStage: '',
    showProgressPopup: false,
    finalPopup: false,
    faqs: [
      { q: 'How are transactions flagged?', a: 'Our AI model analyzes patterns to flag suspicious transactions.' },
      { q: 'Can I dispute a flagged transaction?', a: 'Yes, contact support with the transaction ID.' },
      { q: 'How often is data updated?', a: 'Real-time updates as transactions are processed.' },
      { q: 'How do I generate a report?', a: 'Go to Reports tab and click download.' }
    ],
    openIndex: null,
    showProfileModal: false,
    mobileMenuOpen: false,
    loading: true,
    error: '',
    lastUpdated: null,
    currentTipIndex: 0,
    tips: [
      "Use the filter buttons to focus on specific risk levels.",
      "Export weekly reports in PDF for your records.",
      "Click on any flagged transaction to see detailed rules triggered.",
      "Data refreshes automatically every 10 seconds.",
      "The Analytics page gives you deeper insights and trends.",
      "Your dashboard is secure - all data is encrypted in transit."
    ],
    intervals: [],
    countPollInterval: null
  };

  // ---------- DOM REFS ----------
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const welcomeMsg = $('#welcomeMsg');
  const sidebar = $('#sidebar');
  const mobileMenuBtn = $('#mobileMenuBtn');
  const profileBtn = $('#profileBtn');
  const logoutBtn = $('#logoutBtn');
  const profileModal = $('#profileModal');
  const profileEmail = $('#profileEmail');
  const profilePassword = $('#profilePassword');
  const profileConfirm = $('#profileConfirm');
  const profileSubmitBtn = $('#profileSubmitBtn');
  const profileCancelBtn = $('#profileCancelBtn');
  const profileError = $('#profileError');
  const profileSuccess = $('#profileSuccess');
  const progressPopup = $('#progressPopup');
  const progressText = $('#progressText');
  const finalPopup = $('#finalPopup');
  const finalPopupBtn = $('#finalPopupBtn');

  // ---------- UTILITY ----------
  function formatDate(iso) {
    if (!iso) return 'N/A';
    try { return new Date(iso).toLocaleString(); } catch { return 'N/A'; }
  }
  function formatDateShort(iso) {
    if (!iso) return 'N/A';
    try { return new Date(iso).toLocaleDateString(); } catch { return 'N/A'; }
  }
  function getToken() { return localStorage.getItem('token'); }
  function getUser() {
    try { return JSON.parse(localStorage.getItem('user') || 'null'); } catch { return null; }
  }
  function formatCurrency(n) { return (n || 0).toLocaleString(); }
  function formatRiskClass(risk) {
    if (!risk) return '';
    const r = risk.toLowerCase();
    if (r === 'critical' || r === 'high') return 'risk-high';
    if (r === 'medium') return 'risk-medium';
    if (r === 'low') return 'risk-low';
    return '';
  }
  function formatRiskLabel(risk) {
    if (!risk) return 'unknown';
    return risk.charAt(0).toUpperCase() + risk.slice(1);
  }

  // ---------- NAVIGATION ----------
  function navigateTo(page) {
    state.currentPage = page;
    $$('.page-section').forEach(el => el.classList.remove('active-page'));
    const target = document.getElementById('page-' + page);
    if (target) target.classList.add('active-page');
    $$('.dashboard-sidebar li a').forEach(el => el.classList.remove('active-link'));
    const link = document.querySelector('.dashboard-sidebar li a[data-page="' + page + '"]');
    if (link) link.classList.add('active-link');
    state.mobileMenuOpen = false;
    if (sidebar) sidebar.classList.remove('mobile-open');
    if (page === 'overview') {
      fetchOverviewData();
    } else if (page === 'analytics') {
      fetchAnalyticsData();
    } else if (page === 'reports') {
      // Initialize Reports
      if (typeof window.initReports === 'function') {
        window.initReports();
      } else if (typeof window.refreshReportsData === 'function') {
        window.refreshReportsData();
      } else {
        // fallback
        console.warn('Reports module not loaded yet - retrying in 500ms');
        setTimeout(() => {
          if (typeof window.initReports === 'function') {
            window.initReports();
          } else {
            console.error('Reports module still not available.');
          }
        }, 500);
      }
    } else if (page === 'controls') {
      fetchConfig();
    }
  }

  // ---------- AUTH ----------
  function loadUser() {
    const u = getUser();
    state.user = u;
    state.sourceSystem = u?.source_system || null;
    if (welcomeMsg) welcomeMsg.textContent = 'Welcome: ' + (u?.organization_name || u?.email || 'User');
  }
  function handleLogout() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.href = '/login';
  }

  // ---------- PROFILE MODAL ----------
  function openProfileModal() {
    const u = getUser();
    if (profileEmail) profileEmail.value = u?.email || '';
    if (profilePassword) profilePassword.value = '';
    if (profileConfirm) profileConfirm.value = '';
    if (profileError) profileError.style.display = 'none';
    if (profileSuccess) profileSuccess.style.display = 'none';
    if (profileModal) profileModal.style.display = 'flex';
    state.showProfileModal = true;
  }
  function closeProfileModal() {
    if (profileModal) profileModal.style.display = 'none';
    state.showProfileModal = false;
  }
  async function handleProfileSubmit(e) {
    e.preventDefault();
    const email = profileEmail ? profileEmail.value.trim() : '';
    const password = profilePassword ? profilePassword.value : '';
    const confirm = profileConfirm ? profileConfirm.value : '';
    if (profileError) profileError.style.display = 'none';
    if (profileSuccess) profileSuccess.style.display = 'none';
    if (password && password !== confirm) {
      if (profileError) {
        profileError.textContent = 'Passwords do not match';
        profileError.style.display = 'block';
      }
      return;
    }
    const token = getToken();
    if (!token) { return; }
    if (profileSubmitBtn) {
      profileSubmitBtn.disabled = true;
      profileSubmitBtn.textContent = 'Updating...';
    }
    try {
      const res = await fetch('/auth/update-profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({ email, password: password || undefined })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Update failed');
      const u = getUser();
      if (u) { u.email = email; localStorage.setItem('user', JSON.stringify(u)); state.user = u; }
      if (profileSuccess) {
        profileSuccess.textContent = 'Profile updated successfully!';
        profileSuccess.style.display = 'block';
      }
      setTimeout(() => closeProfileModal(), 1500);
    } catch (err) {
      if (profileError) {
        profileError.textContent = err.message;
        profileError.style.display = 'block';
      }
    } finally {
      if (profileSubmitBtn) {
        profileSubmitBtn.disabled = false;
        profileSubmitBtn.textContent = 'Update';
      }
    }
  }

  // ---------- TIPS CAROUSEL ----------
  let tipInterval = null;
  function initTips() {
    const dotsContainer = $('#tipDots');
    if (!dotsContainer) return;
    dotsContainer.innerHTML = '';
    state.tips.forEach((_, idx) => {
      const dot = document.createElement('button');
      dot.className = 'dot' + (idx === state.currentTipIndex ? ' active' : '');
      dot.setAttribute('aria-label', 'Tip ' + (idx + 1));
      dot.dataset.idx = idx;
      dot.addEventListener('click', function() {
        state.currentTipIndex = parseInt(this.dataset.idx);
        updateTip();
      });
      dotsContainer.appendChild(dot);
    });
    updateTip();
    if (tipInterval) clearInterval(tipInterval);
    tipInterval = setInterval(() => {
      state.currentTipIndex = (state.currentTipIndex + 1) % state.tips.length;
      updateTip();
    }, 5000);
  }
  function updateTip() {
    const slide = $('#tipSlide');
    if (slide) slide.textContent = state.tips[state.currentTipIndex] || '';
    const dots = $$('#tipDots .dot');
    dots.forEach((d, i) => {
      d.classList.toggle('active', i === state.currentTipIndex);
    });
  }

  // ---------- FETCH: CONFIG CHECK ----------
  async function checkConfig() {
    try {
      const token = getToken();
      if (!token) { state.configured = false; return false; }
      const res = await fetch('/dashboard/controls/supabase-config', {
        headers: { Authorization: 'Bearer ' + token }
      });
      state.configured = res.ok;
      if (res.ok) {
        const config = await res.json();
        state.url = config.url || '';
        state.anonKey = config.anon_key || '';
        state.serviceRoleKey = config.service_role_key || '';
        state.configSource = config.source_system || '';
        const apiUrl = document.getElementById('apiUrl');
        const anonKey = document.getElementById('anonKey');
        const serviceRoleKey = document.getElementById('serviceRoleKey');
        const sourceSystem = document.getElementById('sourceSystem');
        if (apiUrl) apiUrl.value = state.url;
        if (anonKey) anonKey.value = state.anonKey;
        if (serviceRoleKey) serviceRoleKey.value = state.serviceRoleKey;
        if (sourceSystem) sourceSystem.value = state.configSource;
        if (state.configSource) {
          const loadTestSource = document.getElementById('loadTestSource');
          const overviewSource = document.getElementById('overviewSource');
          const analyticsSource = document.getElementById('analyticsSource');
          if (loadTestSource) loadTestSource.textContent = state.configSource;
          if (overviewSource) overviewSource.textContent = 'Data source: ' + state.configSource;
          if (analyticsSource) analyticsSource.textContent = 'Data source: ' + state.configSource;
          switchPanel('loadtest');
        }
      }
      return state.configured;
    } catch {
      state.configured = false;
      return false;
    }
  }

  // ---------- FETCH: OVERVIEW ----------
  async function fetchOverviewData() {
    if (!state.configured || !state.sourceSystem) {
      renderOverviewNoConfig();
      return;
    }
    const token = getToken();
    if (!token) return;
    try {
      const statsRes = await fetch('/dashboard/stats/overview', {
        headers: { Authorization: 'Bearer ' + token }
      });
      if (statsRes.ok) {
        const data = await statsRes.json();
        state.stats = {
          totalTransactions: data.totalTransactions ?? 0,
          totalFlagged: data.totalFlagged ?? 0,
          highRisk: data.highRisk ?? 0,
          lowRisk: data.lowRisk ?? 0,
          fraudCount: data.fraudCount ?? 0,
          normalCount: data.normalCount ?? 0,
        };
        renderStats();
      }
      const ruledRes = await fetch('/dashboard/ruled-transactions?limit=5&skip=0', {
        headers: { Authorization: 'Bearer ' + token }
      });
      if (ruledRes.ok) {
        state.recentRuled = await ruledRes.json();
        renderRecentRuled();
      }
      const procRes = await fetch('/dashboard/processed-transactions?limit=5&skip=0', {
        headers: { Authorization: 'Bearer ' + token }
      });
      if (procRes.ok) {
        state.recentProcessed = await procRes.json();
        renderRecentProcessed();
      }
      state.lastUpdated = new Date();
      const updatedEl = document.getElementById('overviewLastUpdated');
      if (updatedEl) updatedEl.textContent = 'Last updated: ' + state.lastUpdated.toLocaleTimeString();
    } catch (err) {
      console.error(err);
    }
  }

  function renderOverviewNoConfig() {
    const container = document.querySelector('#page-overview .overview');
    if (!container) return;
    const existing = container.querySelector('.no-config-msg');
    if (existing) return;
    const msg = document.createElement('div');
    msg.className = 'no-config-msg';
    msg.style.textAlign = 'center';
    msg.style.padding = '4rem 1rem';
    msg.innerHTML = `
      <h2 style="color:var(--primary-dark);margin-bottom:1rem;">No Data Source Configured</h2>
      <p style="margin-bottom:2rem;">Please connect your Supabase account to start monitoring transactions.</p>
      <span class="load-more-btn" data-nav="controls">Set Up Connection</span>
    `;
    const grid = container.querySelector('.stats-grid');
    if (grid) grid.innerHTML = '';
    const row = container.querySelector('.insights-row');
    if (row) row.innerHTML = '';
    container.appendChild(msg);
    const loadMore = msg.querySelector('.load-more-btn');
    if (loadMore) {
      loadMore.addEventListener('click', function() {
        navigateTo('controls');
      });
    }
  }

  function renderStats() {
    const statTotal = document.getElementById('statTotal');
    const statFlagged = document.getElementById('statFlagged');
    const statHighRisk = document.getElementById('statHighRisk');
    const statLowRisk = document.getElementById('statLowRisk');
    const statFraud = document.getElementById('statFraud');
    const statNormal = document.getElementById('statNormal');
    if (statTotal) statTotal.textContent = state.stats.totalTransactions;
    if (statFlagged) statFlagged.textContent = state.stats.totalFlagged;
    if (statHighRisk) statHighRisk.textContent = state.stats.highRisk;
    if (statLowRisk) statLowRisk.textContent = state.stats.lowRisk;
    if (statFraud) statFraud.textContent = state.stats.fraudCount;
    if (statNormal) statNormal.textContent = state.stats.normalCount;
  }

  function renderRecentRuled() {
    const container = document.getElementById('recentRuledContainer');
    if (!container) return;
    if (!state.recentRuled.length) {
      container.innerHTML = '<p class="empty-message">No ruled transactions found.</p>';
      return;
    }
    let html = '<div class="activity-list">';
    state.recentRuled.forEach(tx => {
      const riskClass = formatRiskClass(tx.risk);
      const riskLabel = formatRiskLabel(tx.risk);
      html += `
        <div class="activity-item">
          <div class="activity-info">
            <span class="activity-id">${tx.id || 'N/A'}</span>
            <span class="activity-risk ${riskClass}">${riskLabel}</span>
            ${tx.flagged ? '<span class="flagged-badge">Flagged</span>' : ''}
          </div>
          <div class="activity-details">
            <span>$${formatCurrency(tx.amount)}</span>
            <span>${formatDate(tx.date)}</span>
          </div>
        </div>
      `;
    });
    html += '</div>';
    container.innerHTML = html;
  }

  function renderRecentProcessed() {
    const container = document.getElementById('recentProcessedContainer');
    if (!container) return;
    if (!state.recentProcessed.length) {
      container.innerHTML = '<p class="empty-message">No processed transactions found.</p>';
      return;
    }
    let html = '<div class="activity-list">';
    state.recentProcessed.forEach(tx => {
      const vClass = tx.verdict === 'fraud' ? 'risk-high' : (tx.verdict === 'normal' ? 'risk-low' : '');
      html += `
        <div class="activity-item">
          <div class="activity-info">
            <span class="activity-id">${tx.id || 'N/A'}</span>
            <span class="activity-risk ${vClass}">${tx.verdict || 'unknown'}</span>
          </div>
          <div class="activity-details">
            <span>$${formatCurrency(tx.amount)}</span>
            <span>Score: ${tx.finalScore ?? '—'}</span>
            <span>${formatDate(tx.date)}</span>
          </div>
        </div>
      `;
    });
    html += '</div>';
    container.innerHTML = html;
  }

  // ---------- FETCH: ANALYTICS ----------
  async function fetchAnalyticsData() {
    if (!state.configured || !state.sourceSystem) {
      renderAnalyticsNoConfig();
      return;
    }
    const token = getToken();
    if (!token) return;
    try {
      const [ruledRes, procRes] = await Promise.all([
        fetch('/dashboard/ruled-transactions?limit=10000', { headers: { Authorization: 'Bearer ' + token } }),
        fetch('/dashboard/processed-transactions?limit=10000', { headers: { Authorization: 'Bearer ' + token } })
      ]);
      state.ruledTransactions = ruledRes.ok ? await ruledRes.json() : [];
      state.processedTransactions = procRes.ok ? await procRes.json() : [];
      state.lastUpdated = new Date();
      const updatedEl = document.getElementById('analyticsLastUpdated');
      if (updatedEl) updatedEl.textContent = 'Last updated: ' + state.lastUpdated.toLocaleTimeString();
      renderAnalyticsTabs();
      renderAnalyticsContent();
    } catch (err) {
      console.error(err);
    }
  }

  function renderAnalyticsNoConfig() {
    const container = document.getElementById('analyticsContent');
    if (!container) return;
    container.innerHTML = `
      <div style="text-align:center;padding:4rem 1rem;">
        <h2 style="color:var(--primary-dark);margin-bottom:1rem;">No Data Source Configured</h2>
        <p style="margin-bottom:2rem;">Please connect your Supabase account to view transaction data.</p>
        <span class="load-more-btn" data-nav="controls">Set Up Connection</span>
      </div>
    `;
    const loadMore = container.querySelector('.load-more-btn');
    if (loadMore) {
      loadMore.addEventListener('click', function() {
        navigateTo('controls');
      });
    }
  }

  function renderAnalyticsTabs() {
    const ruled = state.ruledTransactions || [];
    const processed = state.processedTransactions || [];
    const flagged = ruled.filter(tx => tx.flagged === true);
    const high = ruled.filter(tx => tx.risk === 'high' || tx.risk === 'critical');
    const medium = ruled.filter(tx => tx.risk === 'medium');
    const low = ruled.filter(tx => tx.risk === 'low');
    const fraud = processed.filter(tx => tx.verdict === 'fraud');
    const normal = processed.filter(tx => tx.verdict === 'normal');

    const tabs = document.querySelectorAll('#analyticsTabs .tab, #analyticsTabs .tab-active');
    const labels = ['ruled', 'processed', 'flagged', 'high', 'medium', 'low', 'fraud', 'normal'];
    const counts = [ruled.length, processed.length, flagged.length, high.length, medium.length, low.length, fraud.length, normal.length];
    tabs.forEach((btn, i) => {
      if (i < labels.length) {
        const label = labels[i];
        const count = counts[i];
        btn.textContent = label.charAt(0).toUpperCase() + label.slice(1) + ' (' + count + ')';
        btn.dataset.tab = label;
        btn.className = (label === state.activeTab) ? 'tab-active' : 'tab';
      }
    });
  }

  function renderAnalyticsContent() {
    const container = document.getElementById('analyticsContent');
    if (!container) return;
    const ruled = state.ruledTransactions || [];
    const processed = state.processedTransactions || [];
    const tab = state.activeTab;

    let data = [], title = '', columns = [], type = 'ruled';

    if (tab === 'ruled') {
      data = ruled;
      title = 'Ruled Transactions (Risk Scored)';
      columns = ['id', 'amount', 'date', 'risk_level', 'risk_score', 'flagged', 'rules'];
      type = 'ruled';
    } else if (tab === 'processed') {
      data = processed;
      title = 'Processed Transactions (ML + Cross‑Channel)';
      columns = ['id', 'amount', 'date', 'verdict', 'finalScore', 'mlScore', 'correlationScore'];
      type = 'processed';
    } else if (tab === 'flagged') {
      data = ruled.filter(tx => tx.flagged === true);
      title = 'Flagged Transactions (from ruled data)';
      columns = ['id', 'amount', 'date', 'risk_level', 'risk_score', 'rules'];
      type = 'ruled';
    } else if (tab === 'high') {
      data = ruled.filter(tx => tx.risk === 'high' || tx.risk === 'critical');
      title = 'High Risk Transactions';
      columns = ['id', 'amount', 'date', 'risk_score', 'flagged', 'rules'];
      type = 'ruled';
    } else if (tab === 'medium') {
      data = ruled.filter(tx => tx.risk === 'medium');
      title = 'Medium Risk Transactions';
      columns = ['id', 'amount', 'date', 'risk_score', 'flagged', 'rules'];
      type = 'ruled';
    } else if (tab === 'low') {
      data = ruled.filter(tx => tx.risk === 'low');
      title = 'Low Risk Transactions';
      columns = ['id', 'amount', 'date', 'risk_score', 'flagged', 'rules'];
      type = 'ruled';
    } else if (tab === 'fraud') {
      data = processed.filter(tx => tx.verdict === 'fraud');
      title = 'Fraudulent Transactions';
      columns = ['id', 'amount', 'date', 'finalScore', 'mlScore', 'correlationScore'];
      type = 'processed';
    } else if (tab === 'normal') {
      data = processed.filter(tx => tx.verdict === 'normal');
      title = 'Normal Transactions';
      columns = ['id', 'amount', 'date', 'finalScore', 'mlScore', 'correlationScore'];
      type = 'processed';
    } else {
      container.innerHTML = '<p>No data.</p>';
      return;
    }

    if (!data.length) {
      container.innerHTML = '<h3>' + title + '</h3><p class="empty-message">No transactions found.</p>';
      return;
    }

    const headerMap = {
      id: 'ID',
      amount: 'Amount',
      date: 'Date',
      risk_level: 'Risk Level',
      risk_score: 'Risk Score',
      flagged: 'Flagged',
      rules: 'Rules',
      verdict: 'Verdict',
      finalScore: 'Final Score',
      mlScore: 'ML Score',
      correlationScore: 'Correlation Score'
    };

    let html = '<h3>' + title + '</h3><table class="data-table"><thead><tr>';
    columns.forEach(col => { html += '<th>' + (headerMap[col] || col) + '</th>'; });
    html += '</tr></thead><tbody>';

    data.forEach(tx => {
      html += '<tr>';
      columns.forEach(col => {
        let val = tx[col];
        if (col === 'amount') {
          val = '$' + formatCurrency(val);
        } else if (col === 'date') {
          val = tx.date ? new Date(tx.date).toLocaleDateString() : 'N/A';
        } else if (col === 'flagged') {
          val = val ? 'Yes' : 'No';
        } else if (col === 'rules') {
          val = (val || []).length;
        } else if (col === 'risk_level') {
          val = '<span class="risk-' + (tx.risk || '') + '">' + (tx.risk || '') + '</span>';
        } else if (col === 'verdict') {
          val = '<span class="verdict-' + (tx.verdict || '') + '">' + (tx.verdict || '') + '</span>';
        } else if (col === 'risk_score' || col === 'finalScore' || col === 'mlScore' || col === 'correlationScore') {
          val = val ?? '';
        } else if (val === undefined || val === null) {
          val = '';
        }
        html += '<td>' + val + '</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
  }

  // ---------- CONTROLS: CONFIG ----------
  async function fetchConfig() {
    try {
      const token = getToken();
      if (!token) return;
      const res = await fetch('/dashboard/controls/supabase-config', {
        headers: { Authorization: 'Bearer ' + token }
      });
      if (res.ok) {
        const config = await res.json();
        state.url = config.url || '';
        state.anonKey = config.anon_key || '';
        state.serviceRoleKey = config.service_role_key || '';
        state.configSource = config.source_system || '';
        const apiUrl = document.getElementById('apiUrl');
        const anonKey = document.getElementById('anonKey');
        const serviceRoleKey = document.getElementById('serviceRoleKey');
        const sourceSystem = document.getElementById('sourceSystem');
        if (apiUrl) apiUrl.value = state.url;
        if (anonKey) anonKey.value = state.anonKey;
        if (serviceRoleKey) serviceRoleKey.value = state.serviceRoleKey;
        if (sourceSystem) sourceSystem.value = state.configSource;
        if (state.configSource) {
          const loadTestSource = document.getElementById('loadTestSource');
          const overviewSource = document.getElementById('overviewSource');
          const analyticsSource = document.getElementById('analyticsSource');
          if (loadTestSource) loadTestSource.textContent = state.configSource;
          if (overviewSource) overviewSource.textContent = 'Data source: ' + state.configSource;
          if (analyticsSource) analyticsSource.textContent = 'Data source: ' + state.configSource;
          switchPanel('loadtest');
        }
      }
    } catch (e) {}
  }

  // ---- Verify Credentials ----
  async function verifyCredentials() {
    const url = document.getElementById('apiUrl') ? document.getElementById('apiUrl').value.trim() : '';
    const anon = document.getElementById('anonKey') ? document.getElementById('anonKey').value.trim() : '';
    const service = document.getElementById('serviceRoleKey') ? document.getElementById('serviceRoleKey').value.trim() : '';
    const msgEl = document.getElementById('configMsg');
    const btn = document.getElementById('verifyCredsBtn');
    if (!btn || !msgEl) return;

    if (!url || !anon || !service) {
      msgEl.textContent = 'Please fill in URL, Anon Key, and Service Role Key.';
      msgEl.style.color = 'var(--danger)';
      return;
    }

    btn.disabled = true;
    btn.textContent = 'Verifying...';
    msgEl.textContent = '';
    msgEl.style.color = '';
    try {
      const token = getToken();
      if (!token) { msgEl.textContent = 'Not authenticated.'; btn.disabled = false; btn.textContent = 'Verify & Save Credentials'; return; }
      const res = await fetch('/dashboard/controls/verify-credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
        body: JSON.stringify({ url, anon_key: anon, service_role_key: service })
      });
      const data = await res.json();
      if (!res.ok) {
        msgEl.textContent = data.detail || 'Verification failed.';
        msgEl.style.color = 'var(--danger)';
        btn.disabled = false;
        btn.textContent = 'Verify & Save Credentials';
        return;
      }
      state.url = url;
      state.anonKey = anon;
      state.serviceRoleKey = service;
      msgEl.textContent = 'Credentials verified and saved!';
      msgEl.style.color = 'var(--success)';
      const refreshRes = await fetch('/auth/refresh-token', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + token }
      });
      if (refreshRes.ok) {
        const rd = await refreshRes.json();
        localStorage.setItem('token', rd.access_token);
        localStorage.setItem('user', JSON.stringify(rd.user));
        setTimeout(() => window.location.reload(), 1000);
      } else {
        msgEl.textContent = 'Token refresh failed. Please log out and log in again.';
        msgEl.style.color = 'var(--danger)';
      }
    } catch (err) {
      msgEl.textContent = 'Network error.';
      msgEl.style.color = 'var(--danger)';
    }
    btn.disabled = false;
    btn.textContent = 'Verify & Save Credentials';
  }

  // ---- Save Source System ----
  async function saveSourceSystem() {
    const source = document.getElementById('sourceSystem') ? document.getElementById('sourceSystem').value.trim() : '';
    const msgEl = document.getElementById('sourceMsg');
    const btn = document.getElementById('saveSourceBtn');
    if (!btn || !msgEl) return;

    if (!source) {
      msgEl.textContent = 'Please specify a Source System.';
      msgEl.style.color = 'var(--danger)';
      return;
    }

    btn.disabled = true;
    btn.textContent = 'Saving...';
    msgEl.textContent = '';
    msgEl.style.color = '';
    try {
      const token = getToken();
      if (!token) { msgEl.textContent = 'Not authenticated.'; btn.disabled = false; btn.textContent = 'Save Source System'; return; }
      const res = await fetch('/dashboard/controls/set-source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
        body: JSON.stringify({ source_system: source })
      });
      const data = await res.json();
      if (!res.ok) {
        msgEl.textContent = data.detail || 'Failed to save source system.';
        msgEl.style.color = 'var(--danger)';
        btn.disabled = false;
        btn.textContent = 'Save Source System';
        return;
      }
      state.configSource = source;
      const loadTestSource = document.getElementById('loadTestSource');
      const overviewSource = document.getElementById('overviewSource');
      const analyticsSource = document.getElementById('analyticsSource');
      if (loadTestSource) loadTestSource.textContent = source;
      if (overviewSource) overviewSource.textContent = 'Data source: ' + source;
      if (analyticsSource) analyticsSource.textContent = 'Data source: ' + source;
      msgEl.textContent = 'Source system saved!';
      msgEl.style.color = 'var(--success)';
      const refreshRes = await fetch('/auth/refresh-token', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + token }
      });
      if (refreshRes.ok) {
        const rd = await refreshRes.json();
        localStorage.setItem('token', rd.access_token);
        localStorage.setItem('user', JSON.stringify(rd.user));
        setTimeout(() => window.location.reload(), 1000);
      } else {
        msgEl.textContent = 'Token refresh failed. Please log out and log in again.';
        msgEl.style.color = 'var(--danger)';
      }
    } catch (err) {
      msgEl.textContent = 'Network error.';
      msgEl.style.color = 'var(--danger)';
    }
    btn.disabled = false;
    btn.textContent = 'Save Source System';
  }

  // ---------- CONTROLS: LOAD TEST ----------
  function switchPanel(panel) {
    state.activePanel = panel;
    document.querySelectorAll('.control-tab').forEach(tab => {
      tab.classList.toggle('active', tab.dataset.panel === panel);
    });
    document.querySelectorAll('.slide-panel').forEach(p => {
      p.classList.toggle('active', p.dataset.panel === panel);
    });
  }

  async function getCounts() {
    const token = getToken();
    if (!token) return { rawCount: 0, ruledCount: 0, processedCount: 0 };
    try {
      const [rawRes, ruledRes, procRes] = await Promise.all([
        fetch('/dashboard/transactions?limit=1', { headers: { Authorization: 'Bearer ' + token } }),
        fetch('/dashboard/ruled-transactions?limit=1', { headers: { Authorization: 'Bearer ' + token } }),
        fetch('/dashboard/processed-transactions?limit=1', { headers: { Authorization: 'Bearer ' + token } })
      ]);
      const rawLen = rawRes.ok ? (await rawRes.json()).length : 0;
      const ruledLen = ruledRes.ok ? (await ruledRes.json()).length : 0;
      const procLen = procRes.ok ? (await procRes.json()).length : 0;
      return { rawCount: rawLen, ruledCount: ruledLen, processedCount: procLen };
    } catch { return { rawCount: 0, ruledCount: 0, processedCount: 0 }; }
  }

  async function startLoadTest() {
    const source = state.configSource;
    if (!source) {
      const msgEl = document.getElementById('loadTestMsg');
      if (msgEl) msgEl.textContent = 'Source system not set. Please save it in the Controls section.';
      return;
    }
    const limit = parseInt(document.getElementById('loadLimit') ? document.getElementById('loadLimit').value : 1000) || 1000;
    state.limit = limit;
    state.running = true;
    state.progressStage = 'ingestion';
    state.showProgressPopup = true;
    state.finalPopup = false;
    const progressPopup = document.getElementById('progressPopup');
    const progressText = document.getElementById('progressText');
    const startBtn = document.getElementById('startLoadTestBtn');
    const stopBtn = document.getElementById('stopLoadTestBtn');
    const msgEl = document.getElementById('loadTestMsg');
    if (progressPopup) progressPopup.style.display = 'flex';
    if (progressText) progressText.textContent = 'Ingestion started – raw transactions stored';
    if (startBtn) startBtn.style.display = 'none';
    if (stopBtn) stopBtn.style.display = 'inline-block';
    if (msgEl) msgEl.textContent = '';

    try {
      const token = getToken();
      if (!token) throw new Error('Not authenticated');
      const res = await fetch('/dashboard/controls/loadtest/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
        body: JSON.stringify({ limit })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Error');
      }

      let stage = 'ingestion';
      if (state.countPollInterval) clearInterval(state.countPollInterval);
      state.countPollInterval = setInterval(async () => {
        const counts = await getCounts();
        if (stage === 'ingestion' && counts.rawCount > 0) {
          stage = 'ruled';
          state.progressStage = 'ruled';
          if (progressText) progressText.textContent = 'Ruled transactions stored';
        }
        if (stage === 'ruled' && counts.ruledCount > 0) {
          stage = 'processed';
          state.progressStage = 'processed';
          if (progressText) progressText.textContent = 'ML correlation finished';
        }
        if (stage === 'processed' && counts.processedCount > 0) {
          clearInterval(state.countPollInterval);
          state.countPollInterval = null;
          state.running = false;
          state.showProgressPopup = false;
          state.finalPopup = true;
          if (progressPopup) progressPopup.style.display = 'none';
          const finalPopup = document.getElementById('finalPopup');
          if (finalPopup) finalPopup.style.display = 'flex';
          if (startBtn) startBtn.style.display = 'inline-block';
          if (stopBtn) stopBtn.style.display = 'none';
        }
      }, 3000);
    } catch (err) {
      if (msgEl) msgEl.textContent = err.message || 'Failed to start load test';
      state.running = false;
      state.showProgressPopup = false;
      if (progressPopup) progressPopup.style.display = 'none';
      if (startBtn) startBtn.style.display = 'inline-block';
      if (stopBtn) stopBtn.style.display = 'none';
    }
  }

  function stopLoadTest() {
    if (state.countPollInterval) {
      clearInterval(state.countPollInterval);
      state.countPollInterval = null;
    }
    state.running = false;
    state.showProgressPopup = false;
    state.finalPopup = false;
    const progressPopup = document.getElementById('progressPopup');
    const finalPopup = document.getElementById('finalPopup');
    const startBtn = document.getElementById('startLoadTestBtn');
    const stopBtn = document.getElementById('stopLoadTestBtn');
    const msgEl = document.getElementById('loadTestMsg');
    if (progressPopup) progressPopup.style.display = 'none';
    if (finalPopup) finalPopup.style.display = 'none';
    if (startBtn) startBtn.style.display = 'inline-block';
    if (stopBtn) stopBtn.style.display = 'none';
    if (msgEl) msgEl.textContent = 'Load test stopped.';
  }

  // ---------- SUPPORT ----------
  function renderSupport() {
    const container = document.getElementById('faqList');
    if (!container) return;
    let html = '';
    state.faqs.forEach((faq, idx) => {
      const open = state.openIndex === idx;
      html += `
        <div class="faq-item">
          <button class="faq-question" data-idx="${idx}">${faq.q}</button>
          ${open ? '<div class="faq-answer">' + faq.a + '</div>' : ''}
        </div>
      `;
    });
    container.innerHTML = html;
    container.querySelectorAll('.faq-question').forEach(btn => {
      btn.addEventListener('click', function() {
        const idx = parseInt(this.dataset.idx);
        state.openIndex = (state.openIndex === idx) ? null : idx;
        renderSupport();
      });
    });
  }

  // ---------- SETUP INTERVALS ----------
  function setupIntervals() {
    state.intervals.forEach(i => clearInterval(i));
    state.intervals = [];
    const ov = setInterval(() => {
      if (state.currentPage === 'overview' && state.configured && state.sourceSystem) {
        fetchOverviewData();
      }
    }, 10000);
    state.intervals.push(ov);
    const an = setInterval(() => {
      if (state.currentPage === 'analytics' && state.configured && state.sourceSystem) {
        fetchAnalyticsData();
      }
    }, 10000);
    state.intervals.push(an);
  }

  // ---------- INIT ----------
  async function init() {
    loadUser();
    await checkConfig();
    renderSupport();
    initTips();
    navigateTo('overview');
    setupIntervals();

    // ---- EVENT BINDING ----
    document.querySelectorAll('.dashboard-sidebar li a').forEach(el => {
      el.addEventListener('click', function(e) {
        e.preventDefault();
        const page = this.dataset.page;
        if (page) navigateTo(page);
      });
    });

    document.querySelectorAll('.view-all-link[data-nav]').forEach(el => {
      el.addEventListener('click', function() {
        const page = this.dataset.nav;
        if (page) navigateTo(page);
      });
    });

    if (mobileMenuBtn) {
      mobileMenuBtn.addEventListener('click', function() {
        state.mobileMenuOpen = !state.mobileMenuOpen;
        if (sidebar) sidebar.classList.toggle('mobile-open', state.mobileMenuOpen);
      });
    }

    if (logoutBtn) logoutBtn.addEventListener('click', handleLogout);

    if (profileBtn) profileBtn.addEventListener('click', openProfileModal);
    if (profileCancelBtn) profileCancelBtn.addEventListener('click', closeProfileModal);
    if (profileModal) {
      profileModal.addEventListener('click', function(e) {
        if (e.target === this) closeProfileModal();
      });
    }
    const profileForm = document.getElementById('profileForm');
    if (profileForm) profileForm.addEventListener('submit', handleProfileSubmit);

    const overviewRefreshBtn = document.getElementById('overviewRefreshBtn');
    if (overviewRefreshBtn) {
      overviewRefreshBtn.addEventListener('click', function() {
        if (state.configured && state.sourceSystem) fetchOverviewData();
      });
    }

    document.querySelectorAll('#analyticsTabs .tab, #analyticsTabs .tab-active').forEach(btn => {
      btn.addEventListener('click', function() {
        const tab = this.dataset.tab;
        if (tab) {
          state.activeTab = tab;
          renderAnalyticsTabs();
          renderAnalyticsContent();
        }
      });
    });

    const analyticsRefreshBtn = document.getElementById('analyticsRefreshBtn');
    if (analyticsRefreshBtn) {
      analyticsRefreshBtn.addEventListener('click', function() {
        if (state.configured && state.sourceSystem) fetchAnalyticsData();
      });
    }

    document.querySelectorAll('.control-tab').forEach(tab => {
      tab.addEventListener('click', function() {
        const panel = this.dataset.panel;
        if (panel) switchPanel(panel);
      });
    });

    const verifyCredsBtn = document.getElementById('verifyCredsBtn');
    if (verifyCredsBtn) verifyCredsBtn.addEventListener('click', verifyCredentials);

    const saveSourceBtn = document.getElementById('saveSourceBtn');
    if (saveSourceBtn) saveSourceBtn.addEventListener('click', saveSourceSystem);

    const startLoadTestBtn = document.getElementById('startLoadTestBtn');
    const stopLoadTestBtn = document.getElementById('stopLoadTestBtn');
    if (startLoadTestBtn) startLoadTestBtn.addEventListener('click', startLoadTest);
    if (stopLoadTestBtn) stopLoadTestBtn.addEventListener('click', stopLoadTest);

    const finalPopup = document.getElementById('finalPopup');
    if (finalPopup) {
      finalPopup.addEventListener('click', function(e) {
        if (e.target === this) {
          this.style.display = 'none';
          state.finalPopup = false;
        }
      });
    }

    if (finalPopupBtn) {
      finalPopupBtn.addEventListener('click', function(e) {
        e.stopPropagation(); 
        const popup = document.getElementById('finalPopup');
        if (popup) popup.style.display = 'none';
        state.finalPopup = false;
        navigateTo('reports');
        if (typeof window.refreshReportsData === 'function') {
          window.refreshReportsData();
        }
      });
    }

    const progressPopup = document.getElementById('progressPopup');
    if (progressPopup) {
      progressPopup.addEventListener('click', function(e) {
        if (e.target === this && !state.running) {
          this.style.display = 'none';
          state.showProgressPopup = false;
        }
      });
    }

    document.addEventListener('click', function(e) {
      const target = e.target.closest('[data-nav="controls"]');
      if (target) {
        e.preventDefault();
        navigateTo('controls');
      }
    });

    if (state.configSource) {
      const overviewSource = document.getElementById('overviewSource');
      const analyticsSource = document.getElementById('analyticsSource');
      const loadTestSource = document.getElementById('loadTestSource');
      if (overviewSource) overviewSource.textContent = 'Data source: ' + state.configSource;
      if (analyticsSource) analyticsSource.textContent = 'Data source: ' + state.configSource;
      if (loadTestSource) loadTestSource.textContent = state.configSource;
    }

    console.log('Dashboard initialized.');
  }

  document.addEventListener('DOMContentLoaded', init);

})();