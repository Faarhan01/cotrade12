# Gateway reference

API reference for the cony gateway daemon.

## Base URL

```
http://127.0.0.1:8888
```

## Conventions

- All responses are JSON.
- Errors return a matching HTTP status with `{"error": "...", "type": "..."}`.
- Money fields are in the account currency (the `currency` field on `/account`).
- Times are epoch seconds (UTC) unless a field name ends in `_iso`.
- Prices are quoted at the symbol's native `digits` precision.

### Order types

`order_type` accepts either the MT5 integer or the name below.

| Name | Integer | Meaning |
|------|---------|---------|
| `buy` | 0 | Market buy |
| `sell` | 1 | Market sell |
| `buy_limit` | 2 | Buy at or below the given price |
| `sell_limit` | 3 | Sell at or above the given price |
| `buy_stop` | 4 | Buy at or above the given price (breakout) |
| `sell_stop` | 5 | Sell at or below the given price (breakout) |
| `buy_stop_limit` | 6 | Stop then limit |
| `sell_stop_limit` | 7 | Stop then limit |
| `close_by` | 8 | Close against an opposite position |

### Timeframes

`timeframe` accepts a name or the MT5 integer. `GET /routes` returns the map.

`M1` `M2` `M3` `M4` `M5` `M6` `M10` `M12` `M15` `M20` `M30`
`H1` `H2` `H3` `H4` `H6` `H8` `H12` `D1` `W1` `MN1`

### Filling modes

`type_filling`: `fok` (0), `ioc` (1), `return` (2), `boc` (3). Defaults to
`return`. Some brokers reject certain modes; if an order fails with
`TRADE_RETCODE_INVALID_FILLING_TYPE` (10030), retry with another.

## Endpoints

### GET /health

Daemon state and MT5 connection details.

```json
{
  "status": "ok",
  "service": "cony-gateway",
  "mt5_connected": true,
  "connection": {
    "connected": true,
    "terminal": { "name": "...", "company": "...", "build": 5100 },
    "account": { "login": 0, "server": "...", "currency": "USD", "leverage": 1000 },
    "package_version": "5.0.6231"
  }
}
```

### GET /routes

Every registered route plus the order type and timeframe maps. Useful as a
discovery call at the start of a session.

### POST /connect

Attach to the terminal. Omit the body fields when the terminal is already
logged in. All parameters optional.

```json
{ "login": 12345, "password": "secret", "server": "Broker-Server" }
```

Also accepts `path` (terminal64.exe location) and `timeout` (ms).

On success the daemon starts a background reconnect loop.

### POST /disconnect

Detach. Returns `{"success": true, "mt5_connected": false}`.

### GET /account

```json
{
  "login": 0, "balance": 0.0, "equity": 0.0, "profit": 0.0,
  "margin": 0.0, "margin_free": 0.0, "margin_level": 0.0,
  "leverage": 1000, "currency": "USD", "trade_allowed": true,
  "trade_expert": true, "limit_orders": 50
}
```

`margin_level` is a percentage of equity used for margin and is `0.0` when
there are no open positions.

### GET /terminal

Terminal name, company, build, data path, language, connected flag.

### GET /symbols

All symbols the broker exposes. Optional `?group=` substring filter and
`?visible=true|false` to narrow to MarketWatch entries.

Each entry includes `name`, `description`, `path`, `digits`, `trade_mode`,
`volume_min`, `volume_max`, `volume_step`, `volume_digits`, `spread`,
`trade_contract_size`, `margin_initial`, `tick_value`, `trade_tick_value`,
`trade_tick_size`, `swap_long`, `swap_short`, `visible`, `select`.

### GET /symbol/{symbol}

Everything about one symbol, plus a `_derived` block built for agents:

```json
{
  "name": "EURUSD",
  "description": "EURUSD",
  "digits": 5,
  "volume_min": 0.01,
  "volume_max": 20.0,
  "volume_step": 0.01,
  "trade_contract_size": 100000.0,
  "spread": 12,
  "_derived": {
    "digits": 5,
    "point_size": 1e-05,
    "pip_size": 0.0001,
    "pip_decimals": 4,
    "points_per_pip": 10,
    "pip_description": "1 point = 1e-05; 1 pip = 0.0001 (10 points)",
    "rounding": "Quote prices to 5 decimal places. Measure stops in pips of 0.0001.",
    "lot_info": { "min_lot": 0.01, "max_lot": 20.0, "lot_step": 0.01, "contract_size": 100000.0 },
    "margin": { "initial": 0.0, "maintenance": 0.0, "currency": "USD" },
    "trade_mode": "FULL",
    "spread": { "current_points": 12, "is_floating": true },
    "swap": { "long": -11.42, "short": 2.66 },
    "tick_value": 1.0,
    "tick_size": 1e-05,
    "pip_value_per_lot": 10.0,
    "value_note": "1 standard lot moves 10 USD per pip.",
    "sizing_formula": "lots = risk_amount / (stop_distance_in_pips * pip_value_per_lot)"
  }
}
```

`trade_mode` is one of `DISABLED`, `LONG_ONLY`, `SHORT_ONLY`, `CLOSE_ONLY`,
`FULL`. Respect it before sending an order.

`pip_value_per_lot` is the key number for position sizing: with a stop `d`
pips away, a position of `n` lots risks roughly `d * n * pip_value_per_lot`.

### POST /symbol/{symbol}/select

Add or remove a symbol from MarketWatch so ticks keep flowing.

```json
{ "enable": true }
```

### GET /tick/{symbol}

```json
{ "time": 0, "bid": 0.0, "ask": 0.0, "last": 0.0, "volume": 0, "flags": 6 }
```

### GET /ticks

Ticks for every watched symbol, or only the ones named in
`?symbols=EURUSD,GBPUSD`. Unavailable symbols come back as `null`.

### GET /candles/{symbol}

OHLCV bars. Query parameters:

| Param | Default | Notes |
|-------|---------|-------|
| `timeframe` | `M1` | Name or MT5 integer |
| `count` | `100` | 1–10000 bars |
| `from` | — | ISO datetime; the server counts back from it |
| `start` | — | Positional instead: `start=0` is the current bar |

```json
{
  "symbol": "EURUSD",
  "timeframe": 5,
  "count": 3,
  "candles": [
    { "time": 0, "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0,
      "tick_volume": 0, "spread": 0, "real_volume": 0 }
  ]
}
```

Use `start=0&count=200` for the most recent 200 bars including the forming one,
or `from=<ISO>` to walk backwards in history.

### GET /positions

Open positions, optionally `?symbol=` or `?ticket=`.

```json
{
  "count": 1,
  "positions": [
    { "ticket": 0, "time": 0, "symbol": "EURUSD", "type": 0,
      "volume": 0.1, "price_open": 0.0, "sl": 0.0, "tp": 0.0,
      "price_current": 0.0, "swap": 0.0, "profit": 0.0,
      "magic": 0, "comment": "", "identifier": 0 }
  ]
}
```

`type` is `0` for buy and `1` for sell. `profit` is already live.

### GET /orders

Pending orders, optionally `?symbol=` or `?ticket=`.

### POST /order

Place an order.

```json
{
  "symbol": "EURUSD",
  "volume": 0.1,
  "order_type": "buy",
  "sl": 1.08,
  "tp": 1.095,
  "deviation": 20,
  "magic": 1001,
  "comment": "ai-entry",
  "type_filling": "return"
}
```

`symbol`, `volume` and `order_type` are required. `price` is optional for
market orders (the server fills in the live ask/bid) and required for pending
orders. `sl` and `tp` are optional; omit a key to leave it unset.

```json
{
  "success": true,
  "order_type": "buy",
  "result": {
    "retcode": 10009, "deal": 0, "order": 0, "volume": 0.1,
    "price": 0.0, "bid": 0.0, "ask": 0.0, "comment": "",
    "request_id": 0, "retcode_external": 0,
    "_success": true, "_retcode_description": "Request completed"
  }
}
```

A rejection returns `409` with the MT5 code so you can tell a requote
(`10004`) from insufficient margin (`10019`) from a frozen position
(`10029`).

### POST /close

```json
{ "ticket": 0, "volume": 0.05, "deviation": 20, "comment": "partial" }
```

`volume` is optional and defaults to the full position. For a partial close,
the engine does not send `position`, so the opposite deal nets the exposure
down instead of closing the whole ticket.

### POST /close-all

```json
{ "symbol": "EURUSD", "magic": 1001 }
```

Both filters optional. Returns a per-position result list.

### POST /modify

```json
{ "ticket": 0, "sl": 1.085 }
```

At least one of `sl` or `tp` is required. Omitted keys keep their current
value.

### POST /cancel

```json
{ "ticket": 0 }
```

### GET /history/deals

Query: `from`, `to` (ISO; defaults to the last 7 days), `symbol`.

### GET /history/orders

Same query parameters as `/history/deals`.

### POST /calc/margin

```json
{ "symbol": "EURUSD", "volume": 0.1, "order_type": "buy", "price": 1.1195 }
```

`price` is optional — the current tick is used when omitted.

```json
{ "symbol": "EURUSD", "volume": 0.1, "margin": 11.2 }
```

### POST /calc/profit

```json
{ "symbol": "EURUSD", "volume": 0.1, "order_type": "buy",
  "open_price": 1.1195, "close_price": 1.1245 }
```

```json
{ "symbol": "EURUSD", "volume": 0.1, "price_move": 0.005, "profit": 50.0 }
```

## Error responses

| Status | When |
|--------|------|
| `400` | Missing or malformed parameter, or unparseable JSON body |
| `404` | Unknown route, unknown symbol, or missing position/order ticket |
| `409` | Order rejected by the terminal; body carries `retcode` |
| `503` | MT5 terminal not connected |
| `500` | Unexpected engine failure; body carries `type` and `error` |

```json
{ "error": "'volume' must be >= 0.00001, got 0", "type": "BadRequest" }
```

## Notes for agents

- Call `GET /health` first. If `mt5_connected` is `false`, call
  `POST /connect` before anything else.
- `GET /symbol/{symbol}` before trading. It tells you the pip size, the lot
  step, whether the symbol is `FULL` or restricted, and the value of a pip.
- Size with `lots = risk_amount / (stop_distance_in_pips * pip_value_per_lot)`,
  then round to the symbol's `lot_step` and clamp to `volume_min`/`volume_max`.
- `pip_size` is 10 points. On a 5-digit pair that is `0.0001`; on a 3-digit
  JPY pair it is `0.01`. Always read it rather than assuming 0.0001.
- Set `magic` on every order so you can filter positions and orders by
  strategy later via `/positions?magic=` style filtering and `/close-all`.
- Prices must match the symbol's `digits`. Stops that violate the broker's
  minimum distance come back as retcode `10016`.
