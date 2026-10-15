/* frontend — pages/history.js
   ---------------------------------------------------------------------------
   Account history view.

   A thin client over the gateway's /history/* routes. The only logic here is
   building the query and formatting rows; the realised, commission, swap and
   net figures are all produced by the backend, and `net` includes commission
   rather than reporting only realised plus swap.
*/
(function () {
  "use strict";

  var boot = dom.bootstrap();
  var clockOffset = Number(boot.clock_offset) || 0;
  var currency = (boot.account && boot.account.currency) || "";

  var form = document.querySelector('[data-form="history"]');
  var statusNode = document.querySelector('[data-role="history-status"]');
  var metaNode = document.querySelector('[data-role="window-meta"]');
  var dealsNode = document.querySelector('[data-role="deals-body"]');
  var sideNode = document.querySelector('[data-role="side-summary"]');

  function role(name) {
    return document.querySelector('[data-role="' + name + '"]');
  }

  function setRole(name, value) {
    var node = role(name);
    if (node && node.textContent !== value) node.textContent = value;
  }

  function status(text, kind) {
    if (!statusNode) return;
    statusNode.textContent = text || "";
    statusNode.className = "search-status" + (kind ? " " + kind : " muted");
  }

  function emptyState(title, detail) {
    return '<div class="empty">' + fmt.escapeHtml(title)
         + "<span>" + fmt.escapeHtml(detail || "") + "</span></div>";
  }

  function buildQuery() {
    var params = new URLSearchParams();
    if (form.elements.from.value) params.set("from", form.elements.from.value);
    if (form.elements.to.value) params.set("to", form.elements.to.value);
    // The symbol is passed exactly as typed. The engine resolves broker
    // spelling itself; upper-casing here would only make exact-original names
    // harder to reason about.
    if (form.elements.symbol.value.trim()) {
      params.set("symbol", form.elements.symbol.value.trim());
    }
    var query = params.toString();
    return query ? "?" + query : "";
  }

  function renderSummary(summary) {
    var realised = summary.realized_profit;
    var commission = summary.commission;
    var swap = summary.swap;
    var net = summary.net;
    setRole("realised", fmt.signed(realised, 2));
    setRole("commission", fmt.signed(commission, 2));
    setRole("swap", fmt.signed(swap, 2));
    var netNode = role("net");
    if (netNode) {
      netNode.textContent = fmt.signed(net, 2);
      netNode.className = "card-value " + fmt.tone(net);
    }
    setRole("deal-count", String(summary.deal_count || 0));

    var by = summary.by_side || {};
    var parts = [];
    Object.keys(by).forEach(function (side) {
      parts.push(side + " " + fmt.signed(by[side], 2));
    });
    if (sideNode) {
      sideNode.textContent = parts.length ? parts.join(" · ") : "—";
    }
    if (metaNode) {
      var fromStr = summary.from ? String(summary.from).slice(0, 10) : "—";
      var toStr = summary.to ? String(summary.to).slice(0, 10) : "—";
      metaNode.textContent = fromStr + " to " + toStr
        + (currency ? " · " + currency : "");
    }
  }

  function renderDeals(deals) {
    if (!dealsNode) return;
    if (!deals || !deals.length) {
      dealsNode.innerHTML = emptyState("No deals in this window",
        "widen the date range or clear the symbol filter");
      return;
    }
    var rows = deals.slice().sort(function (a, b) {
      return (b.time_msc || b.time || 0) - (a.time_msc || a.time || 0);
    });
    var html = '<table class="grid"><thead><tr>'
      + '<th>Time</th><th>Symbol</th><th>Side</th><th>Entry</th>'
      + "<th>Volume</th><th>Price</th><th>Profit</th>"
      + "<th>Commission</th><th>Swap</th><th>Comment</th>"
      + "</tr></thead><tbody>";
    rows.forEach(function (d) {
      var digits = d.digits === undefined ? 5 : d.digits;
      html += "<tr>"
        + '<td class="muted mono">'
        + fmt.escapeHtml(fmt.shortDateTime(d.time_msc || d.time, clockOffset))
        + "</td>"
        + '<td class="sym">' + fmt.escapeHtml(d.symbol) + "</td>"
        + '<td><span class="tag ' + (d._type === "buy" ? "buy" : "sell") + '">'
        + fmt.escapeHtml(d._type || d.type) + "</span></td>"
        + '<td><span class="tag subtle">' + fmt.escapeHtml(d._entry) + "</span></td>"
        + '<td class="num">' + fmt.num(d.volume, 2) + "</td>"
        + '<td class="num">' + fmt.num(d.price, digits) + "</td>"
        + '<td class="num ' + fmt.tone(d.profit) + '">'
        + fmt.signed(d.profit) + "</td>"
        + '<td class="num muted">' + fmt.signed(d.commission) + "</td>"
        + '<td class="num muted">' + fmt.signed(d.swap) + "</td>"
        + '<td class="muted ellipsis" title="'
        + fmt.escapeHtml(d.comment) + '">'
        + (d.comment ? fmt.escapeHtml(d.comment) : "—") + "</td>"
        + "</tr>";
    });
    dealsNode.innerHTML = html + "</tbody></table>";
  }

  function load() {
    status("loading…", "busy");
    var query = buildQuery();
    Promise.all([
      api.get("/history/summary" + query),
      api.get("/history/deals" + query)
    ]).then(function (results) {
      status("");
      renderSummary(results[0] || {});
      renderDeals((results[1] || {}).deals);
    }).catch(function (err) {
      status(err.message, "error");
      dealsNode.innerHTML = '<div class="empty error">Failed to load history'
        + "<span>" + fmt.escapeHtml(err.message) + "</span></div>";
    });
  }

  if (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      load();
    });
  }

  // Load a recent window once, so the page is not empty on arrival. The
  // backend applies its own default when neither date is supplied.
  load();
  // Ensure fmt is available for shell.js clock
  window.fmt = window.fmt || window.fmtLib || window.fmt;
  window.shell.start(window.dom.bootstrap());
})();