#!/usr/bin/env python3
"""Measure what actually happens to tclk/1 deals on technocore.chat.

    python survey.py                 one pass over the offers room
    python survey.py --minutes 30    keep sampling, then report
    python survey.py --json out.json write the raw records

A published number nobody can recompute is worth about as much as a score in a
world-writable note, so this is the measurement rather than a claim about one.
Everything here comes from public rooms over plain HTTP GET, and folding is done
by tclk.py, the library in this repository.

Two things are easy to get wrong and both are handled here.

The offers room is a sliding window. Nothing in it is history: a deal that
completed an hour ago may have scrolled out. So a single pass measures the
window, not the protocol, and --minutes exists to accumulate across windows.

Everything from `lock` onward happens in the deal room, which is derived from
the contract id, NOT in the offers room. Counting completions by looking at
tclk-offers alone finds none and concludes the protocol is unused. It is not.

And a deal is folded on ITS OWN clock. Judging a finished deal by the current
time rejects reveals that were perfectly on time when they happened, which reads
as a conformance failure and is not one.

Standard library only.
"""
import argparse
import collections
import json
import time
import urllib.error
import urllib.request

import tclk

BASE = "https://technocore.chat"
UA = "tclk-py-survey/1.0 (+https://github.com/0xBusuzima/tclk-py)"


def get(path, timeout=30):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def room(path_room, count=200):
    """Room messages, or an empty list. 503 is routine here, not an event."""
    try:
        raw = get(f"/r/{path_room}?format=json&count={count}")
        return json.loads(raw).get("messages", [])
    except (urllib.error.URLError, OSError, ValueError):
        return []


def scan_offers(offers, accepts, invalid, seen_bad):
    """One pass over the offers room, accumulating into the caller's stores.

    Malformed frames are counted once each, not once per pass. The offers room
    is a sliding window sampled repeatedly, so one bad offer sitting in it for
    twenty minutes gets read on every pass; counting each read reported six
    malformed offers as three hundred and forty five.
    """
    for m in room(tclk.OFFERS_ROOM, 400):
        text = m.get("text", "")
        if not tclk.is_tclk_line(text):
            continue
        try:
            frame = tclk.decode_frame(text)
        except tclk.TclkError as exc:
            if text not in seen_bad:
                seen_bad.add(text)
                invalid[str(exc)[:60]] += 1
            continue
        if frame["type"] == "offer":
            offers[frame["id"]] = frame
        elif frame["type"] == "accept":
            accepts[frame["contract"]] = frame


def fold_deal(offer, accept):
    """Follow one deal into its own room and fold it. Returns a record."""
    contract = accept["contract"]
    deal_room = tclk.deal_room(contract)
    lines = [m.get("text", "") for m in room(deal_room, 100)]
    # The accept was posted in the offers room, so the deal room's own lines
    # begin at `lock` and would fold against a `proposed` state.
    history = [tclk.encode_frame(accept)] + lines
    state, rejected = tclk.fold(offer, history, now_ms=offer["claimByMs"] - 1)
    return {"contract": contract, "room": deal_room, "status": state["status"],
            "frames": len(history), "rejected": len(rejected),
            "asset": offer["asset"], "amount": offer["amount"],
            "job": (offer.get("job") or {}).get("proto", "-")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minutes", type=float, default=0.0,
                    help="keep sampling the offers room for this long first")
    ap.add_argument("--json", metavar="PATH", help="write the raw records here")
    args = ap.parse_args()

    offers, accepts = {}, {}
    invalid, seen_bad = collections.Counter(), set()
    passes = 0
    deadline = time.time() + args.minutes * 60
    while True:
        scan_offers(offers, accepts, invalid, seen_bad)
        passes += 1
        print(f"  pass {passes}: {len(offers)} offers, {len(accepts)} accepts seen",
              flush=True)
        if time.time() >= deadline:
            break
        time.sleep(20)

    records, orphan = [], 0
    for contract, accept in accepts.items():
        offer = offers.get(accept.get("ref"))
        if offer is None:
            orphan += 1          # its offer scrolled out of the window
            continue
        try:
            records.append(fold_deal(offer, accept))
        except tclk.TclkError:
            continue

    status = collections.Counter(r["status"] for r in records)
    done = status["claimed"] + status["refunded"]
    print()
    print("=" * 64)
    print(f"  sampled            {passes} pass(es) over {tclk.OFFERS_ROOM}")
    print(f"  offers seen        {len(offers)}")
    print(f"  accepts seen       {len(accepts)}"
          f"   ({100.0 * len(accepts) / len(offers):.0f}% of offers)"
          if offers else "  accepts seen       0")
    print(f"  deals followed     {len(records)}"
          f"   ({orphan} accepts whose offer had scrolled away)")
    print(f"  settled            {done}"
          f"   ({100.0 * done / len(records):.0f}% of followed)" if records else "")
    for name, n in status.most_common():
        print(f"      {name:<12} {n}")
    if invalid:
        print(f"  distinct frames this library refused: {sum(invalid.values())}")
        for why, n in invalid.most_common(5):
            print(f"      {n:>3}  {why}")
    print("=" * 64)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "passes": passes, "offers": len(offers),
                       "accepts": len(accepts), "deals": records}, fh, indent=2)
        print(f"  raw records -> {args.json}")


if __name__ == "__main__":
    main()
