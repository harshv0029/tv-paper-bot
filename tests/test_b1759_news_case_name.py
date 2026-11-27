"""B-1759: a scam/fraud word that only names a court case about people is not adverse company news."""
import news_signals as ns

IRCTC = [
    "Delhi HC rejects Lalu Prasad Yadav, Rabri Devi, Tejashwi's pleas in IRCTC scam case, upholds charges - Moneycontrol.com",
    "IRCTC hotels scam: Delhi HC upholds corruption charges against Lalu Prasad, Rabri Devi, Tejashwi Yadav - The Economic Times",
    "Delhi High Court rejects Lalu Yadav, Rabri Devi and Tejashwi's pleas against charges in IRCTC 'scam' case - CNBC TV18",
]
GENUINE = [
    "SEBI bars Gensol promoters over fund diversion fraud",
    "IndusInd Bank shares crash after accounting fraud comes to light",
    "Court rejects bail of XYZ promoter in Rs 500 crore fraud case",
    "CBI chargesheet names company in Rs 500 crore loan fraud",
    "IDFC First Bank scam: employee faked Rs 116-crore FDRs in Smart City fraud, claims CBI",
    "Massive accounting scam at ABC Ltd, auditors resign",
]


def test_case_name_headlines_are_not_hard():
    for t in IRCTC:
        assert ns.is_case_name_headline(t), t
        assert ns.score_headline(t)["hard_neg"] == [], t


def test_case_name_still_mildly_negative_not_zeroed():
    sc = ns.score_headline(IRCTC[0])
    assert sc["hits"] >= 1 and sc["score"] < 0


def test_genuine_company_fraud_stays_hard():
    for t in GENUINE:
        assert ns.score_headline(t)["hard_neg"], t


def test_irctc_three_publishers_not_actionable():
    now = 1_800_000_000
    items = [{"title": t, "ts": now - 600, "source": src} for t, src in
             zip(IRCTC, ("Moneycontrol moneycontrol.com", "The Economic Times economictimes.indiatimes.com",
                         "CNBC TV18 cnbctv18.com"))]
    agg = ns.aggregate(items, now=now)
    assert not ns.confirmation(agg, "long")["actionable"]
    assert agg["hard_neg"] == []
