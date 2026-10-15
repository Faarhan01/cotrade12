# Local-use Development Rules

- Keep all changes local-first: no deployment assumptions, no Docker/service stack requirements, no platform-specific production tooling.
- Frontend remains dependency-free: no build tool, Node runtime dependency, or CDN.
- `knowledgebase/` must remain dependency-free.
- `gateway/cony/` must not import `server`, `application`, `database`, or `tools`.
- `frontconnect` must stay read-only and isolated: it can gather MT5 data for rendering, but it must not mutate connection state or break backend request handling.
- Do not hardcode MetaTrader 5 data, symbols, prices, currency formatting assumptions, or business constants in the frontend/server when the value can come from MT5.
- Send and receive MetaTrader 5 values as they are; only normalize at rendering boundaries and never silently convert pip/point/symbol spelling.
- Structure modules under the intended layers: `core`, `gateway`, `tools`, `database`.
- Keep database code under `backend/database` and runtime SQLite files under `backend/database/data`; never create a parallel `db/` folder.
- Tests live under `backend/tools/simulatedtester/tests`; `backend/tools/simulatedtester` also contains the isolated simulator.
- Keep environment reads centralized in `backend/core/config.py`.
- Preserve route JSON shapes, endpoint behavior, and database paths unless there is an explicit migration.
- Do not insert `sys.path` mutations outside the approved entrypoints and isolated tool self-containment.
- Run Python compile, pytest, layering audit, and all frontend `node --check` validations after changes.
