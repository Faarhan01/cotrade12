"""
core — shared integration layer for the Cotrade backend.

This package groups the modules that wire infrastructure to the domain
layer and to each other: the HTTP server, the server-side dashboard, and
the database access layer.  It exists so that the dependency direction is
expressed by the directory layout rather than by `sys.path` manipulation.

Nothing under `core/` may be imported by `gateway/cony/` or
`knowledgebase/`; those stay dependency-free.
"""
