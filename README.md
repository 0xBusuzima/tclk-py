# tclk-py

An independent Python implementation of [tclk/1][spec], the Technocore Lock
Protocol: hash-locked deal-making for agents that meet in a chat room.

Standard library only. No dependencies.

```python
import tclk

offer = tclk.make_offer(
    frm=my_did, amount="100", asset="FLOP",
    rails=["flop-htlc"], lock="hash",
    claim_by_ms=now + 30 * 60_000,
    refund_after_ms=now + 60 * 60_000,
)
line = tclk.encode_frame(offer)      # 'tclk1 {"amount":"100",...}'
```

## What the protocol does

Two agents meet in a room. One wants work done, the other wants paying, and
neither can afford to go first. If the payer pays, the work may never arrive.
If the worker works, the payment may never arrive. Both hesitations are
reasonable and no amount of promising resolves them.

tclk/1 settles it with a hash lock and a deadline:

| | | |
|---|---|---|
| 1 | `offer` | The payer states terms and two deadlines. |
| 2 | `accept` | The payee mints a secret and publishes **only its hash**. |
| 3 | `lock` | The payer escrows on the named rail, payable to whoever produces the secret. |
| 4 | `reveal` | The payee publishes the secret, and publishing it *is* the claim. |
| | `refund` | Or the refund deadline passes and the payer reclaims. |

Nobody has to trust anybody. The worker will not reveal before the money is
locked, the payer will not lock before the hash is published, and the deadline
bounds the whole thing.

Coordination lives in the room as signed messages. Money lives on a settlement
rail the parties name in the offer. The venue settles nothing and holds no keys.

## What this library covers

The frame layer: canonical JSON, domain-tagged hashes, offer and contract ids,
frame encoding and decoding, and the state machine. Rails are out of scope here,
as they are in the specification itself.

```python
# the payee side
secret    = tclk.new_secret()
statement = tclk.hash_lock(secret)
accept    = tclk.make_accept(offer, frm=their_did, statement=statement)

# both sides derive the same deal room without agreeing one
room = tclk.deal_room(accept["contract"])   # 'mb-p-tclk-2768bf32b4553178'

# fold a whole world-writable room over the machine
state, rejected = tclk.fold(offer, room_lines)
print(state["status"])                      # proposed | accepted | locked | ...
```

`step` and `fold` are pure and fail-closed. An invalid frame returns a reason
and leaves the state untouched; neither ever raises. That matters because these
run over every line of a room full of strangers, where most lines are not yours
and some are junk.

## Correctness

The reference repository ships cross-implementation vectors and states the rule
plainly:

> They were generated from the reference implementation, so any port (this one,
> or a future one in another language) that disagrees is wrong. Fix the
> implementation, never the vector.

All four pass here, along with 32 further checks on the specification's rules
and the state machine.

```
$ python tests/test_vectors.py
  passed 36, failed 0
  all vectors and rules hold.
```

Tracked against upstream. The `receipt` guards landed here after the reference
implementation added them in *reject contradictory receipt outcomes*: a receipt
must name the contract it belongs to, come from a party, and claim the outcome
the contract actually reached. It still makes no transition.

No network, no pytest, no fixtures to download.

### Two details that are easy to get wrong

Both were gotten wrong here first, and the vectors caught both.

**The acceptance core has no `type` field.** The contract id commits to
`from`, `ref`, `statement`, `paymentKey` and `nonce`. The frame gains `type`
afterwards. Include it in the hash and the offer id still matches while the
contract id quietly does not.

**The domain hash covers the escaped canonical JSON.** With a non-ASCII field
the escaped and unescaped forms differ, and the id has to commit to the bytes
the wire actually carries. The reference repository ships a vector for exactly
this case.

## Canonical JSON in Python

The reference implementation sorts keys, emits no whitespace, and escapes
non-ASCII. Python expresses all three as flags:

```python
json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
```

JavaScript sorts by UTF-16 code unit and Python by code point. Field names are
ASCII, so the two agree.

## Before you use this for anything real

These are the upstream project's own words, not a summary of them:

> No rail here holds value. The one that ships records the lifecycle and backs
> it with nothing.

> The adaptor-signature module is unaudited: full-Schnorr, not BIP-340.

> Alpha. Testnet only.

Two more things worth knowing. A deal room is derived from the contract id
rather than agreed, which is convenience and not privacy; the specification says
so directly. And a signature says who wrote a frame, never whether the deal
behind it is real.

This library implements the frame layer faithfully. It cannot make a protocol
safer than the protocol is.

## Scope

Implemented: canonical JSON, `domain_hash`, `offer_id`, `contract_id`,
`deal_room`, `rails_note`, all seven frame types, `encode_frame` / `decode_frame`,
and the `step` / `fold` state machine for hash locks.

Not implemented: point locks are validated and carried through the frames, but
this library does no secp256k1 arithmetic, so it cannot mint or verify a point
statement. Adaptor signatures and settlement rails are likewise out of scope.

## Licence and attribution

Apache-2.0, matching upstream. See `LICENSE` and `NOTICE`.

The tclk/1 protocol, its specification and its reference implementation are the
work of Flop Labs: **[github.com/flop-labs/tclk][spec]**.

This project is not affiliated with, endorsed by, or maintained by Flop Labs. It
is a separate implementation written against the published specification and
checked against the vectors that repository ships.

[spec]: https://github.com/flop-labs/tclk
