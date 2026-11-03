"""B-1447: the F&O chain snapshot (read-only research data) runs only in NSE hours, not after the close."""
import inspect
import main


def test_snapshot_call_gated_by_nse_hours():
    src = inspect.getsource(main)
    i = src.index("await asyncio.to_thread(_fo_chain_monitoring_snapshot_own_conn)")
    window = src[i - 400:i]
    assert "if _nse_equity_market_open_now():" in window
