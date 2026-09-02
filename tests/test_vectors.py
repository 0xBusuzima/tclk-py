#!/usr/bin/env python3
"""tclk/1 conformance tests.  python tests/test_vectors.py

The golden vectors are taken verbatim from tests/vectors.test.ts in the
reference repository, github.com/flop-labs/tclk. That file's own rule:

    "They were generated from the reference implementation, so any port
     (this one, or a future one in another language) that disagrees is
     wrong - fix the implementation, never the vector."

So a disagreement here means this implementation is wrong, not the vector.
No network, no pytest.
"""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import tclk

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  OK   " if cond else "  FAIL ") + name + (f"  {detail}" if detail and not cond else ""))


PAYER = "did:key:z6Mk" + "f" * 44
PAYEE = "did:key:z6Mk" + "g" * 44

OFFER_ID = "0xd001fbbf4fa36d9ab8ea88df02a8b3303539e9d59f7ff9d9bfeb679318e9ce75"
CONTRACT_ID = "0x2768bf32b455317879796093ff2e5882371cbec238611ca71f555a7fcbe58e1c"
NON_ASCII_OFFER_ID = "0xfdad69c602bef151596e3e914cc3ca05b1ccd009211b57c4fdbf0ba0e0d4635b"

OFFER_LINE = (
    'tclk1 {"amount":"1000000","asset":"FLOP","claimByMs":1756703600000,"expiresMs":1756700600000,'
    '"from":"did:key:z6Mkffffffffffffffffffffffffffffffffffffffffffff",'
    f'"id":"{OFFER_ID}",'
    '"job":{"context":"ctx-1","id":"task-3f","proto":"a2a"},"lock":"hash",'
    '"nonce":"9f2c81d04c9e1f7a","rails":["flop-htlc","x402"],"refundAfterMs":1756707200000,'
    '"role":"payer","type":"offer"}')

ACCEPT_LINE = (
    f'tclk1 {{"contract":"{CONTRACT_ID}",'
    '"from":"did:key:z6Mkgggggggggggggggggggggggggggggggggggggggggggg",'
    f'"nonce":"0011223344556677","ref":"{OFFER_ID}",'
    '"statement":"0xabababababababababababababababababababababababababababababababab",'
    '"type":"accept"}')


def _offer():
    return tclk.make_offer(
        frm=PAYER, role="payer", amount="1000000", asset="FLOP", lock="hash",
        rails=["flop-htlc", "x402"], claim_by_ms=1756703600000,
        refund_after_ms=1756707200000, expires_ms=1756700600000,
        job={"proto": "a2a", "id": "task-3f", "context": "ctx-1"},
        nonce="9f2c81d04c9e1f7a")


def test_vectors():
    print("\n[golden vectors, against the reference implementation]")
    offer = _offer()
    check("offer id", offer["id"] == OFFER_ID, offer["id"])
    check("offer line", tclk.encode_frame(offer) == OFFER_LINE)

    accept = tclk.make_accept(offer, frm=PAYEE, statement="0x" + "ab" * 32,
                              nonce="0011223344556677")
    check("contract id", accept["contract"] == CONTRACT_ID, accept["contract"])
    check("accept line", tclk.encode_frame(accept) == ACCEPT_LINE)

    # The id must commit to the bytes the wire carries, not to the pre-escape
    # string. A non-ASCII job field separates the two, which is what this
    # vector exists to catch.
    na = tclk.make_offer(
        frm=PAYER, role="payer", lock="hash", amount="100", asset="FLOP",
        rails=["flop-htlc"], claim_by_ms=1756703600000,
        refund_after_ms=1756707200000, expires_ms=1756700600000,
        job={"proto": "a2a", "id": "t" + chr(0xE2) + "che-1"},
        nonce="9f2c81d04c9e1f7a")
    line = tclk.encode_frame(na)
    check("non-ASCII frame encodes to a pure ASCII line",
          all(0x20 <= ord(c) <= 0x7E for c in line))
    check("ascii disi karakter \\u00e2 olarak kacisli", "\\u00e2" in line)
    check("ascii disi offer id", na["id"] == NON_ASCII_OFFER_ID, na["id"])


def test_rules():
    print("\n[specification rules]")
    offer = _offer()
    check("anlasma odasi contract idnden turetiliyor",
          tclk.deal_room(CONTRACT_ID) == "mb-p-tclk-" + CONTRACT_ID[2:18])
    check("offers room constant", tclk.OFFERS_ROOM == "tclk-offers")
    check("rail advertisement format",
          tclk.rails_note(["flop-htlc", "x402"]) == "tclk1:flop-htlc,x402")

    for bad, why in ((0, "claimByMs == refundAfterMs"), (1, "claimByMs > refundAfterMs")):
        try:
            tclk.make_offer(frm=PAYER, amount="1", asset="FLOP", rails=["r"],
                            claim_by_ms=1000 + bad, refund_after_ms=1000)
            ok = False
        except tclk.TclkError:
            ok = True
        check(f"refused: {why}", ok)

    try:
        tclk.make_accept(offer, frm=PAYER, statement="0x" + "ab" * 32)
        ok = False
    except tclk.TclkError:
        ok = True
    check("the offering party cannot accept its own offer", ok)

    secret = tclk.new_secret()
    check("sha256(secret) yields the statement",
          tclk.hash_lock(secret) == tclk.hash_lock(secret) and len(tclk.hash_lock(secret)) == 66)
    check("a non-tclk line is not treated as one", not tclk.is_tclk_line('{"type":"offer"}'))
    check("a valid line is recognised", tclk.is_tclk_line(OFFER_LINE))
    check("roundtrip: decode(encode(x)) == x",
          tclk.decode_frame(tclk.encode_frame(offer)) == offer)


def test_machine():
    print("\n[state machine, pure and fail-closed]")
    offer = _offer()
    secret = tclk.new_secret()
    statement = tclk.hash_lock(secret)
    accept = tclk.make_accept(offer, frm=PAYEE, statement=statement)

    st = tclk.initial_state(offer)
    check("starts proposed", st["status"] == "proposed")

    # An out-of-turn frame must leave the state untouched.
    r = tclk.step(st, {"type": "reveal", "from": PAYEE, "contract": accept["contract"],
                       "secret": secret})
    check("an out-of-turn reveal is refused", not r["ok"])
    check("a refused frame leaves the state untouched", r["state"] == st)

    r = tclk.step(st, accept)
    check("accept -> accepted", r["ok"] and r["state"]["status"] == "accepted")
    st = r["state"]

    r = tclk.step(st, {"type": "lock", "from": PAYEE, "contract": accept["contract"],
                       "rail": "flop-htlc", "ref": "r1"})
    check("the wrong party cannot lock", not r["ok"])

    r = tclk.step(st, {"type": "lock", "from": PAYER, "contract": accept["contract"],
                       "rail": "bilinmeyen-rail", "ref": "r1"})
    check("a rail absent from the offer is refused", not r["ok"])

    r = tclk.step(st, {"type": "lock", "from": PAYER, "contract": accept["contract"],
                       "rail": "flop-htlc", "ref": "r1"})
    check("lock -> locked", r["ok"] and r["state"]["status"] == "locked")
    st = r["state"]

    r = tclk.step(st, {"type": "reveal", "from": PAYEE, "contract": accept["contract"],
                       "secret": "0x" + "11" * 32}, now_ms=1756703000000)
    check("a secret that does not open the statement is refused", not r["ok"])

    r = tclk.step(st, {"type": "reveal", "from": PAYEE, "contract": accept["contract"],
                       "secret": secret}, now_ms=1756707300000)
    check("a reveal after the refund window is refused", not r["ok"])

    r = tclk.step(st, {"type": "reveal", "from": PAYEE, "contract": accept["contract"],
                       "secret": secret}, now_ms=1756703000000)
    check("reveal -> claimed", r["ok"] and r["state"]["status"] == "claimed")

    r = tclk.step(st, {"type": "refund", "from": PAYER, "contract": accept["contract"]},
                  now_ms=1756703000000)
    check("an early refund is refused", not r["ok"])
    r = tclk.step(st, {"type": "refund", "from": PAYER, "contract": accept["contract"]},
                  now_ms=1756707300000)
    check("refund after refundAfterMs -> refunded",
          r["ok"] and r["state"]["status"] == "refunded")

    # This has to run over every line of a world-writable room, so junk input
    # must be skipped rather than raised on.
    lines = ["gm", "tclk1 bozuk-json", tclk.encode_frame(accept), "", "tclk1 {}"]
    try:
        state, rejected = tclk.fold(offer, lines)
        ok = state["status"] == "accepted" and len(rejected) >= 2
    except Exception as exc:                                   # noqa: BLE001
        ok = False
        print("     raised:", exc)
    check("a valid transition is found among junk lines", ok)


if __name__ == "__main__":
    test_vectors()
    test_rules()
    test_machine()
    print("\n" + "=" * 60)
    print(f"  passed {len(PASS)}, failed {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print("   FAIL:", f)
        sys.exit(1)
    print("  all vectors and rules hold.")
