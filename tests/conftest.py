import pytest


@pytest.fixture(autouse=True)
def _swing_entry_cutoff_off_by_default(monkeypatch):
    # The 15:00 IST real swing entry cutoff is wall-clock dependent; tests that
    # exercise it set it explicitly. Everything else must not depend on when it runs.
    import main
    monkeypatch.setattr(main, "SWING_REAL_ENTRY_CUTOFF_MIN", 24 * 60 + 1)
