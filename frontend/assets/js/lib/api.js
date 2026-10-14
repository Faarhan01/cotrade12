/* frontend — lib/api.js
   ---------------------------------------------------------------------------
   The single place the frontend talks to the backend.

   Two rules this enforces, both of which exist because getting them wrong is
   invisible until something breaks:

   1. Every failure surfaces as a rejected promise carrying the server's own
      message. The gateway answers errors as {"error", "type", "status"}, and
      that text is far more useful than "failed to fetch".

   2. Streaming is never mixed with request/response. EventSource handles its
      own reconnection and applies the server's retry hint, so wrapping it in
      fetch would discard that behaviour and rebuild it badly.
*/
(function (global) {
  "use strict";

  function request(path, options) {
    var opts = options || {};
    return fetch(path, {
      method: opts.method || "GET",
      headers: opts.body ? { "Content-Type": "application/json" } : undefined,
      body: opts.body ? JSON.stringify(opts.body) : undefined
    }).then(function (response) {
      return response.text().then(function (text) {
        var data = null;
        if (text) {
          try { data = JSON.parse(text); } catch (err) { data = null; }
        }
        if (!response.ok) {
          var message = (data && (data.error || data.message))
            || (response.status + " " + response.statusText);
          var failure = new Error(message);
          failure.status = response.status;
          failure.type = data && data.type;
          throw failure;
        }
        return data;
      });
    });
  }

  function get(path) {
    return request(path);
  }

  function post(path, body) {
    return request(path, { method: "POST", body: body || {} });
  }

  /* Open a server-sent event stream.
     `handlers` maps an event name to a callback. The `open` event the gateway
     sends first carries no data, so it is surfaced separately rather than
     parsed as a payload. */
  function stream(path, handlers) {
    if (!path || typeof EventSource === "undefined") return null;
    var source;
    try {
      source = new EventSource(path);
    } catch (err) {
      return null;
    }
    Object.keys(handlers || {}).forEach(function (name) {
      source.addEventListener(name, function (event) {
        var payload;
        try { payload = JSON.parse(event.data); } catch (err) { return; }
        handlers[name](payload);
      });
    });
    source.addEventListener("error", function () {
      // EventSource reconnects on its own. Callers are told so they can show a
      // stale marker, but no retry is scheduled here.
      if (handlers && handlers.error) handlers.error();
    });
    return source;
  }

  global.api = { request: request, get: get, post: post, stream: stream };
})(window);