"""B-1564: kotak_fill_ledger keeps a second (git side-branch) copy; restore merges, push is an append-only union."""
import main


class _R:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body

    def json(self):
        return self._b

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _row(day, sym, bq, sq=0, src="kotak_positions", upd=1.0):
    return {"day": day, "trdsym": sym, "prod": "CNC", "source": src, "seg": "nse_cm", "buy_qty": bq, "buy_amt": bq * 10.0,
            "sell_qty": sq, "sell_amt": sq * 11.0, "updated_at": upd}


def test_merge_union_more_fills_wins_and_drops_local_opening():
    remote = [_row("2026-11-02", "SAIL", 5), _row("2026-11-03", "WIPRO", 2)]
    local = [_row("2026-11-03", "WIPRO", 2, 2, upd=2.0), _row("2026-11-12", "IRCTC", 1),
             _row("2026-11-12", "OLD", 3, src="opening")]
    got = {(r["day"], r["trdsym"]): r for r in main._fill_ledger_merge_rows(remote, local)}
    assert set(got) == {("2026-11-02", "SAIL"), ("2026-11-03", "WIPRO"), ("2026-11-12", "IRCTC")}
    assert got[("2026-11-03", "WIPRO")]["sell_qty"] == 2
    # a smaller local row never shrinks the git copy
    got2 = {(r["day"], r["trdsym"]): r for r in main._fill_ledger_merge_rows(local[:1], [_row("2026-11-03", "WIPRO", 1)])}
    assert got2[("2026-11-03", "WIPRO")]["buy_qty"] == 2
    # empty remote keeps the local opening rows (true first capture)
    assert len(main._git_tier_merge_rows("kotak_fill_ledger", [], local)) == 3


def test_restore_merges_git_copy_into_wiped_ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "f.db"))
    main.init_db()
    monkeypatch.setattr(main, "_git_tier_hydrated", set())
    with main.closing(main.get_db()) as c:  # a post-wipe capture: only today's row, plus a bogus 'opening' row
        for r in (_row("2026-11-16", "RECLTD", 4), _row("2026-11-16", "X", 9, src="opening")):
            c.execute("INSERT INTO kotak_fill_ledger (day, trdsym, prod, source, seg, buy_qty, buy_amt, sell_qty, sell_amt, "
                      "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)", tuple(r.values()))
        c.commit()
    remote = [_row("2026-11-02", "SAIL", 5, 5), _row("2026-11-11", "BANKBARODA", 3, 3)]
    urls = []
    monkeypatch.setattr(main.requests, "get", lambda url, **k: urls.append(url) or _R(200, {"rows": remote}))
    assert main._fill_ledger_git_restore("o/r")
    assert "/state-sync/docs/tables/kotak_fill_ledger.json" in urls[0]
    with main.closing(main.get_db()) as c:
        days = sorted((r[0], r[1]) for r in c.execute("SELECT day, trdsym FROM kotak_fill_ledger").fetchall())
    assert ("2026-11-02", "SAIL") in days and ("2026-11-11", "BANKBARODA") in days and ("2026-11-16", "RECLTD") in days
    assert "kotak_fill_ledger" in main._git_tier_hydrated


def test_restore_404_counts_as_restored_and_push_waits_on_failure(monkeypatch):
    monkeypatch.setattr(main, "_git_tier_hydrated", set())
    monkeypatch.setattr(main.requests, "get", lambda url, **k: _R(404))
    assert main._fill_ledger_git_restore("o/r") and "kotak_fill_ledger" in main._git_tier_hydrated
    monkeypatch.setattr(main, "_git_tier_hydrated", set())
    monkeypatch.setenv("GITHUB_SYNC_TOKEN", "dummy")
    monkeypatch.setattr(main.requests, "get", lambda url, **k: (_ for _ in ()).throw(RuntimeError("net")))
    assert main._git_tier_push_side_branch("kotak_fill_ledger") is False  # restore failed: no push that could clobber
    assert "kotak_fill_ledger" in main._GIT_TIER_PUSH_TABLES
