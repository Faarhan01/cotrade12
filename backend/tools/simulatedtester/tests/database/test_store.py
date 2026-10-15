import os, sys, tempfile

backend = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if backend not in sys.path:
    sys.path.insert(0, backend)

from database.store import Store


def test_store_migrates_on_construction():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    with Store(path) as s:
        rows = s.query("SELECT name FROM sqlite_master WHERE type='table'")
        names = {r["name"] for r in rows}
    os.unlink(path)
    for suffix in ("-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except FileNotFoundError:
            pass
    assert "reports" in names
    assert "strategies" in names
    assert "pattern_hits" in names
