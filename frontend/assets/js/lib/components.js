/* frontend — lib/components.js
   ---------------------------------------------------------------------------
   Reusable UI components: tables, modals, toasts, confirm dialogs, loaders.

   These components are built on vanilla JS with no dependencies, following
   the project's dependency-free philosophy. */
(function (global) {
  "use strict";

  var utils = global.utils || {};

  // ── Toast Notifications ────────────────────────────────────────────────

  var toastContainer = null;

  function ensureToastContainer() {
    if (!toastContainer) {
      toastContainer = document.createElement("div");
      toastContainer.id = "toast-container";
      toastContainer.style.cssText = [
        "position: fixed",
        "bottom: 1.5rem",
        "right: 1.5rem",
        "z-index: 10000",
        "display: flex",
        "flex-direction: column",
        "gap: 0.5rem",
        "pointer-events: none",
      ].join(";");
      document.body.appendChild(toastContainer);
    }
    return toastContainer;
  }

  /**
   * Show a toast notification
   * @param {string} message - Message to display
   * @param {string} [type="info"] - Type: "info", "success", "warning", "error"
   * @param {number} [duration=4000] - Auto-dismiss after ms
   * @returns {Function} Dismiss function
   */
  function toast(message, type, duration) {
    var container = ensureToastContainer();
    var toastEl = document.createElement("div");

    var colors = {
      info: { bg: "#1e3a5f", border: "#3b82f6", icon: "ℹ" },
      success: { bg: "#064e3b", border: "#10b981", icon: "✓" },
      warning: { bg: "#78350f", border: "#f59e0b", icon: "⚠" },
      error: { bg: "#7f1d1d", border: "#ef4444", icon: "✕" },
    };
    var style = colors[type] || colors.info;

    toastEl.style.cssText = [
      "display: flex",
      "align-items: center",
      "gap: 0.75rem",
      "padding: 0.75rem 1rem",
      "background: " + style.bg,
      "border: 1px solid " + style.border,
      "border-radius: 8px",
      "color: #e6edf3",
      "font-size: 13px",
      "font-family: inherit",
      "min-width: 280px",
      "max-width: 400px",
      "box-shadow: 0 10px 40px rgba(0,0,0,0.3)",
      "opacity: 0",
      "transform: translateX(100%)",
      "transition: opacity 0.2s, transform 0.2s",
      "pointer-events: auto",
    ].join(";");

    toastEl.innerHTML = '<span style="font-size:16px;">' + style.icon + '</span>' +
      '<span style="flex:1;">' + utils.escapeHtml(message) + '</span>' +
      '<button style="background:none;border:none;color:inherit;font-size:18px;cursor:pointer;padding:0 0 0 8px;line-height:1;">✕</button>';

    var closeBtn = toastEl.querySelector("button");
    var dismissed = false;

    var dismiss = function () {
      if (dismissed) return;
      dismissed = true;
      toastEl.style.opacity = "0";
      toastEl.style.transform = "translateX(100%)";
      setTimeout(function () { toastEl.remove(); }, 200);
    };

    closeBtn.addEventListener("click", dismiss);

    container.appendChild(toastEl);

    // Force reflow then animate in
    void toastEl.offsetWidth;
    toastEl.style.opacity = "1";
    toastEl.style.transform = "translateX(0)";

    var timer = setTimeout(dismiss, duration || 4000);

    return dismiss;
  }

  // ── Modal Dialog ────────────────────────────────────────────────────────

  var modalOverlay = null;

  /**
   * Show a modal dialog
   * @param {Object} options
   * @param {string} options.title - Modal title
   * @param {string|Element} options.content - Modal content
   * @param {Array<Object>} [options.buttons] - Buttons: [{text, class, onClick, primary}]
   * @param {boolean} [options.closeOnOverlayClick=true]
   * @param {Function} [options.onClose] - Called when modal closes
   * @returns {Function} Close function
   */
  function modal(options) {
    options = options || {};

    // Remove existing modal
    if (modalOverlay) modalOverlay.remove();

    modalOverlay = document.createElement("div");
    modalOverlay.style.cssText = [
      "position: fixed",
      "inset: 0",
      "background: rgba(0,0,0,0.6)",
      "display: flex",
      "align-items: center",
      "justify-content: center",
      "z-index: 10000",
      "padding: 1rem",
      "opacity: 0",
      "transition: opacity 0.2s",
    ].join(";");

    var modalEl = document.createElement("div");
    modalEl.style.cssText = [
      "background: var(--surface)",
      "border: 1px solid var(--border)",
      "border-radius: 12px",
      "padding: 1.5rem",
      "max-width: 480px",
      "width: 100%",
      "max-height: 80vh",
      "overflow-y: auto",
      "box-shadow: 0 20px 60px rgba(0,0,0,0.4)",
      "transform: scale(0.95)",
      "opacity: 0",
      "transition: transform 0.2s, opacity 0.2s",
    ].join(";");

    var titleHtml = options.title
      ? '<h2 style="margin:0 0 1rem;font-size:1.1rem;font-weight:600;">' + utils.escapeHtml(options.title) + '</h2>'
      : "";

    var contentHtml = typeof options.content === "string"
      ? options.content
      : (options.content ? options.content.outerHTML : "");

    var buttonsHtml = "";
    if (options.buttons && options.buttons.length) {
      buttonsHtml = '<div style="display:flex;gap:0.5rem;justify-content:flex-end;margin-top:1.5rem;">' +
        options.buttons.map(function (btn, i) {
          var primary = btn.primary ? 'style="background:var(--accent);border-color:var(--accent);color:#06121f;font-weight:600;"' : '';
          return '<button type="button" data-btn-index="' + i + '" ' + primary +
            ' class="btn" style="padding:0.5rem 1rem;border-radius:6px;font:inherit;cursor:pointer;">' +
            utils.escapeHtml(btn.text) + '</button>';
        }).join("") +
        '</div>';
      : "";

    modalEl.innerHTML = titleHtml +
      '<div style="margin-bottom:1rem;color:var(--text);line-height:1.6;">' + contentHtml + '</div>' +
      buttonsHtml;

    modalOverlay.appendChild(modalEl);
    document.body.appendChild(modalOverlay);

    var dismissed = false;

    var close = function (result) {
      if (dismissed) return;
      dismissed = true;
      modalOverlay.style.opacity = "0";
      modalEl.style.opacity = "0";
      modalEl.style.transform = "scale(0.95)";
      setTimeout(function () {
        modalOverlay.remove();
        modalOverlay = null;
        if (options.onClose) options.onClose(result);
      }, 200);
    };

    // Handle button clicks
    if (options.buttons && options.buttons.length) {
      modalEl.querySelectorAll("[data-btn-index]").forEach(function (btn, i) {
        btn.addEventListener("click", function () {
          var btnOpt = options.buttons[i];
          var result = btnOpt.onClick ? btnOpt.onClick() : true;
          if (result !== false) close(result);
        });
      });
    }

    // Close on overlay click
    if (options.closeOnOverlayClick !== false) {
      modalOverlay.addEventListener("click", function (e) {
        if (e.target === modalOverlay) close(false);
      });
    }

    // Close on Escape
    var escHandler = function (e) {
      if (e.key === "Escape") {
        close(false);
        document.removeEventListener("keydown", escHandler);
      }
    };
    document.addEventListener("keydown", escHandler);

    // Animate in
    void modalOverlay.offsetWidth;
    modalOverlay.style.opacity = "1";
    modalEl.style.opacity = "1";
    modalEl.style.transform = "scale(1)";

    return close;
  }

  // ── Loading Spinner ────────────────────────────────────────────────────

  /**
   * Show a loading spinner on an element
   * @param {Element} el - Element to show spinner on
   * @param {string} [text="Loading…"] - Loading text
   * @returns {Function} Function to hide spinner
   */
  function showSpinner(el, text) {
    if (!el) return function () { };
    var spinner = document.createElement("div");
    spinner.className = "loading-spinner";
    spinner.style.cssText = [
      "position: absolute",
      "inset: 0",
      "display: flex",
      "align-items: center",
      "justify-content: center",
      "background: rgba(10,14,20,0.85)",
      "z-index: 100",
      "border-radius: inherit",
      "color: var(--accent)",
      "font-size: 13px",
    ].join(";");
    spinner.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;gap:8px;">' +
      '<div style="width:24px;height:24px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;"></div>' +
      '<span>' + (utils.escapeHtml(text || "Loading…")) + '</span>' +
      '</div>';

    // Add spin animation if not exists
    if (!document.getElementById("spin-keyframes")) {
      var style = document.createElement("style");
      style.id = "spin-keyframes";
      style.textContent = '@keyframes spin{to{transform:rotate(360deg);}}';
      document.head.appendChild(style);
    }

    // Ensure parent has relative positioning
    var pos = window.getComputedStyle(el).position;
    if (pos === "static") el.style.position = "relative";

    el.appendChild(spinner);

    return function hideSpinner() {
      spinner.remove();
    };
  }

  // ── Confirm Dialog ────────────────────────────────────────────────────

  /**
   * Show a confirmation dialog
   * @param {string} message - Confirmation message
   * @param {Object} [options]
   * @param {string} [options.title="Confirm"]
   * @param {string} [options.confirmText="Confirm"]
   * @param {string} [options.cancelText="Cancel"]
   * @param {string} [options.type="warning"] - "warning" | "danger" | "info"
   * @returns {Promise<boolean>}
   */
  function confirm(message, options) {
    options = options || {};
    return new Promise(function (resolve) {
      var close = modal({
        title: options.title || "Confirm",
        content: '<p style="margin:0;line-height:1.6;">' + utils.escapeHtml(message) + '</p>',
        buttons: [
          {
            text: options.cancelText || "Cancel",
            class: "btn",
            onClick: function () { return false; },
          },
          {
            text: options.confirmText || "Confirm",
            primary: options.type === "danger",
            onClick: function () { return true; },
          },
        ],
        onClose: function (result) {
          resolve(!!result);
        },
      });
    };
  }

  // ── Empty State Helper ───────────────────────────────────────────────

  /**
   * Create an empty state element
   * @param {string} title - Main title
   * @param {string} [detail] - Detail text
   * @returns {Element}
   */
  function emptyState(title, detail) {
    var div = document.createElement("div");
    div.className = "empty";
    div.innerHTML = utils.escapeHtml(title) + (detail ? '<span>' + utils.escapeHtml(detail) + '</span>' : '');
    return div;
  }

  // ── Table Builder ────────────────────────────────────────────────────

  /**
   * Build a table from column definitions and row data
   * @param {Array<Object>} columns - [{key, label, format?, class?}]
   * @param {Array<Object>} rows - Row data
   * @param {Object} [options]
   * @returns {Element} Table element
   */
  function buildTable(columns, rows, options) {
    options = options || {};
    var table = document.createElement("table");
    table.className = "grid" + (options.class ? " " + options.class : "");
    if (options.mono) table.classList.add("mono");

    // Header
    var thead = document.createElement("thead");
    var headerRow = document.createElement("tr");
    columns.forEach(function (col) {
      var th = document.createElement("th");
      th.textContent = col.label;
      if (col.class) th.className = col.class;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Body
    var tbody = document.createElement("tbody");
    rows.forEach(function (row, rowIdx) {
      var tr = document.createElement("tr");
      if (options.rowClass) {
        var cls = typeof options.rowClass === "function"
          ? options.rowClass(row, rowIdx)
          : options.rowClass;
        if (cls) tr.className = cls;
      }
      columns.forEach(function (col) {
        var td = document.createElement("td");
        var value = row[col.key];
        var formatted = col.format ? col.format(value, row) : (value ?? "—");
        td.textContent = formatted;
        if (col.class) td.className = col.class;
        if (col.align) td.style.textAlign = col.align;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  }

  // ── Form Helpers ──────────────────────────────────────────────────────

  /**
   * Serialize form data to object
   * @param {HTMLFormElement} form
   * @returns {Object}
   */
  function serializeForm(form) {
    var data = {};
    new FormData(form).forEach(function (value, key) {
      data[key] = value;
    });
    return data;
  }

  /**
   * Set form values from object
   * @param {HTMLFormElement} form
   * @param {Object} data
   */
  function populateForm(form, data) {
    Object.keys(data).forEach(function (key) {
      var input = form.elements[key];
      if (!input) return;
      if (input.type === "checkbox") {
        input.checked = !!data[key];
      } else if (input.type === "radio") {
        var radios = form.querySelectorAll('[name="' + key + '"]');
        radios.forEach(function (r) { r.checked = r.value == data[key]; });
      } else {
        input.value = data[key] ?? "";
      }
    });
  }

  /**
   * Clear form
   * @param {HTMLFormElement} form
   */
  function clearForm(form) {
    form.reset();
    form.querySelectorAll("input, select, textarea").forEach(function (el) {
      if (el.type === "checkbox" || el.type === "radio") el.checked = false;
      else el.value = "";
    });
  }

  // ── Export ────────────────────────────────────────────────────────────

  global.components = {
    toast: toast,
    modal: modal,
    confirm: confirm,
    showSpinner: showSpinner,
    emptyState: emptyState,
    buildTable: buildTable,
    serializeForm: serializeForm,
    populateForm: populateForm,
    clearForm: clearForm,
  };

})(window);