"""B-1306: login() reuses one session instead of a fresh TOTP login per call."""
from unittest.mock import patch

import kotak_neo


def test_login_is_reused_within_ttl_and_refreshed_after_invalidate():
    kotak_neo.invalidate_session()
    with patch("kotak_neo.login", side_effect=lambda: object()) as fl:
        a = kotak_neo.shared_login()
        b = kotak_neo.shared_login()
        assert a is b and fl.call_count == 1
        kotak_neo.invalidate_session()
        c = kotak_neo.shared_login()
        assert c is not a and fl.call_count == 2
    kotak_neo.invalidate_session()


def test_failed_login_is_not_cached():
    kotak_neo.invalidate_session()
    with patch("kotak_neo.login", side_effect=[RuntimeError("x"), object()]) as fl:
        try:
            kotak_neo.shared_login()
        except RuntimeError:
            pass
        assert kotak_neo.shared_login() is not None and fl.call_count == 2
    kotak_neo.invalidate_session()
