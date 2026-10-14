/* frontend — pages/dashboard.js
   ---------------------------------------------------------------------------
   Drives the account overview.

   Strategy: the server has already rendered every number it knows, so this
   file never fetches what it does not have to. It only

     1. paints the shell from the bootstrap block,
     2. subscribes to the two streams that keep it current.

   Both streams push only when something changed, so a quiet account costs
   almost nothing and there is no polling timer to tune.

   If this file fails to load the page is still a complete account summary -
   it simply stops updating. */
(function () {
  "use strict";

  var boot = dom.bootstrap();
  var clockOffset = Number(boot.clock_offset) || 0;
  var account = boot.account || {};

  /* ── Shell ───────────────────────────────────────────────────────── */

  function role(name) {
    return document.querySelector('[data-role="' + name + '"]');
  }

  function paintStatus(connected) {
    var node = role("status");
    if (!node) return;
    node.innerHTML = connected
      ? '<span class="dot ok"></span>Connected'
      : '<span class="dot bad"></span>Disconnected';
  }

  function setRole(name, value) {
    dom.setText(role(name), value);
  }

  setRole("account", account.login || "—");
  setRole("server", account.server || "—");
  setRole("mode", account._trade_mode || account.trade_mode || "—");
  setRole("account-hint", "account " + (account.login || "—"));
  setRole("leverage-hint", account.server || "—");
  setRole("package", boot.package_version || "—");
  setRole("terminal", boot.terminal && boot.terminal.build
    ? "build " + boot.terminal.build : "—");
  setRole("offset", clockOffset
    ? clockOffset.toFixed(1) + " s offset" : "unknown");
  setRole("permissions",
    ((boot.terminal && boot.terminal.trade_allowed) ? "allowed" : "blocked")
    + " · DLLs "
    + ((boot.terminal && boot.terminal.dlls_allowed) ? "on" : "off"));

  paintStatus(boot.connected !== false);

  /* ── Broker clock ───────────────────────────────────────────────── */

  function tickClock() {
    setRole("clock", fmt.clockOnly(clockOffset) + " UTC");
  }
  tickClock();
  setInterval(tickClock, 1000);

  /* ── Account figures ────────────────────────────────────────────── */

  function paintAccount(a) {
    if (!a) return;
    if (a.balance !== undefined) setRole("balance", fmt.num(a.balance, 2));
    if (a.equity !== undefined) setRole("equity", fmt.num(a.equity, 2));
    if (a.margin !== undefined) {
      setRole("margin", fmt.num(a.margin, 2));
      setRole("margin-hint", "of " + fmt.num(a.margin_free, 2) + " free");
    }
    if (a.profit !== undefined || a.floating_profit !== undefined) {
      var p = a.profit !== undefined ? a.profit : a.floating_profit;
      var node = role("floating");
      if (node) {
        node.textContent = fmt.signed(p, 2);
        node.className = "card-value " + fmt.tone(p);
      }
    }
  }

  paintAccount(boot.account);

  /* ── Tables ─────────────────────────────────────────────────────── */

  function emptyState(title, detail) {
    return '<div class="empty">' + fmt.escapeHtml(title)
         + "<span>" + fmt.escapeHtml(detail || "") + "</span></div>";
  }

  function renderPositions(rows) {
    var body = role("positions-body");
    setRole("positions-count", (rows || []).length + " open");
    if (!body) return;
    if (!rows || !rows.length) {
      body.innerHTML = emptyState("No open positions", "The account is flat");
      return;
    }
    var html = '<table class="grid"><thead><tr><th>Symbol</th><th>Side</th>'
      + "<th>Volume</th><th>Open</th><th>Stop</th><th>Target</th>"
      + '<th>P/L</th><th>Swap</th><th>Ticket</th></tr></thead><tbody>';
    rows.forEach(function (p) {
      var d = p.digits === undefined ? 5 : p.digits;
      var pnl = Number(p.profit);
      html += "<tr>"
        + '<td class="sym">' + fmt.escapeHtml(p.symbol) + "</td>"
        + '<td><span class="tag ' + (p._type === "buy" ? "buy" : "sell") + '">'
        + fmt.escapeHtml(p._type || p.type) + "</span></td>"
        + '<td class="num">' + fmt.num(p.volume, 2) + "</td>"
        + '<td class="num">' + fmt.num(p.price, d) + "</td>"
        + '<td class="num">' + fmt.num(p.sl, d) + "</td>"
        + '<td class="num">' + fmt.num(p.tp, d) + "</td>"
        + '<td class="num ' + fmt.tone(p.profit) + '">' + fmt.signed(p.profit) + "</td>"
        + '<td class="num muted">' + fmt.num(p.swap, 2) + "</td>"
        + '<td class="num muted">' + fmt.escapeHtml(p.ticket) + "</td>"
        + "</tr>";
    });
    body.innerHTML = html + "</tbody></table>";
  }

  function renderOrders(rows) {
    var body = role("orders-body");
    setRole("orders-count", (rows || []).length + " pending");
    if (!body) return;
    if (!rows || !rows.length) {
      body.innerHTML = emptyState("No working orders",
        "Nothing is pending at the broker");
      return;
    }
    var html = '<table class="grid"><thead><tr><th>Symbol</th><th>Side</th>'
      + "<th>Volume</th><th>Entry</th><th>Stop</th><th>Target</th>"
      + "<th>Ticket</th></tr></thead><tbody>";
    rows.forEach(function (o) {
      var d = o.digits === undefined ? 5 : o.digits;
      html += "<tr>"
        + '<td class="sym">' + fmt.escapeHtml(o.symbol) + "</td>"
        + '<td><span class="tag">' + fmt.escapeHtml(o._type || o.type) + "</span></td>"
        + '<td class="num">' + fmt.num(o.volume_current, 2) + "</td>"
        + '<td class="num">' + fmt.num(o.price_open, d) + "</td>"
        + '<td class="num">' + fmt.num(o.sl, d) + "</td>"
        + '<td class="num">' + fmt.num(o.tp, d) + "</td>"
        + '<td class="num muted">' + fmt.escapeHtml(o.ticket) + "</td>"
        + "</tr>";
    });
    body.innerHTML = html + "</tbody></table>";
  }

  function renderDeals(rows) {
    var body = role("deals-body");
    if (!body) return;
    if (!rows || !rows.length) {
      body.innerHTML = emptyState("No deals in the last two days",
        "The history call returned nothing");
      return;
    }
    var html = '<table class="grid"><thead><tr><th>Time</th><th>Symbol</th>'
      + "<th>Side</th><th>Entry</th><th>Volume</th><th>Price</th>"
      + "<th>P/L</th><th>Swap</th><th>Comment</th></tr></thead><tbody>";
    rows.forEach(function (d) {
      var d5 = d.digits === undefined ? 5 : d.digits;
      html += "<tr>"
        + '<td class="muted mono">'
        + fmt.escapeHtml(fmt.shortDateTime(d.time_msc || d.time, clockOffset))
        + "</td>"
        + '<td class="sym">' + fmt.escapeHtml(d.symbol) + "</td>"
        + '<td><span class="tag ' + (d._type === "buy" ? "buy" : "sell") + '">'
        + fmt.escapeHtml(d._type) + "</span></td>"
        + '<td><span class="tag subtle">' + fmt.escapeHtml(d._entry) + "</span></td>"
        + '<td class="num">' + fmt.num(d.volume, 2) + "</td>"
        + '<td class="num">' + fmt.num(d.price, d5) + "</td>"
        + '<td class="num ' + fmt.tone(d.profit) + '">' + fmt.signed(d.profit) + "</td>"
        + '<td class="num muted">' + fmt.signed(d.swap) + "</td>"
        + '<td class="muted ellipsis" title="'
        + fmt.escapeHtml(d.comment) + '">'
        + (d.comment ? fmt.escapeHtml(d.comment) : "—") + "</td>"
        + "</tr>";
    });
    body.innerHTML = html + "</tbody></table>";
  }

  function renderWatchlist(rows) {
    var body = role("watchlist-body");
    if (!body) return;
    if (!rows || !rows.length) {
      body.innerHTML = emptyState("No symbols available", "");
      return;
    }
    var html = '<table class="grid" id="watchlist"><thead><tr><th>Symbol</th>'
      + "<th>Bid</th><th>Ask</th><th>Spread<small>pips</small></th>"
      + "<th>Change %</th><th>Description</th></tr></thead><tbody>";
    rows.forEach(function (s) {
      var d = s.digits === undefined ? 5 : s.digits;
      var change = null;
      if (s.session_open && s.bid) {
        change = ((Number(s.bid) - Number(s.session_open))
                  / Number(s.session_open)) * 100;
      }
      html += "<tr>"
        + '<td class="sym" data-symbol="' + fmt.escapeHtml(s.name) + '">'
        + fmt.escapeHtml(s.name) + "</td>"
        + '<td class="num bid" data-field="bid" data-digits="' + d + '">'
        + fmt.num(s.bid, d) + "</td>"
        + '<td class="num ask" data-field="ask" data-digits="' + d + '">'
        + fmt.num(s.ask, d) + "</td>"
        + '<td class="num muted" data-field="spread" data-point="'
        + fmt.escapeHtml(s.point) + '" data-pip="' + fmt.escapeHtml(s.pip_size) + '">'
        + fmt.num(fmt.spreadPips(s.spread, s.point, s.pip_size), 2) + "</td>"
        + '<td class="num ' + fmt.tone(change) + '" data-field="change">'
        + (change === null ? "—" : fmt.signed(change, 2)) + "</td>"
        + '<td class="muted ellipsis" title="' + fmt.escapeHtml(s.description) + '">'
        + (s.description ? fmt.escapeHtml(s.description) : "—") + "</td>"
        + "</tr>";
    });
    body.innerHTML = html + "</tbody></table>";
  }

  renderPositions(boot.positions);
  renderOrders(boot.orders);
  renderDeals(boot.deals);
  renderWatchlist(boot.watchlist_rows);

  /* ── Live ───────────────────────────────────────────────────────── */

  function markStream(ok) {
    var label = role("stream-state");
    if (label) label.textContent = ok ? "live" : "reconnecting";
    var panel = role("watchlist-panel");
    if (panel) panel.className = ok ? "panel streaming" : "panel stream-stale";
  }

  api.stream(boot.portfolio_stream, {
    portfolio: function (msg) {
      paintStatus(true);
      paintAccount(msg);
      if (msg.positions) renderPositions(msg.positions);
    },
    error: function () { markStream(false); }
  });

  var lastBid = {};

  api.stream(boot.tick_stream, {
    tick: function (msg) {
      markStream(true);
      var symbols = msg.symbols || {};
      Object.keys(symbols).forEach(function (name) {
        var t = symbols[name];
        var cell = document.querySelector(
          'td[data-symbol="' + dom.cssEscape(name) + '"]');
        if (!cell || !cell.parentNode) return;
        var row = cell.parentNode.children;
        var bidCell = row[1], askCell = row[2];
        var digits = parseInt(bidCell.getAttribute("data-digits"), 10) || 5;

        var previous = lastBid[name];
        if (previous !== undefined && previous !== t.bid) {
          dom.replayClass(bidCell, t.bid > previous ? "up" : "down");
          dom.replayClass(askCell, t.bid > previous ? "up" : "down");
        }
        lastBid[name] = t.bid;

        bidCell.textContent = fmt.num(t.bid, digits);
        askCell.textContent = fmt.num(t.ask, digits);

        // Recomputed with the same pip size the server used. Inferring it from
        // the digit count is wrong on anything that is not a plain FX pair.
        var spreadCell = row[3];
        var pip = parseFloat(spreadCell.getAttribute("data-pip"));
        spreadCell.textContent = fmt.num(
          pip > 0 ? (t.ask - t.bid) / pip : NaN, 2);
      });
    },
    error: function () { markStream(false); }
  });
})();