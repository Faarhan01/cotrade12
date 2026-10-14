# cotrade frontend

Static front end for the cony gateway. Plain HTML, CSS and JavaScript — no
build step, no npm, no CDN, no web fonts. A trading desk is often offline,
and a page that renders as Times while a CDN times out looks broken, so
everything here is served from the local process.

## Layout

```
frontend/
├── pages/                  one .html per screen
│   ├── index.html          /          account overview
│   ├── symbols.html        /ui/symbols     instrument browser
│   └── research.html       /ui/research    patterns, strategies, backtests
├── partials/               shared fragments, one source
│   ├── head.html           charset, stylesheets
│   ├── header.html         top bar, nav, connection state
│   └── footer.html         package/terminal versions, links
└── assets/
    ├── css/
    │   ├── base.css        design tokens, reset, typography
    │   ├── layout.css      page furniture and grid
    │   ├── components.css  cards, tables, tags, buttons, forms
    │   └── pages/          styles used by exactly one page
    └── js/
        ├── lib/            shared: format, dom, api
        └── pages/          one script per page
```

## URLs

| URL | Serves |
|---|---|
| `/` | `pages/index.html` |
| `/ui/{page}` | `pages/{page}.html` |
| `/assets/{path...}` | `assets/**` |

`/ui/` exists because `/research`, `/account` and friends are the JSON API.
Keeping the prefixes apart means an agent never has to tell a page from a
payload.

## Adding a page

1. Create `pages/mypage.html`. Copy the marker block from `pages/index.html`.
2. Add `assets/js/pages/mypage.js` and `assets/css/pages/mypage.css` if needed.
3. Add it to `_SECTIONS` in `backend/dashboard/__init__.py` so the server
   knows what data to collect. Without that it defaults to account and
   terminal only, which is enough for the shared header and footer.

No Python change is needed for step 1–2 beyond adding the nav link in
`partials/header.html`.

## Server markers

Pages may contain two markers, expanded before the page is sent:

```html
<!--#include header-->     splices in frontend/partials/header.html
<!--#bootstrap-->          replaced with the runtime JSON block
```

**Do not reproduce either marker literally inside an HTML comment.** An HTML
comment ends at the first `-->` it contains, so a comment that spells one out
closes early and everything after it spills into the visible page. Because the
splice is not recursive, that stray text then survives into the served
response. This cost a duplicated 30 KB bootstrap payload before it was caught;
`verify.py` now asserts no marker survives.

## Data

The page receives its initial data in the `bootstrap` JSON block, injected at
the marker. It contains the account figures, terminal build, broker clock
offset, and the two SSE stream URLs. Everything after first paint arrives over:

- `/stream/portfolio?interval=1` — account, equity, open positions
- `/stream/ticks?symbols=…&interval=1` — live bid/ask, only for moved symbols

For anything else, call the JSON API directly from `lib/api.js`. The symbol
browser does exactly this against `/symbols/search`.

`/symbols` is 1.5 MB for this broker's 731 instruments and is never sent to
the browser. Search on demand instead.

## Conventions

- **Tabs in every figure.** Values change constantly; proportional digits make
  the whole row shift sideways on each update.
- **Pip sizes come from the server.** They vary per instrument and cannot be
  inferred from the digit count — an earlier attempt was wrong on everything
  except plain FX pairs.
- **Timestamps render in broker time**, UTC plus the published clock offset, so
  a deal time and the header clock cannot disagree.
- **Colour means one thing.** Green is a gain, red a loss, muted neutral. The
  verdict classes on the research page follow the same rule, which is why
  `noise` is never green.
- **Escape anything from the broker.** Symbol names, deal comments and server
  names all come from a third party. `lib/dom.js` and `lib/format.js` provide
  `escapeHtml` for that reason.

## Editing safely

Pages and assets are read from disk on every request. Save the file, reload
the browser — no restart needed. Only changes to `backend/dashboard/*.py`
require restarting the daemon.