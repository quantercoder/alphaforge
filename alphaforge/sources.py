"""Free point-in-time data sources: FRED / ALFRED (macro, with vintages) and SEC EDGAR (company filings).

Keys come from the environment (GitHub secrets in the research workflow), never from the repository:
    FRED_API_KEY    free key from fred.stlouisfed.org
    SEC_USER_AGENT  "Name email" the SEC requires in every request (its fair-access policy)

    python -m alphaforge.sources --check     # one small request to each, prints what came back
"""
import argparse
import json
import os
import time
import urllib.parse
import urllib.request

FRED = "https://api.stlouisfed.org/fred"
SEC_DATA = "https://data.sec.gov"
SEC_WWW = "https://www.sec.gov"
_last_sec = [0.0]


def _get(url, headers=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and i < tries - 1:
                time.sleep(2 ** i * 2)
                continue
            raise RuntimeError(f"{url.split('?')[0]} -> HTTP {e.code}") from None
        except urllib.error.URLError:
            if i == tries - 1:
                raise
            time.sleep(2 ** i * 2)


# ---------------------------------------------------------------- FRED / ALFRED

def fred_key():
    k = os.environ.get("FRED_API_KEY")
    if not k:
        raise RuntimeError("FRED_API_KEY is not set")
    return k


def fred_vintages(series_id):
    """Every value the series has ever shown, with the dates it was shown (ALFRED): rows of
    (observation date, value, realtime_start, realtime_end). Point-in-time: on day d the known value for an
    observation is the row whose realtime_start <= d <= realtime_end."""
    import pandas as pd
    q = urllib.parse.urlencode({"series_id": series_id, "api_key": fred_key(), "file_type": "json",
                                "realtime_start": "1776-07-04", "realtime_end": "9999-12-31"})
    obs = json.loads(_get(f"{FRED}/series/observations?{q}"))["observations"]
    df = pd.DataFrame(obs)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    for c in ("date", "realtime_start"):
        df[c] = pd.to_datetime(df[c])
    df["realtime_end"] = pd.to_datetime(df["realtime_end"].replace("9999-12-31", "2262-04-11"))
    return df.dropna(subset=["value"])[["date", "value", "realtime_start", "realtime_end"]]


def fred_latest(series_id):
    """The current vintage only: right for market series (yields, spreads) that are never revised."""
    import pandas as pd
    q = urllib.parse.urlencode({"series_id": series_id, "api_key": fred_key(), "file_type": "json"})
    obs = json.loads(_get(f"{FRED}/series/observations?{q}"))["observations"]
    s = pd.Series({pd.Timestamp(o["date"]): o["value"] for o in obs})
    return pd.to_numeric(s, errors="coerce").dropna()


# ---------------------------------------------------------------- SEC EDGAR

def sec_headers():
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError("SEC_USER_AGENT is not set")
    return {"User-Agent": ua, "Accept-Encoding": "identity"}


def sec_get(url):
    """At most 8 requests a second (the SEC allows 10)."""
    wait = 0.125 - (time.time() - _last_sec[0])
    if wait > 0:
        time.sleep(wait)
    _last_sec[0] = time.time()
    return _get(url, sec_headers())


def sec_tickers():
    """Ticker -> CIK for companies currently filing with the SEC."""
    d = json.loads(sec_get(f"{SEC_WWW}/files/company_tickers.json"))
    return {v["ticker"].upper(): int(v["cik_str"]) for v in d.values()}


def sec_company_facts(cik):
    """Every XBRL fact a company has filed: values with the period, the form, and the filing date."""
    return json.loads(sec_get(f"{SEC_DATA}/api/xbrl/companyfacts/CIK{cik:010d}.json"))


def check():
    """One small request to each source; prints what came back without printing any key."""
    ok = True
    try:
        v = fred_vintages("PAYEMS")
        first = v.sort_values("realtime_start").groupby("date").first()
        print(f"FRED/ALFRED ok: PAYEMS {len(v):,} vintage rows; Jan 2020 first published "
              f"{first.loc['2020-01-01', 'value']:,.0f} on {first.loc['2020-01-01', 'realtime_start'].date()}, "
              f"now {v[v['date'] == '2020-01-01'].sort_values('realtime_start')['value'].iloc[-1]:,.0f}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"FRED failed: {e}")
    try:
        t = sec_tickers()
        f = sec_company_facts(t["AAPL"])
        ni = [x for x in f["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"] if x.get("form") == "10-K"]
        print(f"SEC EDGAR ok: {len(t):,} tickers; Apple has {len(f['facts']['us-gaap'])} us-gaap concepts; "
              f"latest 10-K net income {ni[-1]['val']:,} for the year to {ni[-1]['end']}, filed {ni[-1]['filed']}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"SEC failed: {e}")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        raise SystemExit(0 if check() else 1)
