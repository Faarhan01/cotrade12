/* frontend — pages/research.js
   ---------------------------------------------------------------------------
   A client over /research/*. It computes nothing: every t-statistic, baseline
   and verdict here was produced by the backend, which is the only layer that
   has both the data and the statistics.

   The rendering leans hard on showing what was measured next to what it was
   compared against. A pattern scan that shows only the impressive column is
   how a drifting sample gets mistaken for an edge. */
(function () {
  "use strict";

  var boot = dom.bootstrap();
  var clockOffset = Number(boot.clock_offset) || 0;

  function status(node, text, kind) {
    var el = document.querySelector('[data-role="' + node + '"]');
    if (!el) return;
    el.textContent = text || "";
    el.className = "search-status" + (kind ? " " + kind : " muted");
  }

  function emptyState(title, detail) {
    return '<div class="empty">' + fmt.escapeHtml(title)
         + "<span>" + fmt.escapeHtml(detail || "") + "</span></div>";
  }

  /* ── Pattern scan ──────────────────────────────────────────────── */

  var follow = document.querySelector('[data-role="scan-body"]');
  var summary = document.querySelector('[data-role="scan-summary"]');
  var meta = document.querySelector('[data-role="scan-meta"]');

  function scanRow(name, v) {
    var cls = "";
    if (v.trade_direction) cls = ' class="is-tradable"';
    else if (v.cost_marginal) cls = ' class="is-marginal"';
    var flag = v.trade_direction
      ? '<span class="tag accent">' + fmt.escapeHtml(v.trade_direction) + "</span>"
      : (v.cost_marginal ? '<span class="tag warn">too small</span>' : "");
    return "<tr" + cls + ">"
      + '<td class="sym">' + fmt.escapeHtml(name) + "</td>"
      + '<td class="num">' + fmt.num(v.n, 0) + "</td>"
      + '<td class="num">' + fmt.num(v.hit_rate, 1) + "%</td>"
      + '<td class="num">' + fmt.num(v.mean_move_pct, 5) + "%</td>"
      + '<td class="num ' + fmt.tone(v.mean_edge_pct) + '">'
      + fmt.signed(v.mean_edge_pct, 5) + "%</td>"
      + '<td class="num ' + fmt.tone(v.mean_edge_pct_net) + '">'
      + fmt.signed(v.mean_edge_pct_net, 5) + "%</td>"
      + '<td class="num">' + fmt.num(v.t_statistic_edge, 2) + "</td>"
      + '<td class="num">' + fmt.num(v.t_statistic_net, 2) + "</td>"
      + '<td class="verdict ' + fmt.escapeHtml(v.verdict) + '">'
      + fmt.escapeHtml(v.verdict) + "</td>"
      + "<td>" + flag + "</td>"
      + "</tr>";
  }

  function renderScan(result) {
    var rows = Object.keys(result.follow_through || {})
      .filter(function (k) {
        return result.follow_through[k].t_statistic_edge !== null
            && result.follow_through[k].t_statistic_edge !== undefined;
      })
      .sort(function (a, b) {
        return Math.abs(result.follow_through[b].t_statistic_edge)
             - Math.abs(result.follow_through[a].t_statistic_edge);
      });

    if (meta) {
      meta.textContent = result.symbol + " " + result.timeframe
        + " · " + result.bars + " bars · cost " + result.spread_pct + "%";
    }

    if (summary) {
      summary.innerHTML = '<div class="form-pad"><dl class="kv">'
        + "<dt>matches</dt><dd>" + result.matches + " ("
        + result.density_per_100_bars + " per 100 bars)</dd>"
        + "<dt>busiest pattern</dt><dd>"
        + result.busiest_pattern_per_100_bars + "% of bars</dd>"
        + "<dt>real signal</dt><dd>"
        + (result.significant_after_correction.length
            ? result.significant_after_correction.join(", ") : "none") + "</dd>"
        + "<dt>too small to trade</dt><dd>"
        + (result.cost_marginal.length ? result.cost_marginal.join(", ") : "none")
        + "</dd>"
        + "<dt>tradeable</dt><dd>"
        + (result.tradable_as_signalled.length
            ? result.tradable_as_signalled.join(", ") : "none") + " as signalled / "
        + (result.tradable_inverted.length
            ? result.tradable_inverted.join(", ") : "none") + " inverted</dd>"
        + "</dl></div>";
    }

    if (!follow) return;
    if (!rows.length) {
      follow.innerHTML = emptyState("No pattern had enough occurrences",
        "scan a longer window");
      return;
    }

    var html = '<table class="grid"><thead><tr><th>Pattern</th><th>n</th>'
      + "<th>hit%</th><th>raw%</th><th>edge%</th><th>edge net%</th>"
      + "<th>t edge</th><th>t net</th><th>verdict</th><th>trade</th>"
      + "</tr></thead><tbody>";
    rows.forEach(function (name) {
      html += scanRow(name, result.follow_through[name]);
    });
    html += "</tbody></table>";

    var baseline = result.follow_through[rows[0]].baseline_pct;
    html += '<div class="form-pad"><p class="muted">'
      + "The market moved " + fmt.signed(baseline, 5)
      + "% on average over this horizon from any bar. "
      + "raw% mostly measures that drift; edge% removes it and is what the "
      + "verdict is judged on. edge net% then charges the round-trip spread."
      + "</p></div>";

    follow.innerHTML = html;
  }

  var scanForm = document.querySelector('[data-form="scan"]');
  if (scanForm) {
    scanForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var button = scanForm.querySelector("button[type=submit]");
      var payload = {
        symbol: scanForm.elements.symbol.value.trim(),
        timeframe: scanForm.elements.timeframe.value,
        count: Number(scanForm.elements.count.value) || 2000
      };
      if (button) button.classList.add("spinning");
      status("scan-status", "scanning " + payload.symbol + "…", "busy");

      api.post("/research/patterns/scan", payload)
        .then(function (result) {
          status("scan-status", "");
          if (result.error) {
            status("scan-status", result.error, "error");
            return;
          }
          renderScan(result);
        })
        .catch(function (err) {
          status("scan-status", err.message, "error");
        })
        .then(function () {
          if (button) button.classList.remove("spinning");
        });
    });
  }

  /* ── Strategy ─────────────────────────────────────────────────── */

  var specField = document.getElementById("strategy-json");
  var output = document.querySelector('[data-role="strategy-output"]');

  function showResult(label, payload, verdict) {
    if (!output) return;
    var head = '<div class="result-pad"><dl class="kv">'
      + "<dt>verdict</dt><dd class=\"verdict " + fmt.escapeHtml(verdict || "")
      + '">' + fmt.escapeHtml(verdict || "—") + "</dd>"
      + (payload.interpretation
          ? "<dt>meaning</dt><dd>" + fmt.escapeHtml(payload.interpretation)
            + "</dd>" : "")
      + (payload.split_check
          ? "<dt>train / test consistent</dt><dd>"
            + payload.split_check.consistent + "</dd>"
            + "<dt>test t</dt><dd>" + fmt.num(payload.split_check.test_t, 2)
            + "</dd>" : "")
      + "</dl></div>";
    var raw = '<pre class="result result-pad">'
      + fmt.escapeHtml(JSON.stringify(payload, null, 2)) + "</pre>";
    output.innerHTML = head + raw;
  }

  function showError(payload) {
    if (!output) return;
    var problems = (payload && payload.problems) || [];
    var list = problems.length
      ? '<div class="form-pad"><ul class="muted">'
        + problems.map(function (p) { return "<li>" + fmt.escapeHtml(p) + "</li>"; }).join("")
        + "</ul></div>"
      : "";
    output.innerHTML = list + '<pre class="result result-pad">'
      + fmt.escapeHtml(JSON.stringify(payload, null, 2)) + "</pre>";
  }

  function parseSpec() {
    try {
      return { value: JSON.parse(specField.value) };
    } catch (err) {
      return { error: "That is not valid JSON: " + err.message };
    }
  }

  var strategyForm = document.querySelector('[data-form="strategy"]');
  if (strategyForm) {
    strategyForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var parsed = parseSpec();
      if (parsed.error) {
        status("strategy-status", parsed.error, "error");
        return;
      }
      status("strategy-status", "checking…", "busy");
      var payload = parsed.value;
      var isString = typeof payload === "string";

      api.post("/research/strategy/validate",
               isString ? { name: payload } : payload)
        .then(function (result) {
          status("strategy-status", "");
          if (!result.valid) { showError(result); return; }
          // Valid, so run it. Backtesting is the only thing that says
          // anything about whether the definition is any good.
          return api.post("/research/backtest", {
            strategy: isString ? payload : result.strategy,
            symbol: (boot.default_symbol || "EURUSD"),
            timeframe: "M15",
            count: 2000
          });
        })
        .then(function (result) {
          if (!result) return;
          if (result.error || result.valid === false) { showError(result); return; }
          showResult("backtest", result, result.verdict);
        })
        .catch(function (err) {
          status("strategy-status", err.message, "error");
        });
    });
  }

  var loadButton = document.querySelector('[data-action="load-library"]');
  if (loadButton && specField) {
    loadButton.addEventListener("click", function () {
      loadButton.classList.add("spinning");
      api.get("/research/library")
        .then(function (result) {
          var strategies = result.strategies || [];
          if (!strategies.length) throw new Error("no starter strategies");
          specField.value = JSON.stringify(strategies[0], null, 2);
          status("strategy-status",
                 "Loaded " + (strategies[0].name || "a starter") + ". "
                 + strategies.length + " available.", "");
        })
        .catch(function (err) {
          status("strategy-status", err.message, "error");
        })
        .then(function () { loadButton.classList.remove("spinning"); });
    });
  }
})();