"""Numbers for the level meters.

Deliberately not a spectrum analyser: the bars only have to look alive while
something plays. Each bar aims at a fresh random target on its own beat and
travels there quickly on the way up, slowly on the way down, which is what
makes a real meter read as a meter. Values are 0..1; the widgets turn them
into pixels.

Pure Python on purpose -- the timer that drives it lives in gui/widgets.py, so
the maths can be tested without a screen.
"""

import random

FLOOR = 0.14        # no bar ever collapses to nothing
ATTACK = 0.55       # of the distance to a higher target, per tick
DECAY = 0.22        # ... and to a lower one
RETARGET = 3        # ticks a target lasts


def new_levels(count):
    return [FLOOR] * count


def new_targets(count, rng=random):
    return [rng.uniform(FLOOR, 1.0) for _ in range(count)]


def step(values, targets, tick, rng=random):
    """One frame. Returns (values, targets), both lists of floats in 0..1."""
    targets = list(targets)
    for i in range(len(values)):
        # Each bar re-aims on its own beat, or they would move in lockstep.
        if (tick + 2 * i) % RETARGET == 0:
            targets[i] = rng.uniform(FLOOR, 1.0)
    out = []
    for v, t in zip(values, targets):
        v += (t - v) * (ATTACK if t > v else DECAY)
        out.append(min(1.0, max(FLOOR, v)))
    return out, targets
