"""B-1643: every JSON response body has Kotak account ids masked; non-JSON untouched."""
from fastapi.testclient import TestClient
from fastapi.responses import PlainTextResponse

import main


def test_json_response_masks_account_ids():
    @main.app.get("/__b1643_json")
    def _j():
        return {"EntityId": "account-AB12C", "gui": "ZZ9ZZ-0123abcd-0123-0123-0123-0123456789ab", "n": 261119000372979}

    r = TestClient(main.app).get("/__b1643_json")
    assert r.status_code == 200
    d = r.json()
    assert d["EntityId"] == "account-***"
    assert d["gui"] == "***-0123abcd-0123-0123-0123-0123456789ab"
    assert d["n"] == 261119000372979
    assert int(r.headers["content-length"]) == len(r.content)


def test_non_json_untouched():
    @main.app.get("/__b1643_txt", response_class=PlainTextResponse)
    def _t():
        return "account-AB12C"

    assert TestClient(main.app).get("/__b1643_txt").text == "account-AB12C"
