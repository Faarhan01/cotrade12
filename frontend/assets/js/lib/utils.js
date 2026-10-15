/* frontend — lib/utils.js
   ---------------------------------------------------------------------------
   Shared utilities: debounce, throttle, DOM helpers, API client, constants.

   This module consolidates common utilities used across all pages to avoid
   duplication and ensure consistent behavior. */
(function (global) {
  "use strict";

  // ─── Constants ────────────────────────────────────────────────────────────

  /** API endpoint paths */
  global.API = {
    // Market data
    SYMBOLS: "/symbols",
    SYMBOL_SEARCH: "/symbols/search",
    SYMBOL_DETAIL: "/symbol/",
    SYMBOL_SELECT: "/symbol/",
    TICK: "/tick/",
    TICKS: "/ticks",
    TICKS_HISTORY: "/ticks/history",
    CANDLES: "/candles/",
    MARKET_BOOK: "/marketbook",
    MARKET_BOOK_SUBSCRIBE: "/marketbook/",
    MARKET_BOOK_UNSUBSCRIBE: "/marketbook/",

    // Account
    ACCOUNT: "/account",
    TERMINAL: "/terminal",
    TOTALS: "/totals",
    POSITIONS: "/positions",
    ORDERS: "/orders",
    HISTORY_DEALS: "/history/deals",
    HISTORY_ORDERS: "/history/orders",
    HISTORY_TOTALS: "/history/totals",
    HISTORY_SUMMARY: "/history/summary",

    // Trading
    ORDER_CHECK: "/order/check",
    ORDER: "/order",
    BUY: "/buy",
    SELL: "/sell",
    CLOSE: "/close",
    CLOSE_ALL: "/close-all",
    MODIFY: "/modify",
    CANCEL: "/cancel",
    CALC_SIZE: "/calc/size",
    CALC_PROFIT: "/calc/profit",
    CALC_MARGIN: "/calc/margin",

    // Health & Discovery
    HEALTH: "/health",
    ROUTES: "/routes",
    ENUMS: "/enums",
    STREAMS: "/streams",
    CONNECT: "/connect",
    DISCONNECT: "/disconnect",
    LOGIN: "/login",
    LAST_ERROR: "/last-error",
    SYMBOL_CACHE_CLEAR: "/symbol-cache/clear",

    // Research
    RESEARCH: "/research",
    RESEARCH_CATALOGUE: "/research/catalogue",
    RESEARCH_INDICATORS: "/research/indicators",
    RESEARCH_PATTERNS: "/research/patterns",
    RESEARCH_STRATEGIES: "/research/strategies",
    RESEARCH_LIBRARY: "/research/library",
    RESEARCH_STORED: "/research/stored",
    RESEARCH_STRATEGY: "/research/strategy/",
    RESEARCH_VALIDATE: "/research/strategy/validate",
    RESEARCH_SAVE: "/research/strategy/save",
    RESEARCH_BACKTEST: "/research/backtest",
    RESEARCH_SWEEP: "/research/sweep",
    RESEARCH_PATTERN_SCAN: "/research/patterns/scan",
    RESEARCH_INDICATOR: "/research/indicator",
    RESEARCH_PATTERN_FREQ: "/research/patterns/frequency",
    RESEARCH_BARS_RANGE: "/research/bars/range",
    RESEARCH_REPORTS_BEST: "/research/reports/best",
    RESEARCH_HITS_CONTEXT: "/research/hits/context",
    RESEARCH_STRATEGY_HISTORY: "/research/strategy/",
    RESEARCH_STRATEGY_VERSION: "/research/strategy/",
    RESEARCH_STRATEGY_CLONE: "/research/strategy/",
    RESEARCH_STRATEGY_EXPORT: "/research/strategy/export",
    RESEARCH_STRATEGY_IMPORT: "/research/strategy/import",
    RESEARCH_STRATEGY_OPTIMIZE: "/research/strategy/",
    RESEARCH_PATTERNS_COOCCURRENCE: "/research/patterns/cooccurrence",
    RESEARCH_REPORTS_BEST: "/research/reports/best",
    RESEARCH_HITS_CONTEXT: "/research/hits/context",

    // Database
    DB_STATS: "/db/stats",
    DB_REPORTS: "/db/reports",
    DB_INTEGRITY: "/db/integrity",
    DB_VACUUM: "/db/vacuum",
    DB_SESSIONS: "/db/sessions",

    // Bot
    BOT_STATUS: "/bot/status",
    BOT_STRATEGIES: "/bot/strategies",
    BOT_SESSIONS: "/bot/sessions",
    BOT_SESSION: "/bot/sessions/",
    BOT_SESSION_STOP: "/bot/sessions/",
    BOT_SESSION_LOGS: "/bot/sessions/",
    BOT_SESSION_LOG: "/bot/sessions/",
    BOT_SESSION_UPDATE: "/bot/sessions/",

    // Streams
    STREAM_TICKS: "/stream/ticks",
    STREAM_MARKETBOOK: "/stream/marketbook",
    STREAM_PORTFOLIO: "/stream/portfolio",
  };

  /** CSS Selectors for common elements */
  global.SELECTORS = {
    // Shell
    ROLE: '[data-role="%s"]',
    ROLE_STATUS: '[data-role="status"]',
    ROLE_CLOCK: '[data-role="clock"]',
    ROLE_ACCOUNT: '[data-role="account"]',
    ROLE_SERVER: '[data-role="server"]',
    ROLE_MODE: '[data-role="mode"]',
    ROLE_PACKAGE: '[data-role="package"]',
    ROLE_TERMINAL: '[data-role="terminal"]',
    ROLE_OFFSET: '[data-role="offset"]',
    ROLE_PERMISSIONS: '[data-role="permissions"]',

    // Forms
    FORM_SCAN: '[data-form="scan"]',
    FORM_STRATEGY: '[data-form="strategy"]',
    INPUT_SYMBOL: '#q',
    INPUT_SCAN_SYMBOL: '#scan-symbol',
    INPUT_STRATEGY_JSON: '#strategy-json',

    // Actions
    ACTION_LOAD_LIBRARY: '[data-action="load-library"]',
    ACTION_VACUUM: '[data-action="db-vacuum"]',
    ACTION_REFRESH: '[data-action="refresh-reports"]',

    // Containers
    ROLE_POSITIONS_BODY: '[data-role="positions-body"]',
    ROLE_ORDERS_BODY: '[data-role="orders-body"]',
    ROLE_DEALS_BODY: '[data-role="deals-body"]',
    ROLE_WATCHLIST_BODY: '[data-role="watchlist-body"]',
    ROLE_SCAN_BODY: '[data-role="scan-body"]',
    ROLE_SCAN_SUMMARY: '[data-role="scan-summary"]',
    ROLE_SCAN_META: '[data-role="scan-meta"]',
    ROLE_STRATEGY_OUTPUT: '[data-role="strategy-output"]',
    ROLE_SYMBOL_LIST: '[data-role="symbol-list"]',
    ROLE_DETAIL_BODY: '[data-role="detail-body"]',
    ROLE_CHART: '[data-role="chart"]',
    ROLE_CHART_EMPTY: '[data-role="chart-empty"]',
    ROLE_REPORTS_BODY: '[data-role="reports-body"]',
    ROLE_STRATEGIES_BODY: '[data-role="strategies-body"]',
    ROLE_DB_STATS_ROW: '[data-role="db-stats-row"]',
    ROLE_VACUUM_STATUS: '[data-role="vacuum-status"]',
  };

  /** HTTP Status codes */
  global.HTTP_STATUS = {
    OK: 200,
    BAD_REQUEST: 400,
    UNAUTHORIZED: 401,
    NOT_FOUND: 404,
    CONFLICT: 409,
    SERVICE_UNAVAILABLE: 503,
  };

  /** Verdict CSS classes */
  global.VERDICT_CLASSES = {
    noise: "badge-bad",
    fragile: "badge-warn",
    promising: "badge-good",
    strong: "badge-good",
    no_trades: "badge-neutral",
    insufficient: "badge-neutral",
    unresolvable: "badge-warn",
    untested: "badge-neutral",
  };

  // ─── Utility Functions ────────────────────────────────────────────────

  /**
   * Debounce function - delays execution until after wait ms since last call
   * @param {Function} fn - Function to debounce
   * @param {number} wait - Milliseconds to wait
   * @param {boolean} immediate - Execute on leading edge
   * @returns {Function} Debounced function
   */
  function debounce(fn, wait, immediate) {
    var timeout = null;
    return function () {
      var context = this;
      var args = arguments;
      var later = function () {
        timeout = null;
        if (!immediate) fn.apply(context, args);
      };
      var callNow = immediate && !timeout;
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
      if (callNow) fn.apply(context, args);
    };
  }

  /**
   * Throttle function - limits execution to once per wait period
   * @param {Function} fn - Function to throttle
   * @param {number} wait - Minimum milliseconds between calls
   * @returns {Function} Throttled function
   */
  function throttle(fn, wait) {
    var lastCall = 0;
    return function () {
      var now = Date.now();
      if (now - lastCall >= wait) {
        lastCall = now;
        return fn.apply(this, arguments);
      }
    };
  }

  /**
   * Safely query a single element
   * @param {string} selector - CSS selector
   * @param {Element} [scope=document] - Scope to search within
   * @returns {Element|null}
   */
  function $(selector, scope) {
    return (scope || document).querySelector(selector);
  }

  /**
   * Safely query all matching elements
   * @param {string} selector - CSS selector
   * @param {Element} [scope=document] - Scope to search within
   * @returns {Element[]}
   */
  function $$(selector, scope) {
    return Array.prototype.slice.call((scope || document).querySelectorAll(selector));
  }

  /**
   * Create an element with attributes and children
   * @param {string} tag - Tag name
   * @param {Object} [attrs={}] - Attributes to set
   * @param {Array|Node|string} [children=[]] - Child nodes
   * @returns {Element}
   */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === "class") node.className = attrs[key];
      else if (key === "text") node.textContent = attrs[key];
      else if (key === "html") node.innerHTML = attrs[key];
      else if (attrs[key] !== null && attrs[key] !== undefined) {
        node.setAttribute(key, attrs[key]);
      }
    });
    (children || []).forEach(function (child) {
      node.appendChild(typeof child === "string"
        ? document.createTextNode(child) : child);
    });
    return node;
  }

  /**
   * Clear all children from a node
   * @param {Element} node
   */
  function clear(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
  }

  /**
   * Format a selector for data-role attribute
   * @param {string} role - Role name
   * @returns {string}
   */
  function roleSelector(role) {
    return '[data-role="' + role + '"]';
  }

  /**
   * Get element by data-role
   * @param {string} role - Role name
   * @param {Element} [scope=document] - Scope to search within
   * @returns {Element|null}
   */
  function byRole(role, scope) {
    return $(roleSelector(role), scope);
  }

  /**
   * Escape HTML special characters
   * @param {string} text - Text to escape
   * @returns {string}
   */
  function escapeHtml(text) {
    return String(text === null || text === undefined ? "" : text)
      .replace(/&/g, "&")
      .replace(/</g, "<")
      .replace(/>/g, ">")
      .replace(/"/g, """)
      .replace(/'/g, "'");
  }

  /**
   * Re-trigger a CSS animation by removing and re-adding class
   * @param {Element} node - Element to animate
   * @param {string} className - Class to add (e.g., "up" or "down")
   */
  function replayClass(node, className) {
    if (!node) return;
    node.classList.remove("up", "down");
    // Force reflow
    void node.offsetWidth;
    node.classList.add(className);
  }

  /**
   * Set text content if different
   * @param {Element} node
   * @param {string} text
   */
  function setText(node, text) {
    if (node && node.textContent !== text) node.textContent = text;
  }

  /**
   * Parse JSON safely
   * @param {string} text - JSON string
   * @returns {Object|null} Parsed object or null
   */
  function parseJSON(text) {
    try {
      return JSON.parse(text);
    } catch (e) {
      return null;
    }
  }

  /**
   * Deep clone an object
   * @param {*} obj
   * @returns {*}
   */
  function clone(obj) {
    return JSON.parse(JSON.stringify(obj));
  }

  /**
   * Generate unique ID
   * @returns {string}
   */
  function uniqueId() {
    return Math.random().toString(36).substr(2, 9);
  }

  /**
   * Format number with locale-aware formatting
   * @param {number} value
   * @param {number} [decimals=2]
   * @returns {string}
   */
  function formatNumber(value, decimals) {
    if (value === null || value === undefined || value === "") return "\u2014";
    var n = Number(value);
    if (!isFinite(n)) return "\u2014";
    return n.toLocaleString(undefined, {
      minimumFractionDigits: decimals === undefined ? 2 : decimals,
      maximumFractionDigits: decimals === undefined ? 2 : decimals,
    });
  }

  /**
   * Format signed number with + sign
   * @param {number} value
   * @param {number} [decimals=2]
   * @returns {string}
   */
  function formatSigned(value, decimals) {
    if (value === null || value === undefined) return "\u2014";
    var n = Number(value);
    if (!isFinite(n)) return "\u2014";
    return n.toLocaleString(undefined, {
      minimumFractionDigits: decimals === undefined ? 2 : decimals,
      maximumFractionDigits: decimals === undefined ? 2 : decimals,
      signDisplay: "exceptZero",
    });
  }

  /**
   * Get tone class for value (pos/neg/flat)
   * @param {number} value
   * @returns {string}
   */
  function tone(value) {
    var n = Number(value);
    if (!isFinite(n) || n === 0) return "flat";
    return n > 0 ? "pos" : "neg";
  }

  /**
   * Create a promise that resolves after ms
   * @param {number} ms
   * @returns {Promise}
   */
  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  /**
   * Retry a promise-returning function with exponential backoff
   * @param {Function} fn - Function returning promise
   * @param {Object} [options={}] - Options
   * @param {number} [options.retries=3] - Max retries
   * @param {number} [options.baseDelay=1000] - Initial delay ms
   * @param {number} [options.maxDelay=10000] - Max delay ms
   * @param {Function} [options.shouldRetry] - Function(error) => boolean
   * @returns {Promise}
   */
  function retry(fn, options) {
    options = options || {};
    var retries = options.retries || 3;
    var baseDelay = options.baseDelay || 1000;
    var maxDelay = options.maxDelay || 10000;
    var shouldRetry = options.shouldRetry || function () { return true; };

    return fn().catch(function (err) {
      if (retries <= 0 || !shouldRetry(err)) throw err;
      var delay = Math.min(baseDelay * Math.pow(2, 3 - retries), maxDelay);
      return sleep(delay).then(function () {
        return retry(fn, Object.assign({}, options, { retries: retries - 1 }));
      });
    });
  }

  /**
   * Create a promise that resolves after ms
   * @param {number} ms
   * @returns {Promise}
   */
  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  /**
   * Format timestamp in broker time
   * @param {number} epochSeconds - Unix timestamp
   * @param {number} clockOffset - Broker clock offset in seconds
   * @returns {string}
   */
  function brokerTime(epochSeconds, clockOffset) {
    if (!epochSeconds) return "\u2014";
    var ms = epochSeconds > 1e11 ? epochSeconds : epochSeconds * 1000;
    var d = new Date(ms + (Number(clockOffset) || 0) * 1000);
    return d.toISOString().slice(0, 19).replace("T", " ");
  }

  /**
   * Short date time format
   * @param {number} epochSeconds
   * @param {number} clockOffset
   * @returns {string}
   */
  function shortDateTime(epochSeconds, clockOffset) {
    var full = brokerTime(epochSeconds, clockOffset);
    return full === "\u2014" ? "\u2014" : full.slice(8, 19);
  }

  /**
   * Calculate spread in pips
   * @param {number} points - Spread in points
   * @param {number} point - Point size
   * @param {number} pipSize - Pip size
   * @returns {string}
   */
  function spreadPips(points, point, pipSize) {
    if (points === null || points === undefined) return "\u2014";
    var p = Number(pipSize);
    if (!isFinite(p) || p <= 0) return "\u2014";
    return formatNumber((Number(points) * Number(point)) / p, 2);
  }

  // Expose utilities
  global.utils = {
    debounce: debounce,
    throttle: throttle,
    $: $,
    $$: $$,
    el: el,
    clear: clear,
    roleSelector: roleSelector,
    byRole: byRole,
    escapeHtml: escapeHtml,
    replayClass: replayClass,
    setText: setText,
    parseJSON: parseJSON,
    clone: clone,
    uniqueId: uniqueId,
    formatNumber: formatNumber,
    formatSigned: formatSigned,
    tone: tone,
    sleep: sleep,
    retry: retry,
    brokerTime: brokerTime,
    shortDateTime: shortDateTime,
    spreadPips: spreadPips,
    API: global.API,
    SELECTORS: global.SELECTORS,
    HTTP_STATUS: global.HTTP_STATUS,
    VERDICT_CLASSES: global.VERDICT_CLASSES,
  };

})(window);