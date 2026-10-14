/* frontend — pages/symbols.js
   ---------------------------------------------------------------------------
   Search-driven instrument browser.

   The full listing is 1.5 MB for this broker, so it is never fetched. Each
   keystroke queries /symbols/search, which the gateway answers from its symbol
   cache. Requests are debounced and the in-flight one is abandoned when a
   newer keystroke arrives, otherwise a slow early response can overwrite a
   fast later one and leave the list showing results for text the user has
   already deleted. */
(function () {
  "use strict";

  var boot = dom.bootstrap();
  var DEBOUNCE_MS = 220;

  var input = document.getElementById("q");
  var listNode = document.querySelector('[data-role="symbol-list"]');
  var countNode = document.querySelector('[data-role="result-count"]');
  var statusNode = document.querySelector('[data-role="search-status"]');
  var titleNode = document.querySelector('[data-role="detail-title"]');
  var subtitleNode = document.querySelector('[data-role="detail-subtitle"]');
  var detailNode = document.querySelector('[data-role="detail-body"]');

  var timer = null;
  var inFlight = null;
  var sequence = 0;

  /* ── Chart ──────────────────────────────────────────────────────────
     Loaded per symbol and per timeframe. The candle request is kept
     separate from the detail request because they have different failure
     modes: a symbol can resolve while its candles are unavailable, and the
     spec panel should still render in that case. */
  var canvas = document.querySelector('[data-role="chart"]');
  var chartEmpty = document.querySelector('[data-role="chart-empty"]');
  var chartStatus = document.querySelector('[data-role="chart-status"]');
  var timeframe = "M15";
  var chartBars = [];
  var currentSymbol = null;
  var chartToken = 0;

  var CANDLE_COUNTS = {
    M1: 300, M5: 400, M15: 400, M30: 400,
    H1: 500, H4: 500, D1: 500
  };

  function setChartEmpty(show, title, detail) {
    if (!chartEmpty) return;
    chartEmpty.hidden = !show;
    if (show) {
      chartEmpty.innerHTML = fmt.escapeHtml(title || "No data")
        + (detail ? "<span>" + fmt.escapeHtml(detail) + "</span>" : "");
    }
  }

  function paintChart() {
    if (!canvas || !window.chart) return;
    var result = window.chart.draw(canvas, chartBars, {
      height: 320,
      clockOffset: boot.clock_offset
    });
    if (!chartStatus) return;
    if (!result) {
      chartStatus.textContent = "—";
      return;
    }
    var first = chartBars[0];
    var change = first && first.close
      ? (result.last - first.close) / first.close * 100
      : null;
    chartStatus.textContent = chartBars.length + " bars · "
      + (change === null ? "" : fmt.signed(change, 2) + "% · ")
      + "high " + result.high + " · low " + result.low;
  }

  function loadChart(symbol) {
    if (!symbol) return;
    currentSymbol = symbol;
    var mine = ++chartToken;
    setChartEmpty(true, "Loading", symbol + " " + timeframe);
    if (chartStatus) chartStatus.textContent = "loading…";

    var count = CANDLE_COUNTS[timeframe] || 400;
    api.get("/candles/" + encodeURIComponent(symbol)
             + "?timeframe=" + timeframe + "&count=" + count)
      .then(function (result) {
        if (mine !== chartToken) return;              // superseded
        if (result.error) { setChartEmpty(true, "No data", result.error); return; }
        chartBars = result.candles || [];
        if (!chartBars.length) {
          setChartEmpty(true, "No candles", "the broker has none for this window");
          if (chartStatus) chartStatus.textContent = "0 bars";
          return;
        }
        setChartEmpty(false);
        paintChart();
      })
      .catch(function (err) {
        if (mine !== chartToken) return;
        setChartEmpty(true, "Could not load", err.message);
        if (chartStatus) chartStatus.textContent = "—";
      });
  }

  var tfGroup = document.querySelector('[data-role="timeframes"]');
  if (tfGroup) {
    tfGroup.addEventListener("click", function (event) {
      var button = event.target.closest("button[data-timeframe]");
      if (!button) return;
      dom.$$("button", tfGroup).forEach(function (b) {
        b.setAttribute("aria-pressed", "false");
      });
      button.setAttribute("aria-pressed", "true");
      timeframe = button.getAttribute("data-timeframe");
      if (currentSymbol) loadChart(currentSymbol);
    });
  }

  // The canvas is sized from its CSS box, so it must be redrawn when that
  // box changes. Debounced because a drag-resize fires continuously.
  var resizeTimer = null;
  global.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(paintChart, 120);
  });

  function status(text, kind) {
    if (!statusNode) return;
    statusNode.textContent = text || "";
    statusNode.className = "search-status" + (kind ? " " + kind : " muted");
  }

  function select(symbol, button) {
    dom.$$(".symbol-list button").forEach(function (b) {
      b.setAttribute("aria-selected", "false");
    });
    if (button) button.setAttribute("aria-selected", "true");

    if (titleNode) titleNode.textContent = symbol;
    if (subtitleNode) subtitleNode.textContent = "loading…";
    if (detailNode) {
      detailNode.innerHTML = '<div class="empty">Loading'
        + "<span>" + fmt.escapeHtml(symbol) + "</span></div>";
    }

    api.get("/symbol/" + encodeURIComponent(symbol))
      .then(function (info) { renderDetail(info); })
      .catch(function (err) {
        if (subtitleNode) subtitleNode.textContent = "unavailable";
        if (detailNode) {
          detailNode.innerHTML = '<div class="empty">Could not load'
            + "<span>" + fmt.escapeHtml(err.message) + "</span></div>";
        }
      });

    loadChart(symbol);
  }

  function group(title, pairs) {
    var rows = pairs.filter(function (p) {
      return p[1] !== null && p[1] !== undefined && p[1] !== "";
    }).map(function (p) {
      return "<dt>" + fmt.escapeHtml(p[0]) + "</dt><dd>"
        + fmt.escapeHtml(p[1]) + "</dd>";
    }).join("");
    if (!rows) return "";
    return "<section><h3>" + fmt.escapeHtml(title) + "</h3><dl>"
      + rows + "</dl></section>";
  }

  function renderDetail(info) {
    var d = info._derived || {};
    var lot = d.lot_info || {};
    var rules = d.order_rules || {};
    var filling = d.filling || {};

    if (subtitleNode) {
      subtitleNode.textContent = info.description || info.path || "";
    }
    if (!detailNode) return;

    detailNode.innerHTML = '<div class="detail-grid">'
      + group("Quote", [
          ["Bid", fmt.num(info.bid, info.digits)],
          ["Ask", fmt.num(info.ask, info.digits)],
          ["Last", fmt.num(info.last, info.digits)],
          ["Spread", info.spread !== undefined ? info.spread + " pts" : ""],
          ["Digits", info.digits],
          ["Point", info.point]
        ])
      + group("Derived", [
          ["Pip size", d.pip_size],
          ["Points per pip", d.points_per_pip],
          ["Pip decimals", d.pip_decimals],
          ["Pip value / lot", d.pip_value_per_lot],
          ["Trade mode", info._trade_mode]
        ])
      + group("Lot rules", [
          ["Contract size", lot.contract_size],
          ["Min lot", lot.min_lot],
          ["Max lot", lot.max_lot],
          ["Lot step", lot.lot_step]
        ])
      + group("Order rules", [
          ["Min stop distance", rules.min_stop_distance_points
            ? rules.min_stop_distance_points + " pts ("
              + rules.min_stop_distance_pips + " pips)" : ""],
          ["Freeze level", info.trade_freeze_level],
          ["Stops level", info.trade_stops_level],
          ["Filling modes", (filling.supported || []).join(", ")],
          ["Filling flag", filling.flag]
        ])
      + group("Costs", [
          ["Swap long", info.swap_long],
          ["Swap short", info.swap_short],
          ["Initial margin", info.margin_initial],
          ["Maintenance margin", info.margin_maintenance],
          ["Tick value", info.trade_tick_value],
          ["Tick size", info.trade_tick_size]
        ])
      + group("Classification", [
          ["Path", info.path],
          ["Exchange", info.exchange],
          ["Currency base", info.currency_base],
          ["Currency profit", info.currency_profit],
          ["ISIN", info.isin]
        ])
      + "</div>";
  }

  function renderList(query, symbols) {
    if (!listNode) return;
    dom.clear(listNode);
    if (!symbols.length) {
      listNode.innerHTML = '<div class="empty">Nothing matches'
        + "<span>" + fmt.escapeHtml(query) + "</span></div>";
      return;
    }
    var wrap = document.createElement("div");
    wrap.className = "symbol-list";
    symbols.forEach(function (s) {
      var button = document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-selected", "false");
      var name = document.createElement("span");
      name.className = "name";
      name.textContent = s.name;
      var desc = document.createElement("span");
      desc.className = "desc";
      desc.textContent = s.description || s.path || "";
      button.appendChild(name);
      button.appendChild(desc);
      button.addEventListener("click", function () { select(s.name, button); });
      wrap.appendChild(button);
    });
    listNode.appendChild(wrap);
  }

  function search(query) {
    if (inFlight) inFlight = null;
    var mine = ++sequence;
    status("searching…", "busy");

    var request = api.get("/symbols/search?q=" + encodeURIComponent(query))
      .catch(function (err) {
        status(err.message, "error");
        return null;
      });

    inFlight = request;
    request.then(function (result) {
      // A newer keystroke started while this was in flight: drop the answer.
      if (mine !== sequence) return;
      if (!result) return;
      var symbols = result.symbols || [];
      if (countNode) countNode.textContent = symbols.length + " match"
        + (symbols.length === 1 ? "" : "es");
      renderList(query, symbols);
      status("");
    });
  }

  if (input) {
    input.addEventListener("input", function () {
      var query = input.value.trim();
      clearTimeout(timer);
      if (query.length < 1) {
        sequence++;
        if (countNode) countNode.textContent = "—";
        if (listNode) {
          listNode.innerHTML = '<div class="empty">Type to search'
            + "<span>the list is fetched on demand</span></div>";
        }
        status("");
        return;
      }
      timer = setTimeout(function () { search(query); }, DEBOUNCE_MS);
    });
  }

  // Open on something rather than an empty panel.
  if (boot.default_symbol) {
    if (input) input.value = boot.default_symbol;
    search(boot.default_symbol);
    // Draw the first chart once the list has rendered, so the panel is not
    // empty on arrival. `select` is called directly rather than via a click
    // because there may be no button yet when this runs.
    setTimeout(function () {
      var first = document.querySelector(".symbol-list button");
      select(boot.default_symbol, first);
    }, 350);
  }
})();