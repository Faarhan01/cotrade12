/* frontend — lib/dom.js
   ---------------------------------------------------------------------------
   Small DOM helpers, plus the bootstrap reader.

   The bootstrap block is injected by the server into the page. Reading it here
   means every page gets the same access to runtime configuration and the same
   graceful failure if the block is missing.
*/
(function (global) {
  "use strict";

  function $(selector, scope) {
    return (scope || document).querySelector(selector);
  }

  function $$(selector, scope) {
    return Array.prototype.slice.call(
      (scope || document).querySelectorAll(selector));
  }

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

  function clear(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
  }

  /* Read the server-injected runtime block. Absent or malformed yields an
     empty object rather than throwing, so a page still renders - just without
     live data. */
  function bootstrap() {
    var node = document.getElementById("bootstrap");
    if (!node) return {};
    try {
      return JSON.parse(node.textContent) || {};
    } catch (err) {
      return {};
    }
  }

  /* CSS.escape is missing in older Safari. Symbol names come from the broker
     and may contain characters that would otherwise break a selector. */
  function cssEscape(value) {
    if (global.CSS && global.CSS.escape) return global.CSS.escape(value);
    return String(value).replace(/[^\w-]/g, function (ch) { return "\\" + ch; });
  }

  /* Re-trigger a CSS animation by removing the class, forcing a reflow, and
     re-adding it. Without the reflow, setting the same class twice does
     nothing and the flash stops working. */
  function replayClass(node, name) {
    if (!node) return;
    node.classList.remove("up", "down");
    void node.offsetWidth;
    node.classList.add(name);
  }

  function setText(node, text) {
    if (node && node.textContent !== text) node.textContent = text;
  }

  global.dom = {
    $: $,
    $$: $$,
    el: el,
    clear: clear,
    bootstrap: bootstrap,
    cssEscape: cssEscape,
    replayClass: replayClass,
    setText: setText
  };
})(window);