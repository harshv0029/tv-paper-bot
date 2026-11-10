"""B-1537: news add-on (news_signals.py). Offline: fixture RSS only, no network."""
import email.utils
import time

import news_signals as ns

NOW = 1_800_000_000.0


def _rss(items):
    body = "".join(
        f"<item><title>{t}</title><pubDate>{email.utils.formatdate(NOW - age_h * 3600)}</pubDate>"
        f"<source url='https://{src}'>{src}</source><link>https://x/{i}</link></item>"
        for i, (t, age_h, src) in enumerate(items))
    return f"<?xml version='1.0'?><rss><channel>{body}</channel></rss>"


def test_score_headline_direction_and_hard_flags():
    assert ns.score_headline("XYZ shares surge after company bags order worth Rs 500 crore")["score"] == 1.0
    neg = ns.score_headline("SEBI bars XYZ promoters in fraud probe; stock plunges")
    assert neg["score"] == -1.0 and "fraud" in neg["hard_neg"] and "sebi bars" in neg["hard_neg"]
    assert ns.score_headline("XYZ to hold board meeting on Friday") == {"score": 0.0, "hits": 0, "hard_neg": [], "hard_pos": []}


def test_longer_phrase_is_consumed_not_double_counted():
    s = ns.score_headline("XYZ profit falls 20% in Q2")
    assert s["hits"] == 1 and s["score"] == -1.0  # "profit falls", not also "falls"
    assert ns.score_headline("Refinery outage: no word match inside 'warning'")["hits"] == 0  # "war" is whole-word only


def test_parse_rss_reads_items_and_rejects_hostile_or_bad_xml():
    items = ns.parse_rss(_rss([("A rises", 1, "moneycontrol.com"), ("B falls", 2, "blog.example")]))
    assert [i["title"] for i in items] == ["A rises", "B falls"]
    assert abs(items[0]["ts"] - (NOW - 3600)) < 2 and "moneycontrol" in items[0]["source"]
    assert ns.parse_rss("<!DOCTYPE x [<!ENTITY a 'b'>]><rss/>") == []
    assert ns.parse_rss("not xml") == [] and ns.parse_rss("") == []


def test_aggregate_recency_trust_shrinkage_and_age_cutoff():
    fresh_bad = ns.parse_rss(_rss([("XYZ plunges on fraud probe", 1, "moneycontrol.com"), ("XYZ gains", 40, "moneycontrol.com")]))
    a = ns.aggregate(fresh_bad, NOW)
    assert a["score"] < 0 and a["n"] == 2 and a["hard_neg"][0][0] == "fraud"  # the fresh item outweighs the old one
    one = ns.aggregate(ns.parse_rss(_rss([("XYZ surges", 0, "moneycontrol.com")])), NOW)
    assert 0 < one["score"] <= 0.5  # shrinkage: one headline never reads as +1
    old = ns.aggregate(ns.parse_rss(_rss([("XYZ crashes", 60, "moneycontrol.com")])), NOW)
    assert old == {"score": 0.0, "n": 0, "hard_neg": [], "hard_pos": [], "top": []}
    trusted = ns.aggregate(ns.parse_rss(_rss([("XYZ surges", 0, "moneycontrol.com")])), NOW)["score"]
    untrusted = ns.aggregate(ns.parse_rss(_rss([("XYZ surges", 0, "blog.example")])), NOW)["score"]
    assert trusted > untrusted > 0


def test_market_and_sector_scores_route_headlines_by_keyword():
    items = ns.parse_rss(_rss([
        ("Bank Nifty slumps as PSU banks tumble", 1, "moneycontrol.com"),
        ("Banks fall after RBI rate hike", 2, "livemint.com"),
        ("Lenders sink on NBFC default fears", 2, "economictimes.com"),
        ("Pharma stocks rally on USFDA nod", 1, "moneycontrol.com"),
        ("Sensex, Nifty surge to record high", 1, "moneycontrol.com"),
    ]))
    ms = ns.market_and_sector_scores(items, NOW)
    assert ms["sectors"]["Financial Services"]["score"] < -0.4 and ms["sectors"]["Financial Services"]["n"] == 3
    assert ms["sectors"]["Healthcare"]["score"] > 0 and "Technology" not in ms["sectors"]
    assert ms["market"]["score"] > 0


def _agg(titles):
    return ns.aggregate(ns.parse_rss(_rss([(t, 1, "moneycontrol.com") for t in titles])), NOW)


EMPTY_MS = {"market": ns.aggregate([], NOW), "sectors": {}}


def test_entry_verdict_both_directions():
    bad = _agg(["XYZ plunges after SEBI bars promoters", "XYZ slumps to 52-week low"])
    good = _agg(["XYZ surges as it bags order", "XYZ rallies after upgrade"])
    assert ns.entry_verdict("XYZ.NS", "long", stock=bad, ms=EMPTY_MS)["action"] == "avoid"
    assert ns.entry_verdict("XYZ.NS", "short", stock=bad, ms=EMPTY_MS)["action"] == "allow"
    assert ns.entry_verdict("XYZ.NS", "short", stock=good, ms=EMPTY_MS)["action"] == "avoid"  # short mirror
    assert ns.entry_verdict("XYZ.NS", "long", stock=good, ms=EMPTY_MS)["action"] == "allow"


def test_entry_verdict_sector_and_market_are_caution_only_never_avoid():
    quiet = _agg(["XYZ to hold board meeting"])
    sec = {"Financial Services": _agg(["Banks slump", "Lenders tumble", "PSU banks plunge on rate hike"])}
    v = ns.entry_verdict("XYZ.NS", "long", sector="Financial Services", stock=quiet, ms={"market": ns.aggregate([], NOW), "sectors": sec})
    assert v["action"] == "caution" and "Financial Services" in v["reason"]
    assert ns.entry_verdict("XYZ.NS", "short", sector="Financial Services", stock=quiet,
                            ms={"market": ns.aggregate([], NOW), "sectors": sec})["action"] == "allow"


def test_exit_verdict_tightens_only_on_hard_adverse_event_both_directions():
    assert ns.exit_verdict("XYZ.NS", "long", stock=_agg(["XYZ downgraded by broker"]))["action"] == "tighten"
    assert ns.exit_verdict("XYZ.NS", "long", stock=_agg(["XYZ slips 1%"]))["action"] == "hold"
    assert ns.exit_verdict("XYZ.NS", "short", stock=_agg(["XYZ announces buyback"]))["action"] == "tighten"
    assert ns.exit_verdict("XYZ.NS", "short", stock=_agg(["XYZ downgraded by broker"]))["action"] == "hold"


def test_fail_open_when_feeds_are_unreachable(monkeypatch):
    ns._cache.clear()
    monkeypatch.setattr(ns, "_fetch", lambda url: "")
    assert ns.entry_verdict("XYZ.NS", "long")["action"] == "allow"
    assert ns.exit_verdict("XYZ.NS", "long")["action"] == "hold"
    monkeypatch.setattr(ns, "stock_items", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ns.entry_verdict("XYZ.NS", "long")["action"] == "allow"
    assert ns.exit_verdict("XYZ.NS", "short")["action"] == "hold"
    ns._cache.clear()


def test_cache_reuses_a_fetch_within_ttl(monkeypatch):
    ns._cache.clear()
    calls = []
    monkeypatch.setattr(ns, "_fetch", lambda url: calls.append(url) or _rss([("XYZ surges", 0, "moneycontrol.com")]))
    ns.stock_items("XYZ.NS"); ns.stock_items("XYZ.NS")
    assert len(calls) == 1 and "XYZ" in calls[0] and "when%3A2d" in calls[0]
    ns._cache.clear()


def test_news_signals_endpoint_is_shadow_and_never_raises(monkeypatch):
    import main
    ns._cache.clear()
    monkeypatch.setattr(ns, "_fetch", lambda url: _rss([("XYZ plunges after SEBI bars promoters", 0, "moneycontrol.com")])
                        .replace(str(int(NOW)), str(int(time.time()))))
    monkeypatch.setattr(ns.time, "time", lambda: NOW)
    out = main.news_signals_view(symbol="xyz.ns", direction="long")
    assert out["shadow_only"] is True and out["symbol"] == "XYZ.NS"
    assert out["entry"]["action"] == "avoid" and out["exit"]["action"] == "tighten"
    assert main.news_signals_view()["shadow_only"] is True
    ns._cache.clear()


def test_no_order_path_calls_the_news_addon():
    """Shadow only until the user approves a rule: main.py may reference news_signals only inside the view."""
    import re as _re
    src = open("main.py").read()
    body = src[src.index("NEWS_MONITOR_EVERY_N_TICKS = 10"):src.index('@app.get("/real-protection-status")')]
    assert len(_re.findall(r"news_signals\.", src)) == len(_re.findall(r"news_signals\.", body))


def test_stock_relevance_filter_and_name_query(monkeypatch):
    assert ns.is_relevant("Yes Bank shares fall 3%", "YESBANK.NS", "Yes Bank")
    assert ns.is_relevant("YESBANK hits upper circuit", "YESBANK.NS", "Yes Bank")
    assert not ns.is_relevant("Whirlpool of India Q2 profit drops 39%", "RELIANCE.NS", "Reliance")
    assert not ns.is_relevant("Sailing stocks rally", "SAIL.NS", None)  # whole word only
    assert ns.stock_query("YESBANK.NS", "Yes Bank").startswith('("Yes Bank" OR "YESBANK")')
    assert ns.stock_query("SAIL.NS", None).startswith('"SAIL" ')
    monkeypatch.setattr(ns, "_names_cache", {"RELIANCE.NS": "Reliance Industries Limited", "TCS.NS": "Tata Consultancy Services Limited"})
    assert ns.company_name("RELIANCE.NS") == "Reliance" and ns.company_name("TCS.NS") == "Tata Consultancy Services"
    assert ns.company_name("NOPE.NS") is None
    ns._cache.clear()
    monkeypatch.setattr(ns, "_fetch", lambda url: _rss([("Reliance bags order", 0, "moneycontrol.com"), ("Whirlpool profit drops", 0, "moneycontrol.com")]))
    assert [i["title"] for i in ns.stock_items("RELIANCE.NS")] == ["Reliance bags order"]
    ns._cache.clear()


def test_hard_event_counts_only_from_a_trusted_publisher():
    blog = ns.aggregate(ns.parse_rss(_rss([("How analyst upgrades will impact XYZ stock", 1, "simplywall.st")])), NOW)
    assert blog["hard_pos"] == [] and blog["score"] > 0
    mc = ns.aggregate(ns.parse_rss(_rss([("Broker upgrades XYZ", 1, "moneycontrol.com")])), NOW)
    assert mc["hard_pos"][0][0] == "upgrades"


def test_overseas_headlines_do_not_score_an_indian_sector():
    items = ns.parse_rss(_rss([("European power prices shoot up as wind slumps", 1, "livemint.com"), ("Power stocks rally on demand", 1, "livemint.com")]))
    assert ns.market_and_sector_scores(items, NOW)["sectors"]["Utilities"]["n"] == 1
