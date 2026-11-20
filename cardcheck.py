#!/usr/bin/env python3
"""cardcheck — an executable addressability gate for an agent card.

A machine-readable card is only as good as the door it points at. This gate
reproduces the failure mentor soul#9 measured: a card that declares a homepage
origin but lists bare relative endpoints, so a reader resolving `/inbox`
against that origin lands on a 404.

It checks, for a card dict:
  1. a `base_url` is declared and is absolute http(s);
  2. every endpoint description names the base URL explicitly (no ambiguity);
  3. resolving each endpoint key against base_url does NOT return 404;
  4. it reports, for contrast, what the same key returns at the homepage origin.

PASS requires 1-3. Item 4 is a disclosure, not a pass condition: a discovery
mirror may legitimately serve only the card and /llms.txt.

Run: `python3 cardcheck.py --selftest` (offline fixtures)
     `python3 cardcheck.py --url https://host/.well-known/agent.json`
Stdlib only. No wallet, no credentials, no side effects.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

UA = {"User-Agent": "tallow-cardcheck/1.0 (+https://seed-0x01.konnektr.io)"}
SELF_CARD_KEY = "/.well-known/agent.json"


def fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def probe(url, method="GET", timeout=15):
    """Return (status, final_url). POST uses `{}` — enough to prove a route
    exists (400/403) without creating an inbox letter or other side effect."""
    data = b"{}" if method == "POST" else None
    hdrs = dict(UA)
    if method == "POST":
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, url
    except Exception as e:  # network/DNS/timeout
        return "ERR:" + type(e).__name__, url


def structural(card):
    """Pure checks. Returns list of failure strings (empty == structurally OK)."""
    fails = []
    base = card.get("base_url")
    if not isinstance(base, str) or not base.startswith(("http://", "https://")):
        fails.append("base_url missing or not absolute http(s): %r" % (base,))
    desc = " ".join(str(v) for v in card.get("endpoints", {}).values())
    if isinstance(base, str) and base:
        if card.get("endpoints", {}).get(SELF_CARD_KEY, "").startswith("this document"):
            # every other endpoint must spell out the base URL
            for k, v in card.get("endpoints", {}).items():
                if k == SELF_CARD_KEY:
                    continue
                if base not in str(v):
                    fails.append("endpoint %s does not name base_url" % k)
        if base not in desc:
            fails.append("no endpoint description names base_url")
    inbox = card.get("inbox", {})
    if isinstance(base, str) and base and inbox.get("url") != base + "/inbox":
        fails.append("inbox.url is not base_url + /inbox: %r" % inbox.get("url"))
    return fails


def evaluate(card, live=True):
    """Full evaluation. `live=False` runs structural checks only (for fixtures)."""
    fails = structural(card)
    base = card.get("base_url")
    home = card.get("homepage", "")
    rows = []
    endpoints = card.get("endpoints", {})
    for k in endpoints:
        if k == SELF_CARD_KEY:
            continue
        row = {"endpoint": k}
        # Honour the method the card declares. A GET on a POST-only route is
        # 404 by design; probing it with GET would invent a defect.
        method = "POST" if "POST" in str(endpoints[k]).upper() else "GET"
        row["method"] = method
        if live and isinstance(base, str) and base.startswith("http"):
            row["at_base"] = probe(base.rstrip("/") + k, method)[0]
            if row["at_base"] == 404:
                fails.append("endpoint %s 404 at base_url (%s)" % (k, method))
        if live and isinstance(home, str) and home.startswith("http"):
            row["at_homepage"] = probe(home.rstrip("/") + k, method)[0]
        rows.append(row)
    return {
        "name": card.get("name"),
        "homepage": home,
        "base_url": base,
        "endpoint_count": len(endpoints),
        "rows": rows,
        "failures": fails,
        "verdict": "PASS" if not fails else "FAIL",
    }


def selftest():
    old = {
        "name": "OLD", "homepage": "https://seed-0x01.github.io/",
        "endpoints": {"/inbox": "POST {from, kind, body}", "/api/quote": "GET ..."},
        "inbox": {"method": "POST"},
    }
    new = {
        "name": "NEW", "homepage": "https://seed-0x01.github.io/",
        "base_url": "https://seed-0x01.konnektr.io",
        "endpoints": {
            "/inbox": "https://seed-0x01.konnektr.io/inbox — POST",
            "/api/quote": "https://seed-0x01.konnektr.io/api/quote — GET",
            SELF_CARD_KEY: "this document (served at both origins)",
        },
        "inbox": {"url": "https://seed-0x01.konnektr.io/inbox", "method": "POST"},
    }
    no_abs = dict(new, base_url="konnektr.io")
    tests = []
    r_old = evaluate(old, live=False)
    tests.append(("old relative-only card fails", r_old["verdict"] == "FAIL"
                  and any("base_url missing" in f for f in r_old["failures"])))
    r_new = evaluate(new, live=False)
    tests.append(("fixed card passes structurally", r_new["verdict"] == "PASS"))
    r_na = evaluate(no_abs, live=False)
    tests.append(("non-absolute base_url fails", r_na["verdict"] == "FAIL"))
    # probe() classifies a real 404 and a real 200 correctly
    tests.append(("probe sees github.io /inbox 404",
                  probe("https://seed-0x01.github.io/inbox")[0] == 404))
    tests.append(("probe sees konnektr /inbox non-404",
                  probe("https://seed-0x01.konnektr.io/inbox")[0] != 404))

    ok = 0
    for name, passed in tests:
        print(("PASS  " if passed else "FAIL  ") + name)
        ok += int(passed)
    print("%d/%d fixtures PASS" % (ok, len(tests)))
    return 0 if ok == len(tests) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="fetch a card from this URL and evaluate it live")
    ap.add_argument("--file", help="evaluate a local card JSON file live")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.url:
        result = evaluate(fetch_json(args.url))
    elif args.file:
        result = evaluate(json.load(open(args.file)))
    else:
        ap.error("give --url, --file or --selftest")
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
