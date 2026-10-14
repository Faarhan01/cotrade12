/* frontend — lib/format.js
   ---------------------------------------------------------------------------
   Formatting helpers shared by every page.

   Formatting lives here rather than inline because the server renders the
   first paint and the browser renders every update after it. If the two
   disagree, numbers visibly change shape the moment the first SSE frame
   arrives, which reads as a glitch.
*/
(function (global) {
  "use strict";

  var DASH = "—";

  function num(value, digits) {
    if (value === null || value === undefined || value === "") return DASH;
    var n = Number(value);
    if (!isFinite(n)) return DASH;
    return n.toLocaleString(undefined, {
      minimumFractionDigits: digits === undefined ? 2 : digits,
      maximumFractionDigits: digits === undefined ? 2 : digits
    });
  }

  function signed(value, digits) {
    if (value === null || value === undefined) return DASH;
    var n = Number(value);
    if (!isFinite(n)) return DASH;
    return n.toLocaleString(undefined, {
      minimumFractionDigits: digits === undefined ? 2 : digits,
      maximumFractionDigits: digits === undefined ? 2 : digits,
      signDisplay: "exceptZero"
    });
  }

  function tone(value) {
    var n = Number(value);
    if (!isFinite(n) || n === 0) return "flat";
    return n > 0 ? "pos" : "neg";
  }

  /* MT5 timestamps are Unix epoch values. They are rendered on the *broker's*
     clock - UTC plus the offset the gateway publishes - so that a deal time and
     the header clock on the same page cannot disagree. */
  function brokerTime(epochSeconds, clockOffset) {
    if (!epochSeconds) return DASH;
    var ms = epochSeconds > 1e11 ? epochSeconds : epochSeconds * 1000;
    var d = new Date(ms + (Number(clockOffset) || 0) * 1000);
    return d.toISOString().slice(0, 19).replace("T", " ");
  }

  function clockOnly(clockOffset) {
    return brokerTime(Date.now() / 1000, clockOffset).slice(11);
  }

  function shortDateTime(epochSeconds, clockOffset) {
    var full = brokerTime(epochSeconds, clockOffset);
    return full === DASH ? DASH : full.slice(8, 19);
  }

  /* Spread in pips. `spread` from MT5 is a count of points, and point and
     pip are both prices, so this needs all three. The pip size is supplied by
     the server because it varies per instrument and is not derivable from the
     digit count - that inference was tried and was wrong on everything except
     plain FX pairs. */
  function spreadPips(points, point, pipSize) {
    if (points === null || points === undefined) return DASH;
    var p = Number(pipSize);
    if (!isFinite(p) || p <= 0) return DASH;
    return (Number(points) * Number(point)) / p;
  }

  function escapeHtml(text) {
    return String(text === null || text === undefined ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  global.fmt = {
    DASH: DASH,
    num: num,
    signed: signed,
    tone: tone,
    brokerTime: brokerTime,
    clockOnly: clockOnly,
    shortDateTime: shortDateTime,
    spreadPips: spreadPips,
    escapeHtml: escapeHtml
  };
})(window);