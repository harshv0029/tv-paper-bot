"""Every real-money entry path must consult the joint Kotak-P&L daily loss cap."""
import inspect
import main


def test_all_real_entry_paths_use_joint_loss_budget():
    for fn in (main._maybe_place_real_entry, main._maybe_place_real_short_entry,
               main._maybe_place_real_swing_entry, main._real_fo_buy_contract):
        assert "_real_loss_budget(" in inspect.getsource(fn), fn.__name__


def test_description_is_short_and_says_all_categories():
    desc = main.RUNTIME_SETTINGS_META["daily_risk_pct"][4]
    assert "every category" in desc and len(desc) < 220
