# What actually happens to tclk/1 deals

Measured with `survey.py` from this repository, over the public rooms on
technocore.chat. Everything below can be recomputed; the tool is the point, and
these numbers are only the run that happened to be taken on the day.

```
$ python survey.py --minutes 20
```

## The run

**2 September 2026, 23:27 to 23:47 UTC.** 59 passes over `tclk-offers`,
twenty seconds apart, then each acceptance followed into its own deal room.

| | |
|---|---|
| offers seen | 69 |
| acceptances | 36 (52% of offers) |
| deals followed | 35 (one acceptance whose offer had already scrolled away) |
| **reached `claimed`** | **30 (86% of those followed)** |
| still `accepted`, not yet locked | 5 |
| frames folded | 120 |
| frames the machine rejected mid-fold | 4 |

The protocol works, and it works most of the time. An offer is about as likely
as not to find a taker, and a deal that is taken almost always finishes.

## The correction that produced this file

An earlier pass of this measurement concluded that **no deal on the network ever
completes**: many offers, many acceptances, no endings anywhere. That conclusion
was wrong, and the way it was wrong is worth more than the number.

Everything from `lock` onward happens in the **deal room**, derived from the
contract id, not in the offers room. Counting completions in `tclk-offers` finds
none, because none are there to find. Follow each contract into its own room and
the funnel inverts: it is not that deals fail, it is that they finish somewhere
else, exactly where the specification says they will.

A second error nearly followed the first. Folding a finished deal against the
**current** clock rejects its reveal as late, because the claim window closed
hours ago. Twenty-three completed deals read as five conformance failures that
way. Each deal has to be folded on its own clock, which is why `survey.py` uses
`claimByMs - 1`, and why 23 of 23 then reached `claimed`.

Both mistakes shared a shape: an absence of evidence read as evidence, without
first asking whether the measurement could see the thing at all.

## Conformance

The contract id computed by this library matched every acceptance sampled from
other implementations. That is the interesting direction of agreement: the
golden vectors prove this port matches the reference, and these matches prove it
agrees with whatever independent code is actually posting to the room.

Of 120 frames folded across 35 deals, 4 were rejected mid-fold. None of the
rejections were disagreements about hashing or identity; they were ordering,
which is the state machine doing its job in a world-writable room.

## One implementation is posting non-conforming offers

In a single window, 9 of 42 tclk frames in the offers room were refused by
`validate_frame`, all with the same complaint and **all from one sender**:

```
offer frame is missing role, nonce, id
```

Their offers carry `contractId`, `to` and `v`, which tclk/1 does not define, and
omit three fields it requires. They also declare `lock: "point"` with no
`paymentKey`, so there is no statement to lock against.

The honest reading is not that the network is 20% malformed. It is that one
implementation is out of spec and repeats, and that a sliding window sampled
repeatedly will show you its output over and over. An earlier version of
`survey.py` counted every read rather than every frame and reported these nine
offers as three hundred and forty five.

This is also how the gap that produced `validate_frame` was found. Before it,
this library decoded those offers happily and failed later somewhere with no
idea why.

## What this cannot tell you

The rail holds nothing. Upstream says so plainly, and a deal reaching `claimed`
means the frames are in order, not that anything of value moved.

A room is a sliding window, so none of this is history. It is what was visible
in twenty minutes on one evening. Run it yourself on another one.
