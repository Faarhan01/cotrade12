// frontend — assets/js/pages/bot.js
// =============================================================================
// Bot and Database interface: fetches stored reports, strategies, and diagnostics.

(function () {
  "use strict";

  const api = window.cony?.api;
  const dom = window.cony?.dom;
  const fmt = window.cony?.format;

  async function loadStats() {
    try {
      const stats = await api.get("/db/stats");
      const integrity = await api.get("/db/integrity").catch(() => ({ status: "ok" }));

      const stratsEl = dom.find("[data-role=stat-strategies]");
      const reportsEl = dom.find("[data-role=stat-reports]");
      const hitsEl = dom.find("[data-role=stat-hits]");
      const barsEl = dom.find("[data-role=stat-bars]");
      const pathEl = dom.find("[data-role=stat-path]");
      const integEl = dom.find("[data-role=stat-integrity]");

      if (stratsEl) stratsEl.textContent = stats.strategies ?? "0";
      if (reportsEl) reportsEl.textContent = stats.reports ?? "0";
      if (hitsEl) hitsEl.textContent = stats.pattern_hits ?? "0";
      if (barsEl) barsEl.textContent = stats.cached_bars ?? "0";
      if (pathEl) pathEl.textContent = (stats.path || "").split("/").pop() || "peron.db";
      if (integEl) integEl.textContent = integrity.status === "ok" ? "Healthy (WAL)" : integrity.status;
    } catch (err) {
      console.warn("Failed to load DB stats:", err);
    }
  }

  async function loadReports() {
    const container = dom.find("[data-role=reports-body]");
    if (!container) return;

    try {
      const data = await api.get("/db/reports?limit=25");
      const rows = data.reports || [];

      if (rows.length === 0) {
        container.innerHTML = '<div class="empty">No reports saved yet<span>Run a sweep or backtest in Research</span></div>';
        return;
      }

      let html = '<table class="table mono" style="font-size: 13px;">' +
        '<thead><tr>' +
        '<th>Strategy</th>' +
        '<th>Symbol</th>' +
        '<th>TF</th>' +
        '<th>Trades</th>' +
        '<th>Win%</th>' +
        '<th>Net Pips</th>' +
        '<th>t-stat</th>' +
        '<th>Verdict</th>' +
        '</tr></thead><tbody>';

      for (const r of rows) {
        const netPips = r.net_points != null ? (r.net_points / (r.pip || 1)).toFixed(1) : "-";
        const winRate = r.win_rate != null ? Number(r.win_rate).toFixed(1) + "%" : "-";
        const tStat = r.t_statistic != null ? Number(r.t_statistic).toFixed(2) : "-";
        const verdict = r.verdict || "untested";
        const isGood = verdict === "strong" || verdict === "promising";
        const badgeClass = isGood ? "badge-good" : (verdict === "noise" ? "badge-bad" : "badge-neutral");

        html += '<tr>' +
          '<td><strong>' + dom.escape(r.strategy_name) + '</strong></td>' +
          '<td>' + dom.escape(r.symbol) + '</td>' +
          '<td>' + dom.escape(r.timeframe) + '</td>' +
          '<td>' + r.trades + '</td>' +
          '<td>' + winRate + '</td>' +
          '<td>' + netPips + '</td>' +
          '<td>' + tStat + '</td>' +
          '<td><span class="' + badgeClass + '">' + dom.escape(verdict) + '</span></td>' +
          '</tr>';
      }

      html += '</tbody></table>';
      container.innerHTML = html;
    } catch (err) {
      container.innerHTML = '<div class="empty error">Failed to load reports<span>' + dom.escape(err.message) + '</span></div>';
    }
  }

  async function loadStrategies() {
    const container = dom.find("[data-role=strategies-body]");
    if (!container) return;

    try {
      const data = await api.get("/research/stored").catch(() => ({ strategies: [] }));
      const rows = data.strategies || [];

      if (rows.length === 0) {
        container.innerHTML = '<div class="empty">No custom strategies stored<span>Create or save one in Research</span></div>';
        return;
      }

      let html = '<table class="table" style="font-size: 13px;">' +
        '<thead><tr>' +
        '<th>Name</th>' +
        '<th>Symbol</th>' +
        '<th>Timeframe</th>' +
        '<th>Entry Rule</th>' +
        '<th>Version</th>' +
        '</tr></thead><tbody>';

      for (const s of rows) {
        html += '<tr>' +
          '<td><strong>' + dom.escape(s.name) + '</strong></td>' +
          '<td>' + dom.escape(s.symbol || "any") + '</td>' +
          '<td>' + dom.escape(s.timeframe || "M1") + '</td>' +
          '<td class="mono">' + dom.escape(s.entry_name) + '</td>' +
          '<td>v' + (s.version || 1) + '</td>' +
          '</tr>';
      }

      html += '</tbody></table>';
      container.innerHTML = html;
    } catch (err) {
      container.innerHTML = '<div class="empty">Unable to read stored strategies</div>';
    }
  }

  function setupActions() {
    const vacuumBtn = dom.find("[data-action=db-vacuum]");
    const vacuumStatus = dom.find("[data-role=vacuum-status]");
    if (vacuumBtn) {
      vacuumBtn.addEventListener("click", async () => {
        vacuumBtn.disabled = true;
        if (vacuumStatus) vacuumStatus.textContent = "Vacuuming...";
        try {
          const res = await api.post("/db/vacuum", {});
          if (vacuumStatus) vacuumStatus.textContent = res.message || "Done!";
          loadStats();
        } catch (err) {
          if (vacuumStatus) vacuumStatus.textContent = "Error: " + err.message;
        } finally {
          vacuumBtn.disabled = false;
        }
      });
    }

    const refreshBtn = dom.find("[data-action=refresh-reports]");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => {
        loadReports();
        loadStats();
      });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadStats();
    loadReports();
    loadStrategies();
    setupActions();
  });
})();
