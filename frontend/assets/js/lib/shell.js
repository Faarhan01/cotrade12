/* frontend — lib/shell.js
   ---------------------------------------------------------------------------
   Paints the shared header and footer from the server-injected bootstrap
   block.

   Every page carries the same top bar and footer, but only the account
   overview used to include the script that filled them in. On the other pages
   the status stayed at "Loading…" and every footer value stayed an em dash,
   because the markup is duplicated and the initial data only arrives once.

   This keeps the dependency-free rule: reading JSON the daemon already sent is
   cheaper and more reliable than opening another request per page. */
(function (global) {
  "use strict";

  function role(name) {
    return document.querySelector('[data-role="' + name + '"]');
  }

  function setRole(name, value) {
    var node = role(name);
    if (node && node.textContent !== value) node.textContent = value;
  }

  function paintStatus(connected) {
    var node = role("status");
    if (!node) return;
    node.innerHTML = connected
      ? '<span class="dot ok"></span>Connected'
      : '<span class="dot bad"></span>Disconnected';
  }

  function paintShell(boot) {
    boot = boot || {};
    var account = boot.account || {};
    var terminal = boot.terminal || {};
    var clockOffset = Number(boot.clock_offset) || 0;

    setRole("account", account.login || "—");
    setRole("server", account.server || "—");
    setRole("mode", account._trade_mode || account.trade_mode || "—");
    setRole("account-hint", "account " + (account.login || "—"));
    setRole("leverage-hint", account.server || "—");
    setRole("package", boot.package_version || "—");
    setRole("terminal", terminal.build ? "build " + terminal.build : "—");
    setRole("offset", clockOffset ? clockOffset.toFixed(1) + " s offset" : "unknown");
    setRole("permissions",
      ((terminal.trade_allowed) ? "allowed" : "blocked")
      + " · DLLs "
      + ((terminal.dlls_allowed) ? "on" : "off"));

    paintStatus(boot.connected !== false);
    return clockOffset;
  }

  function startClock(boot) {
    var clockOffset = Number(boot.clock_offset) || 0;
    var fmtLib = global.fmt || global.fmtLib; // Support both naming conventions
    function tick() {
      var clock = fmtLib ? fmtLib.clockOnly(clockOffset) + " UTC" : "";
      setRole("clock", clock);
    }
    tick();
    global.setInterval(tick, 1000);
  }

  function start(boot) {
    boot = boot || (global.dom && global.dom.bootstrap ? global.dom.bootstrap() : {});
    paintShell(boot);
    startClock(boot);
  }

  global.shell = {
    start: start,
    paintShell: paintShell,
    paintStatus: paintStatus
  };
})(window);
