/* frontend — lib/chart.js
   ---------------------------------------------------------------------------
   Candlestick and line charts on a plain <canvas>. No charting library: one is
   roughly 300 KB and pulls a dependency tree, for drawing rectangles and lines
   that take about 150 lines here. The site must also work offline, and a CDN
   chart would break exactly when the network does.

   Two deliberate choices:

   * High-DPI aware. Without multiplying by devicePixelRatio the chart is
     blurry on any modern display, which is most of them.
   * The price axis is drawn from the data's own high/low rather than from
     nice round numbers. On an instrument quoted to 5 decimals there are no
     round numbers, and padding the range distorts how big a real move looks.

   Candle bodies are filled green or red; wicks are always drawn, because a
   candle whose open equals its close still has a range that mattered. */
(function (global) {
  "use strict";

  var UP = "#4dd4ac";
  var DOWN = "#ff6b6b";
  var GRID = "rgba(127,127,127,0.16)";
  var AXIS_TEXT = "#7d8896";

  function niceStep(range, targetLines) {
    if (range <= 0) return 1;
    var rough = range / (targetLines || 5);
    var mag = Math.pow(10, Math.floor(Math.log10(rough)));
    var norm = rough / mag;
    var step = norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1;
    return step * mag;
  }

  /* Format a price with just enough decimals to separate adjacent grid lines.
     Fixed-decimal formatting on a 5-digit quote produces labels that all look
     identical. */
  function priceLabel(value, step) {
    var decimals = Math.max(0, Math.min(8, Math.ceil(-Math.log10(step)) + 1));
    return value.toFixed(decimals);
  }

  function draw(canvas, candles, opts) {
    if (!canvas || !canvas.getContext) return null;
    opts = opts || {};
    var ctx = canvas.getContext("2d");
    if (!ctx) return null;

    var style = global.getComputedStyle ? global.getComputedStyle(document.documentElement) : null;
    var accent = (style && style.getPropertyValue("--accent").trim()) || "#58a6ff";

    var dpr = global.devicePixelRatio || 1;
    var cssW = canvas.clientWidth || 600;
    var cssH = opts.height || 320;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    canvas.style.height = cssH + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    if (!candles || !candles.length) return null;

    var padL = 8, padR = 62, padT = 10, padB = 22;
    var plotW = Math.max(1, cssW - padL - padR);
    var plotH = Math.max(1, cssH - padT - padB);

    var hi = -Infinity, lo = Infinity;
    candles.forEach(function (c) {
      if (c.high > hi) hi = c.high;
      if (c.low < lo) lo = c.low;
    });
    var span = hi - lo;
    if (!(span > 0)) { span = Math.abs(hi) || 1; lo = hi - span / 2; hi = hi + span / 2; span = hi - lo; }

    var pad = span * 0.06;
    hi += pad; lo -= pad; span = hi - lo;

    var yOf = function (p) { return padT + (hi - p) / span * plotH; };
    var xOf = function (i) {
      return padL + (candles.length === 1 ? plotW / 2 : i / (candles.length - 1) * plotW);
    };

    // ── grid and price axis
    var step = niceStep(span, 5);
    ctx.strokeStyle = GRID;
    ctx.fillStyle = AXIS_TEXT;
    ctx.lineWidth = 1;
    ctx.font = "10px ui-monospace, Menlo, Consolas, monospace";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    for (var v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      var y = Math.round(yOf(v)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + plotW, y);
      ctx.stroke();
      ctx.fillText(priceLabel(v, step), padL + plotW + 6, y);
    }

    // ── time axis: first, middle and last only, so labels never collide
    // Rendered on the broker's clock, not UTC. The gateway publishes the
    // offset; without it the chart disagrees with every timestamp elsewhere
    // on the page by however far the broker's server runs ahead.
    var offsetMs = (Number(opts.clockOffset) || 0) * 1000;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    var marks = candles.length > 2
      ? [0, Math.floor(candles.length / 2), candles.length - 1]
      : [0];
    marks.forEach(function (i) {
      var d = new Date(candles[i].time * 1000 + offsetMs);
      ctx.fillText(String(d.getUTCHours()).padStart(2, "0") + ":"
                 + String(d.getUTCMinutes()).padStart(2, "0"),
                 xOf(i), padT + plotH + 5);
    });

    // ── candles
    var slot = candles.length > 1 ? plotW / (candles.length - 1) : plotW;
    var body = Math.max(1, Math.min(14, slot * 0.68));
    var wick = Math.max(1, Math.min(2, body * 0.18));

    ctx.save();
    ctx.beginPath();
    ctx.rect(padL, padT, plotW, plotH);
    ctx.clip();

    candles.forEach(function (c, i) {
      var up = c.close >= c.open;
      var colour = up ? UP : DOWN;
      var x = xOf(i);
      ctx.strokeStyle = colour;
      ctx.fillStyle = colour;
      ctx.lineWidth = wick;
      ctx.beginPath();
      ctx.moveTo(x, yOf(c.high));
      ctx.lineTo(x, yOf(c.low));
      ctx.stroke();
      var yo = yOf(c.open), yc = yOf(c.close);
      var top = Math.min(yo, yc);
      var h = Math.max(1, Math.abs(yc - yo));
      // A doji would be zero-height and invisible; the 1px floor keeps it
      // visible as the single flat bar it actually is.
      ctx.fillRect(x - body / 2, top, body, h);
    });
    ctx.restore();

    // ── last price marker
    var last = candles[candles.length - 1];
    var lastY = Math.round(yOf(last.close)) + 0.5;
    var lastUp = last.close >= candles[0].close;
    ctx.strokeStyle = lastUp ? UP : DOWN;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(padL, lastY);
    ctx.lineTo(padL + plotW, lastY);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = lastUp ? UP : DOWN;
    ctx.fillRect(padL + plotW + 2, lastY - 7, padR - 4, 14);
    ctx.fillStyle = "#06121f";
    ctx.font = "10px ui-monospace, Menlo, Consolas, monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(priceLabel(last.close, step), padL + plotW + 2 + (padR - 4) / 2, lastY);

    return { high: hi, low: lo, last: last.close };
  }

  global.chart = { draw: draw };
})(window);