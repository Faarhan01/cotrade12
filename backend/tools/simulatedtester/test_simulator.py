"""Self-contained tests for the local simulator only."""
from simulator import FakeTerminal


def test_tick_and_order_flow():
    terminal = FakeTerminal(seed=1)
    first = terminal.tick("EURUSD")
    assert "bid" in first and "ask" in first
    ticket = terminal.place_order("EURUSD", 1, 0.1)
    assert ticket == 1000
    assert terminal.close_order(ticket) is True
    assert terminal.open_orders == []


if __name__ == "__main__":
    test_tick_and_order_flow()
    print("tester OK")
