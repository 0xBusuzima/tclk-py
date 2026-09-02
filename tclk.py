# -*- coding: utf-8 -*-
"""tclk/1, the Technocore Lock Protocol, in Python.

Specification and reference implementation (TypeScript):
https://github.com/flop-labs/tclk

Two agents meet in a chat room. One wants work done, the other wants paying,
and neither can afford to go first. tclk/1 settles that with a hash lock and a
deadline, run over a room both agents can already reach. It is a convention
layer, not a service: coordination lives in the room as signed messages, money
lives on a settlement rail the parties name in the offer, and the venue settles
nothing and holds no keys.

This module implements the frame layer: canonical JSON, domain-tagged hashes,
offer and contract ids, and the state machine. Rails are deliberately out of
scope here, as they are in the specification itself.

Correctness is not a matter of opinion. tests/test_vectors.py checks this module
against the cross-implementation vectors published in the reference repository,
whose own rule is that any port disagreeing with them is wrong.

Standard library only.
"""
import hashlib
import json
import re
import secrets
import time

__version__ = "0.1.0"

TCLK_DOMAIN = "FLOP::tclk::v1"
TCLK_PREFIX = "tclk1 "
MAX_FRAME_CHARS = 4096          # the room's message cap

OFFERS_ROOM = "tclk-offers"     # where public offers rest

HEX32 = re.compile(r"^0x[0-9a-f]{64}$")
HEX33 = re.compile(r"^0x[0-9a-f]{66}$")

FRAME_TYPES = ("offer", "accept", "lock", "reveal", "refund", "cancel", "receipt")


class TclkError(ValueError):
    """An invalid frame or an invalid construction. `step` never raises this."""


# ------------------------------------------------------------ canonical --
def canonical_json(value) -> str:
    """Produce the same bytes as the reference implementation's canonicalJson.

    Sorted keys, no whitespace between tokens, non-ASCII escaped as \\uXXXX.
    Python expresses all three as flags on json.dumps:

        sort_keys=True          key order
        separators=(",", ":")   no whitespace
        ensure_ascii=True       \\uXXXX escaping

    JS `.sort()` orders by UTF-16 code unit and Python's `sorted` by code point;
    field names are ASCII, so the two agree.

    Fields carrying None (undefined in JS) never reach the wire, so they are
    stripped where frames are built rather than here.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _strip_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def domain_hash(tag: str, payload: str) -> str:
    """0x + sha256("FLOP::tclk::v1|<tag>|<payload>") as lowercase hex.

    The payload is the ESCAPED canonical JSON, not the pre-escape string. The
    reference repository ships a vector specifically to catch this: with a
    non-ASCII job field the two forms differ, and the id has to commit to the
    bytes the wire actually carries.
    """
    material = f"{TCLK_DOMAIN}|{tag}|{payload}".encode("utf-8")
    return "0x" + hashlib.sha256(material).hexdigest()


# ------------------------------------------------------------------ ids --
def offer_id(fields: dict) -> str:
    """The offer id: over every offer field except its own `id`."""
    return domain_hash("offer", canonical_json(_strip_none(fields)))


def contract_id(offer: dict, accept_core: dict) -> str:
    """The contract id: the full offer bound to the acceptance core.

    Per the specification the acceptance side covers `from`, `ref`, `statement`,
    `paymentKey` and `nonce`. It does NOT carry `type`, which the frame gains
    afterwards, and it cannot carry `contract`, which is what this computes.
    """
    return domain_hash("contract", canonical_json(
        {"offer": _strip_none(offer), "accept": _strip_none(accept_core)}))


def deal_room(contract: str) -> str:
    """The deal room name, derived from the contract id so both sides compute
    it without agreeing one. `mb-` makes signatures mandatory and `p-` keeps it
    unlisted. Unlisted is not confidential, and the specification says so.
    """
    if not HEX32.match(contract or ""):
        raise TclkError("contract id must be 0x plus 64 hex characters")
    return "mb-p-tclk-" + contract[2:18]


# --------------------------------------------------------------- frames --
def new_nonce() -> str:
    return secrets.token_hex(8)


def new_secret() -> str:
    """A preimage for the payee to mint. Only its hash is ever published."""
    return "0x" + secrets.token_hex(32)


def hash_lock(secret: str) -> str:
    """The statement for a hash lock: sha256 over the secret's bytes."""
    if not HEX32.match(secret or ""):
        raise TclkError("secret must be 0x plus 64 hex characters")
    return "0x" + hashlib.sha256(bytes.fromhex(secret[2:])).hexdigest()


def make_offer(*, frm, amount, asset, rails, claim_by_ms, refund_after_ms,
               role="payer", lock="hash", payment_key=None, expires_ms=None,
               job=None, nonce=None) -> dict:
    """Build an offer frame and compute its id."""
    if role not in ("payer", "payee"):
        raise TclkError("role must be payer or payee")
    if lock not in ("hash", "point"):
        raise TclkError("lock must be hash or point")
    if lock == "point" and not (payment_key and HEX33.match(payment_key)):
        raise TclkError("a point lock needs a 0x plus 66 hex paymentKey")
    if not rails:
        raise TclkError("name at least one rail")
    # Strict, and equality is refused too: if the two coincided, a reveal and a
    # refund would both be valid at the same instant.
    if not claim_by_ms < refund_after_ms:
        raise TclkError("claimByMs must be strictly less than refundAfterMs")

    fields = _strip_none({
        "type": "offer",
        "from": frm,
        "role": role,
        "amount": str(amount),
        "asset": asset,
        "lock": lock,
        "paymentKey": payment_key,
        "rails": list(rails),
        "claimByMs": int(claim_by_ms),
        "refundAfterMs": int(refund_after_ms),
        "expiresMs": int(expires_ms) if expires_ms is not None else None,
        "job": job,
        "nonce": nonce or new_nonce(),
    })
    return dict(fields, id=offer_id(fields))


def make_accept(offer: dict, *, frm, statement, payment_key=None, nonce=None) -> dict:
    """Build an accept frame. The payee mints a secret and publishes its hash."""
    if offer.get("lock") == "point":
        if not (statement and HEX33.match(statement)):
            raise TclkError("a point lock needs a 0x plus 66 hex statement")
        if not payment_key:
            raise TclkError("a point lock needs the acceptor's paymentKey")
    elif not HEX32.match(statement or ""):
        raise TclkError("a hash lock needs a 0x plus 64 hex statement")
    if frm == offer.get("from"):
        raise TclkError("the offering party cannot accept its own offer")

    core = _strip_none({
        "from": frm,
        "ref": offer["id"],
        "statement": statement,
        "paymentKey": payment_key,
        "nonce": nonce or new_nonce(),
    })
    return dict(core, type="accept", contract=contract_id(offer, core))


def encode_frame(frame: dict) -> str:
    """Render a frame for the wire: 'tclk1 ' plus escaped canonical JSON."""
    line = TCLK_PREFIX + canonical_json(_strip_none(frame))
    if len(line) > MAX_FRAME_CHARS:
        raise TclkError(f"frame is {len(line)} characters, cap is {MAX_FRAME_CHARS}")
    if not all(0x20 <= ord(c) <= 0x7E for c in line):
        raise TclkError("frame line contains non-printable-ASCII characters")
    return line


def is_tclk_line(text: str) -> bool:
    return isinstance(text, str) and text.startswith(TCLK_PREFIX)


def decode_frame(text: str) -> dict:
    if not is_tclk_line(text):
        raise TclkError("not a tclk/1 line")
    try:
        frame = json.loads(text[len(TCLK_PREFIX):])
    except json.JSONDecodeError:
        raise TclkError("frame is not valid JSON") from None
    if not isinstance(frame, dict) or frame.get("type") not in FRAME_TYPES:
        raise TclkError("unknown frame type")
    return frame


# -------------------------------------------------------- state machine --
TRANSITIONS = {
    "proposed":  {"accept": "accepted", "cancel": "cancelled"},
    "accepted":  {"lock": "locked", "cancel": "cancelled"},
    "locked":    {"reveal": "claimed", "refund": "refunded"},
    "claimed":   {},
    "refunded":  {},
    "cancelled": {},
}


def initial_state(offer: dict) -> dict:
    return {"status": "proposed", "offer": offer, "contract": None}


def step(state: dict, frame: dict, now_ms=None) -> dict:
    """Fold one frame onto the state.

    Pure and fail-closed: anything invalid returns {"ok": False, "reason": ...}
    and leaves the state untouched. It never raises, because this has to run
    over every line of a world-writable room, where most lines are not yours
    and some are junk.
    """
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    out = dict(state)

    def no(reason):
        return {"ok": False, "reason": reason, "state": state}

    kind = frame.get("type")
    if kind == "receipt":
        return {"ok": True, "state": state}          # informational, not a transition
    if kind not in TRANSITIONS.get(state.get("status", "proposed"), {}):
        return no(f"'{kind}' is not valid while {state.get('status')}")

    offer = state.get("offer") or {}
    if kind == "accept":
        if frame.get("ref") != offer.get("id"):
            return no("this acceptance refers to a different offer")
        if frame.get("from") == offer.get("from"):
            return no("the offering party cannot accept its own offer")
        out.update(status="accepted", accept=frame, contract=frame.get("contract"),
                   statement=frame.get("statement"), payee=frame.get("from"))
    elif kind == "lock":
        if frame.get("from") != offer.get("from"):
            return no("only the offering party locks")
        if frame.get("contract") != state.get("contract"):
            return no("this lock belongs to a different contract")
        if frame.get("rail") not in (offer.get("rails") or []):
            return no("rail was not named in the offer")
        out.update(status="locked", lock=frame, rail=frame.get("rail"))
    elif kind == "reveal":
        if frame.get("from") != state.get("payee"):
            return no("only the accepting party reveals")
        if frame.get("contract") != state.get("contract"):
            return no("this reveal belongs to a different contract")
        if now_ms >= int(offer.get("refundAfterMs", 0)):
            return no("the refund window has opened, the reveal is late")
        secret = frame.get("secret") or ""
        if not HEX32.match(secret):
            return no("secret is not 0x plus 64 hex characters")
        if hash_lock(secret) != state.get("statement"):
            return no("secret does not open the statement")
        out.update(status="claimed", secret=secret)
    elif kind == "refund":
        if frame.get("from") != offer.get("from"):
            return no("only the offering party is refunded")
        if now_ms < int(offer.get("refundAfterMs", 0)):
            return no("the refund window has not opened yet")
        out.update(status="refunded")
    elif kind == "cancel":
        if frame.get("from") not in (offer.get("from"), state.get("payee")):
            return no("only a party to the deal may cancel")
        out.update(status="cancelled")

    return {"ok": True, "state": out}


def fold(offer: dict, lines, now_ms=None):
    """Fold a room's lines onto the state.

    Lines that are not tclk/1, and frames that do not apply, are skipped rather
    than raised on. Returns the final state and a list of what was rejected and
    why, so a caller can see the traffic it did not act on.
    """
    state = initial_state(offer)
    rejected = []
    for text in lines:
        if not is_tclk_line(text):
            continue
        try:
            frame = decode_frame(text)
        except TclkError as exc:
            rejected.append((str(text)[:60], str(exc)))
            continue
        result = step(state, frame, now_ms=now_ms)
        if result["ok"]:
            state = result["state"]
        else:
            rejected.append((frame.get("type"), result["reason"]))
    return state, rejected


def rails_note(rails) -> str:
    """The rail advertisement for a DID note: 'tclk1:flop-htlc,x402'.

    A routing hint, not proof. Notes are world-writable, so anyone can write
    one. The first signed frame is the proof.
    """
    return "tclk1:" + ",".join(rails)
