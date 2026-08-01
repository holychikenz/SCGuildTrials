"""Calibration campaign: turning the trials model's TIME MARGIN into a PROBABILITY.

DEV-ONLY. Nothing in the shipped pipeline imports this module; it exists to
measure the one number that ``research/risk-aware-objective.md`` §3 leaves as an
assumption, namely ``sigma_eps`` — the fractional error on a party's work rate.

WHY THIS EXISTS
---------------
``src/trials.py`` reports a margin ``m = 1 - tau_T / 3600``: the fraction of the
one-hour budget left unspent when the highest tier was banked. That number is an
ordinal comfort, not a probability. §4.2 of the research note gives the bridge —
under a multiplicative rate shock ``R~ = R * exp(eps)``, the clearing time is
``tau * exp(-eps)`` and so::

    P(tier T holds) = Phi( ln(3600 / tau_T) / sigma_eps )
                    = Phi( -ln(1 - m) / sigma_eps )

which needs exactly one unknown: ``sigma_eps``. This module estimates it, from
the bottom up, by perturbing the model's own inputs and measuring the induced
spread in ``ln tau``.

THE KEY IDENTITY, AND WHY THE ESTIMATOR IS SO SIMPLE
-----------------------------------------------------
A multiplicative shock on the rate is EXACTLY a multiplicative shock on every
clearing time (``tau_t = target_t / R``, and the tier targets are constants). So

    sd( ln tau_t )  IS  sigma_eps

directly — no fitting, no regression. The campaign perturbs inputs, races, and
takes the standard deviation of the log clearing time. That also makes the
model's central assumption *falsifiable*: Model 2 posits ONE sigma for all
tiers, so if ``sd(ln tau_t)`` drifts with ``t``, the single-sigma bridge is
wrong and the reported probability needs a tier-dependent sigma.

WHAT IS PERTURBED (see Sources)
--------------------------------
Each source is a switch, so the campaign can be run one-at-a-time to produce a
VARIANCE BUDGET — which input is worth chasing, and which is noise. The
distinction that matters most is not the size of a source but whether it is

  * INDEPENDENT across members  -> averages down as 1/sqrt(k_eff) over the party
    (~24 members, k_eff 11-24 measured), so a big per-member error can be a
    small party error; or
  * COMMON to the whole party   -> does not average down AT ALL.

Level staleness is modelled as BOTH (a one-sided common drift plus independent
jitter) because a sheet snapshot goes stale for everyone at once, and that
correlated part is what actually moves sigma.

WHAT IS DELIBERATELY *NOT* FOLDED INTO SIGMA
---------------------------------------------
The community buffs. ``config.DOUBLE_CHANCE = 0.25`` is 0.20 community + 0.05
gear; if the gathering buff lapses the party rate drops ~16% in one step. That
is a REGIME, not a Gaussian, and averaging it into sigma would smear a bimodal
risk into a symmetric one. It is run as a labelled scenario instead (see
``scenario_buffs_lapsed``).

BIAS IS ESTIMATED SEPARATELY FROM SIGMA
----------------------------------------
Several sources are one-sided. The model assumes EVERY member carries +7 gear
and a +3 cape (an idealisation — real rosters carry less), which makes it
optimistic; sheet levels only ever go stale downward, which makes it
pessimistic. So the campaign reports ``mean(ln tau_pert / tau_model)`` as a bias
term ``b`` alongside sigma, and the calibrated bridge becomes

    P = Phi( (ln(3600 / tau_T) - b) / sigma_eps )

Reporting sigma without b would produce a confidently wrong probability.

GOLDEN TEST
-----------
:func:`selftest` asserts that with EVERY source switched off this module's race
reproduces ``trials.simulate_race`` — same tier, same clearing times. That is
the ``sigma -> 0`` hard-equality check the research note asks for, and it is what
licenses the perturbed numbers: the harness re-implements the bonus assembly (it
must, since enhancement levels vary per member per slot, which
``config`` constants cannot express), so it has to be pinned against the real
model or it is measuring its own bugs.

USAGE
-----
    python -m src.calibrate                 # full campaign on the live SC lineup
    python -m src.calibrate --reps 20000    # tighter error bars
    python -m src.calibrate --guild li
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Optional

from . import config, trials
from .reader import MemberRow

# ---------------------------------------------------------------------------
# Enhancement multiplier table (research/item-stats.json)
# ---------------------------------------------------------------------------
# config carries only the two levels the shipped model needs (+3, +7). The
# campaign perturbs the enhancement LEVEL, so it needs the whole curve. Loaded
# from the research directory rather than transcribed, because this is a
# dev-only module and a 21-entry table is exactly the thing one mistypes.
_RESEARCH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "research")


def _load_multiplier_table() -> list[float]:
    with open(os.path.join(_RESEARCH, "item-stats.json")) as fh:
        data = json.load(fh)
    table = data["enhancement"]["enhancementLevelTotalBonusMultiplierTable"]
    # Pin the two values config depends on, so a future data refresh that moves
    # the curve fails HERE rather than silently shifting every calibration.
    assert table[7] == config.ENHANCEMENT_MULT_PLUS7, table[7]
    assert table[3] == config.ENHANCEMENT_MULT_PLUS3, table[3]
    return list(table)


MULT = _load_multiplier_table()
MAX_ENHANCE = len(MULT) - 1

# Assumed enhancement levels in the shipped model: +7 on every gear piece,
# +3 on the cape (config's CAPE_SPEED_PLUS3 / *_PLUS7 constants).
ASSUMED_GEAR = 7
ASSUMED_CAPE = 3

# --- Base / per-enhancement-level stat pairs (research/item-stats.md §5) -----
# effectiveStat = base + MULT[level] * per_level. Every pair below reproduces
# its config constant exactly at the assumed level (checked in _selftest_stats).
TOOL_SPEED_HOLY = (0.9, 0.018)
TOOL_SPEED_CELESTIAL = (1.05, 0.021)
TOOL_SUCCESS_HOLY = (0.036, 0.00072)
TOOL_SUCCESS_CELESTIAL = (0.042, 0.00084)
CAPE_SPEED = (0.05, 0.005)
ARMOUR_EFFICIENCY = (0.1, 0.002)
GLOVES_ENHANCING_SPEED = (0.1, 0.002)


def _stat(pair: tuple[float, float], level: int) -> float:
    """``base + MULT[level] * per_level``, clamped to the table's range."""
    level = max(0, min(MAX_ENHANCE, level))
    return pair[0] + MULT[level] * pair[1]


# --- The slots the sheet does not record ------------------------------------
# Scanned out of research/item-stats.json by STAT rather than by name, so this is
# the COMPLETE set of items in the game data that can move a trial rate through a
# slot the sheet has no column for. Values are quoted at +7, the same enhancement
# level the model already assumes for recorded gear.
#
#   skillingSpeed      : Necklace Of Speed          0.04 + 9.1*0.004 = 0.0764
#                        Philosopher's Necklace     0.04 + 9.1*0.004 = 0.0764
#   skillingEfficiency : Necklace Of Efficiency     0.02 + 9.1*0.002 = 0.0382
#                        Philosopher's Necklace     0.02 + 9.1*0.002 = 0.0382
#   gatheringQuantity  : Ring/Earrings Of Gathering 0.02 + 9.1*0.002 = 0.0382
#                        Philosopher's Ring/Earrings          likewise = 0.0382
#
# THE CRITICAL STRUCTURE, which independent per-stat draws cannot express: speed
# and efficiency both come from the ONE neck slot. A member cannot wear Necklace
# of Speed and Necklace of Efficiency together; the Philosopher's Necklace is the
# only way to hold both, and it grants exactly the same values as the specialists.
# So the four reachable neck states are the whole space, and they cap unmodelled
# efficiency at 0.0382 — NOT at whatever half-width one cares to name.
NECK_OPTIONS = [
    (0.0, 0.0),                       # nothing in the slot
    (_stat(TOOL_SPEED_HOLY, 0) * 0 + 0.04 + MULT[7] * 0.004, 0.0),   # Of Speed
    (0.0, 0.02 + MULT[7] * 0.002),                                    # Of Efficiency
    (0.04 + MULT[7] * 0.004, 0.02 + MULT[7] * 0.002),                 # Philosopher's
]
# Ring and earrings are separate slots, so gathering stacks twice.
GATHER_SLOTS = 2
GATHER_OPTIONS = [0.0, 0.02 + MULT[7] * 0.002]


# ---------------------------------------------------------------------------
# Uncertainty sources
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Sources:
    """One campaign's uncertainty budget. Every field is a switch (0 = off).

    The ``+/- x`` figures an officer quotes are read as UNIFORM HALF-WIDTHS over
    integers (levels, house levels and enhancement levels are all integers), so
    ``level_indep=3`` draws uniformly from {-3..+3}, sd = 2 (not 3).

    ``level_common`` is deliberately ONE-SIDED — a sheet snapshot only ever goes
    stale in the direction of members having gained levels — and is drawn
    uniformly from {0..x}, applied to EVERY member of the party at once. That
    correlation is the point: it does not average down over the party, so a
    small common drift outweighs a large independent one.
    """

    level_common: int = 0     # uniform{0..x} levels, SAME for all members
    level_indep: int = 0      # uniform{-x..+x} levels, per member
    house: int = 0            # uniform{-x..+x} on a RECORDED H cell (clamped 0..8)
    house_blank: bool = False # resample a BLANK H cell from the guild's own H
                              # distribution instead of trusting the flat default
    augment: int = 0          # uniform{-x..+x} enhancement levels, per member PER SLOT
    tool_flip: float = 0.0    # probability the celestial/holy checkbox is wrong
    # --- UNMODELLED GEAR ----------------------------------------------------
    # The sheet records a tool, a top and a bottom. It says NOTHING about the
    # neck, ring or earring slots, so the model silently assumes every member
    # wears none. Half-widths below are in ABSOLUTE stat points (0.03 = 3pp).
    gear_speed: float = 0.0        # unrecorded skillingSpeed  (neck slot)
    gear_efficiency: float = 0.0   # unrecorded skillingEfficiency (neck slot)
    gear_gathering: float = 0.0    # unrecorded gatheringQuantity (ring+earrings)
    gear_one_sided: bool = False   # draw uniform(0, x) instead of uniform(-x, x):
                                   # unowned gear can only ADD, never subtract, so
                                   # the honest shape is one-sided — see the note
                                   # in _prepare_perturbed
    gear_slots: bool = False       # ignore the three half-widths and draw the
                                   # ACTUAL item set from research/item-stats.json
    # --- COMMUNITY BUFF MAGNITUDES ------------------------------------------
    # The three live event buffs, each flagged a WORKING ASSUMPTION in config:
    #   gathering  -> +0.20 doubling chance   (COMMUNITY_GATHERING_BUFF_DOUBLE)
    #   production -> +0.15 efficiency        (COMMUNITY_PRODUCTION_EFFICIENCY_BUFF)
    #   enhancing  -> +0.20 action speed      (COMMUNITY_ENHANCING_SPEED_BUFF)
    # Half-widths below are in ABSOLUTE stat points, as for gear.
    #
    # THESE ARE COMMON-MODE, AND THAT IS THE WHOLE POINT. Every gear term above is
    # drawn per member, so a party of 24 averages it down by ~sqrt(k_eff) and even
    # a generous +/-10pp lands at ~1% of party rate. A buff is ONE draw applied to
    # EVERYONE, so it passes through to the party rate undiluted. Point for point,
    # a buff uncertainty is worth several times a gear uncertainty, and the ranking
    # in the variance budget cannot be read off the half-widths alone.
    buff_gathering: float = 0.0    # uncertainty on the +0.20 doubling chance
    buff_production: float = 0.0   # uncertainty on the +0.15 efficiency
    buff_enhancing: float = 0.0    # uncertainty on the +0.20 enhancing speed,
                                   # respecting slot exclusivity
    q_signed: float = 1.0     # turnout probability for a member who volunteered
    q_filled: float = 1.0     # turnout probability for an optimizer-filled seat
    target_cv: float = 0.0    # lognormal CV on the work target (model-form error)
    stochastic: bool = False  # per-action RNG (the ALEATORIC term) — see race()

    def label(self) -> str:
        on = [f"{k}={v}" for k, v in self.__dict__.items()
              if v not in (0, 0.0, 1.0)]
        return ", ".join(on) or "none (golden)"


# The campaign default, assembled from the officers' stated tolerances plus the
# four additions argued for in the accompanying analysis. NOT authoritative —
# it is a stated prior, and the ablation table is what makes it inspectable.
DEFAULT = Sources(
    level_common=0,     # SHEET STALENESS: DELIBERATELY OFF. It is a ONE-SIDED
                        # source — a snapshot can only understate levels, never
                        # overstate them — so including it can only ever move the
                        # reported probability UP. Excluding it therefore makes
                        # every published P a conservative FLOOR: if the sheet is
                        # stale the guild does better than promised, which is the
                        # correct direction for a number officers plan against.
                        # It also removes the campaign's largest unverified
                        # assumption from the answer (it was worth sigma ~0.05 and
                        # a favourable bias of ~0.07, i.e. it was flattering the
                        # thin trials by ~25 points of probability).
    level_indep=0,      # levels are taken as RECORDED. The sheet is the roster of
                        # record; treating its levels as data rather than as an
                        # estimate is the same choice made for houses below.
    house=1,            # RECORDED H cells: a narrow slip, not a guess. The sheet
                        # knows this number (SC records all 96; LI records 29/88).
    house_blank=True,   # BLANK H cells: resampled from the guild's own H spread
    gear_speed=0.03,        # unrecorded neck-slot speed
    gear_efficiency=0.10,   # unrecorded efficiency — NB the item table caps the
                            # true unmodelled envelope at 0.0382 (one neck slot);
                            # see NECK_OPTIONS and the gear_slots cross-check
    gear_gathering=0.05,    # unrecorded ring/earring gathering quantity

    augment=3,          # gear is assumed +7 for all; reality varies
    tool_flip=0.03,     # a few mis-ticked celestial boxes
    target_cv=0.0,      # MODEL-FORM ERROR: DELIBERATELY OFF. The work formulas
                        # are confirmed, not guessed — TotalWork(t,N) =
                        # DifficultyLevel(t)*400*(1+N/100) and the success delta
                        # come from Orvel (2026-07-17) and TARGET_SCALE is pinned
                        # to 1.0 because the 400 coefficient already carries the
                        # scaling. Smearing a Gaussian over confirmed arithmetic
                        # invents uncertainty rather than measuring it, and it was
                        # dominating the answer: at CV=5% it carried 90% of the
                        # variance and was the single largest term in the budget.
                        #
                        # What remains genuinely unconfirmed is NOT a smear but a
                        # short list of NAMED, CHECKABLE constants — GEAR_DOUBLE_
                        # CHANCE (flagged "placeholder until per-member gear is
                        # harvested"), the COMMUNITY_* buff values, points_for_tier,
                        # and the deliberate top/bot-as-efficiency simplification
                        # for Enhancing. Those are priced as SCENARIOS below, where
                        # each can be named, checked and retired individually,
                        # rather than averaged into a sigma that hides which one is
                        # wrong.
    stochastic=True,    # the per-action dice — aleatoric, and NOT assumed small
    # TURNOUT IS DELIBERATELY OFF (q_signed = q_filled = 1.0), and it is the most
    # consequential choice in this file, so it is argued rather than assumed.
    #
    # research/risk-aware-objective.md §2B and §4.3 make turnout the single
    # largest variance term, and measured here it was: sigma 0.049-0.096 against
    # a 0.10 total, i.e. most of the budget. Including it drags the reported
    # probability down hard (Milking 0.994 -> 0.555) and, worse, RE-ORDERS which
    # trial looks riskiest, because the optimizer-filled seats concentrate in one
    # party.
    #
    # It is excluded because of what this tool is FOR: it tells a member WHERE to
    # go and WHEN to switch — it does not predict IF they show up. The guild
    # reports turnout is effectively complete, and the officers' own sheet runs
    # trials as free-assigned. So the published number is a CONDITIONAL
    # probability:
    #
    #     P(tier holds | the assigned party turns up)
    #
    # which is the quantity an officer can actually act on: it isolates the part
    # of the risk that a LINEUP CHANGE can fix. Absence is a different failure
    # with a different remedy (chase the member), and averaging the two produces
    # a number that answers neither question.
    #
    # Flip q_signed/q_filled back below 1.0 to price a guild where turnout is a
    # real risk; the machinery is intact and the ablation still reports it.
)


# ---------------------------------------------------------------------------
# Perturbed member preparation
# ---------------------------------------------------------------------------
@dataclass
class Seat:
    """One party seat: the member, and whether they volunteered for it.

    ``volunteered`` selects between ``Sources.q_signed`` and ``q_filled``. The
    sign-up page's ``status`` field is the source: "assigned" means the member
    ticked the box, "recommended" means the optimizer put them there.
    """

    member: MemberRow
    skill: str
    volunteered: bool = True


def _prepare_perturbed(
    seat: Seat,
    src: Sources,
    rng: random.Random,
    building_levels: int,
    level_drift: int,
    pool: Optional[list[int]] = None,
    buffs: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Optional[tuple[int, float, int, float, int, float]]:
    """Mirror of ``trials._prepare_member`` with per-member/per-slot perturbation.

    Returns the same 6-tuple the real hot loop consumes — ``(level,
    success_bonus, building_levels, double_factor, work_power, action_seconds)``
    — or None when the member contributes nothing (no level, or absent).

    ``level_drift`` is the COMMON staleness drift, passed in rather than drawn
    here precisely because it must be identical across the whole party.

    NB the deliberate asymmetry on turnout: an absentee is dropped from the rate
    sum but the caller still counts them in ``n``. That is the conservative
    reading flagged in research §4.3 — the roster is fixed at sign-up, so a
    no-show still inflates ``effective_target`` through the (1 + N/100) term.
    """
    skill = seat.skill
    member = seat.member

    q = src.q_signed if seat.volunteered else src.q_filled
    if q < 1.0 and rng.random() > q:
        return None  # did not turn up

    level, tool, top, bot, house = trials._resolve_level_and_checks(member, skill)
    if not level or level <= 0:
        return None

    # --- level: common staleness drift + independent jitter -----------------
    level = level + level_drift
    if src.level_indep:
        level += rng.randint(-src.level_indep, src.level_indep)
    if level <= 0:
        return None

    # --- house level --------------------------------------------------------
    # The sheet's per-skill "H" column is a MEASUREMENT, and trials._house_level
    # already uses it; config.DEFAULT_HOUSE_LEVEL is only the blank fallback. So
    # the two cases carry completely different uncertainty and must not share a
    # tolerance — which an earlier revision of this file wrongly did, inflating
    # SC (where nothing is blank) and understating LI (where 2/3 is).
    #
    #   RECORDED cell -> narrow: transcription slips and members upgrading a room
    #                    since the sheet was filled in. src.house is the half-width.
    #   BLANK cell    -> wide: we know nothing. Resampled from the SAME guild's
    #                    own distribution of filled cells for that skill, which is
    #                    the posterior predictive given no information — and which
    #                    also removes the flat default's BIAS for free (LI's filled
    #                    cells average ~3.1 against a default of 4).
    if house is None and src.house_blank and pool:
        house_level = pool[rng.randrange(len(pool))]
    else:
        house_level = trials._house_level(house)
        if src.house and house is not None:
            house_level += rng.randint(-src.house, src.house)
    house_level = max(0, min(config.HOUSE_MAX_LEVEL, house_level))

    # --- tool checkbox ------------------------------------------------------
    if src.tool_flip and rng.random() < src.tool_flip:
        tool = not tool

    # --- enhancement levels, drawn INDEPENDENTLY per slot -------------------
    def enh(assumed: int) -> int:
        if not src.augment:
            return assumed
        return max(0, min(MAX_ENHANCE,
                          assumed + rng.randint(-src.augment, src.augment)))

    speed = _stat(CAPE_SPEED, enh(ASSUMED_CAPE))
    efficiency = 0.0
    success_bonus = 0.0

    # Common-mode buff shifts, drawn ONCE per replicate by the caller and applied
    # identically to every member — which is exactly why they do not average down.
    buff_gathering, buff_production, buff_enhancing = buffs

    if skill == "Enhancing":
        success_bonus += _stat(
            TOOL_SUCCESS_CELESTIAL if tool else TOOL_SUCCESS_HOLY, enh(ASSUMED_GEAR)
        )
        speed += _stat(GLOVES_ENHANCING_SPEED, enh(ASSUMED_GEAR))
        speed += config.COMMUNITY_ENHANCING_SPEED_BUFF + buff_enhancing
        speed += config.HOUSE_ENHANCING_SPEED_PER_LEVEL * house_level
    else:
        speed += _stat(
            TOOL_SPEED_CELESTIAL if tool else TOOL_SPEED_HOLY, enh(ASSUMED_GEAR)
        )
        efficiency += _stat(ARMOUR_EFFICIENCY, enh(ASSUMED_GEAR))
        efficiency += config.HOUSE_EFFICIENCY_PER_LEVEL * house_level
        if skill not in config.GATHERING_SKILLS:
            efficiency += (
                config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF + buff_production
            )

    if top:
        efficiency += _stat(ARMOUR_EFFICIENCY, enh(ASSUMED_GEAR))
    if bot:
        efficiency += _stat(ARMOUR_EFFICIENCY, enh(ASSUMED_GEAR))

    # --- unmodelled gear: the neck, ring and earring slots -------------------
    # The sheet has no column for these, so the shipped model assumes every
    # member wears nothing in them. Two ways to price that:
    #
    #  gear_slots=True  — draw the REAL items (see NECK_OPTIONS / GATHER_SLOTS).
    #    This respects SLOT EXCLUSIVITY, which independent draws cannot: a member
    #    has ONE neck slot, so Necklace of Speed and Necklace of Efficiency are
    #    mutually exclusive, while the Philosopher's Necklace grants both at once.
    #    Speed and efficiency are therefore CORRELATED across members, not
    #    independent, and the correlation is a property of the item table.
    #
    #  otherwise — independent uniform draws of the stated half-widths, which is
    #    the officers' stated tolerance taken at face value.
    #
    # SIDEDNESS MATTERS (cf. level staleness): gear a member does not own cannot
    # subtract from their rate. The truthful shape is one-sided and non-negative,
    # which makes the model PESSIMISTIC and the reported probability a floor. A
    # symmetric draw is only defensible as a proxy for "the assumed baseline gear
    # may itself be wrong in either direction".
    def _gear(half: float) -> float:
        if not half:
            return 0.0
        return rng.uniform(0.0, half) if src.gear_one_sided else rng.uniform(-half, half)

    gather_bonus = 0.0
    if src.gear_slots:
        neck_speed, neck_eff = NECK_OPTIONS[rng.randrange(len(NECK_OPTIONS))]
        speed += neck_speed
        efficiency += neck_eff
        for _ in range(GATHER_SLOTS):
            gather_bonus += GATHER_OPTIONS[rng.randrange(len(GATHER_OPTIONS))]
    else:
        speed += _gear(src.gear_speed)
        efficiency += _gear(src.gear_efficiency)
        gather_bonus = _gear(src.gear_gathering)

    double = 1 + trials.double_chance(skill)
    # gatheringQuantity is a GATHERING-family mechanic; production and enhancing
    # parties carry no doubling term at all, so there is nothing for it to move.
    if trials.double_chance(skill) > 0:
        double = max(1.0, double + gather_bonus + buff_gathering)

    return (
        level,
        success_bonus,
        building_levels,
        double,
        math.floor(trials.work_power(level, efficiency)),
        trials.action_seconds(skill, speed),
    )


# ---------------------------------------------------------------------------
# The race
# ---------------------------------------------------------------------------
def variance_rate(prepared: list[tuple], tier: int) -> float:
    """``V_t`` — the party's work-VARIANCE per second at ``tier``.

    The aleatoric term, derived exactly rather than assumed. Each action is
    ``X = W * S * (1 + D)`` with ``S ~ Bern(p)`` the success roll and
    ``D ~ Bern(delta)`` the doubling roll, independent, so::

        E[X]   = W * p * (1 + delta)                    (= the shipped model)
        E[X^2] = W^2 * p * (1 + 3*delta)                since E[(1+D)^2] = 1+3d
        Var[X] = W^2 * [ p(1+3d) - p^2 (1+d)^2 ]        (-> W^2 p(1-p) at d=0)

    The ACTION COUNT is deterministic (``action_seconds`` is fixed, so a member
    performs exactly tau/a actions in time tau and only the payload is random),
    which is the textbook setting for the CLT — hence a variance RATE, additive
    across members exactly as the drift is.

    ``prepared`` carries ``double = 1 + delta``, so ``(1 + 3*delta)`` is
    ``3*double - 2``.

    FLAGGED ASSUMPTION (research §2A): efficiency is treated as contributing NO
    variance — the capture in research/trial-messages.md shows the engine folding
    efficiency deterministically into progressPerAction. If a later capture shows
    it behaving as an instant-repeat CHANCE, a compound-Poisson term belongs here.
    """
    total = 0.0
    for level, success_bonus, building, double, wp, asec in prepared:
        p = trials.success(level, tier, success_bonus, building)
        total += wp * wp * (p * (3.0 * double - 2.0) - p * p * double * double) / asec
    return total


def race(
    prepared: list[tuple],
    n: int,
    target_mult: float = 1.0,
    max_tier: int = 40,
    rng: Optional[random.Random] = None,
    stochastic: bool = False,
) -> dict[int, float]:
    """Cumulative clearing time per tier, as ``{tier: tau_t}``.

    A tier's entry is the clock reading at which it WOULD be banked, recorded
    whether or not it fits inside the budget — the campaign needs the would-be
    time for the first failed tier too, since ``P(clear t)`` for an unreached
    tier is exactly what the upside of the distribution is made of.

    Deliberately mirrors ``trials.simulate_race``'s arithmetic term for term,
    including the ``sum()`` over a generator in the original factor order (the
    module warns that re-associating it shifts a ULP). ``target_mult`` is the
    model-form shock, applied to the target rather than the rate — algebraically
    identical, and it keeps the rate sum bit-comparable to the real one.

    ``stochastic`` adds the ALEATORIC term: the per-tier clearing time becomes a
    first-passage time rather than a ratio. Under drift ``R`` and variance rate
    ``V``, passage to work level ``Y`` is inverse-Gaussian with mean ``Y/R`` and
    variance ``Y*V/R^3`` (the standard Wald result); it is drawn as a Gaussian,
    which is safe here because each tier absorbs thousands of actions (24 members
    x hundreds of actions each) and the resulting shape parameter is enormous.
    Tiers are treated as sequentially independent — true to first order, since
    the race genuinely restarts its accumulator at each threshold.

    NB this is the term whose size the whole "is the margin a probability"
    question turns on, so it is a SWITCH and not an always-on default: the
    ablation must be able to price it alone.
    """
    taus: dict[int, float] = {}
    cumulative = 0.0
    for tier in range(1, max_tier + 1):
        party_rate = sum(
            trials.success(level, tier, success_bonus, building) * double * wp / asec
            for level, success_bonus, building, double, wp, asec in prepared
        )
        if party_rate <= 0:
            break
        eff_target = trials.effective_target(tier, n, config.TARGET_SCALE) * target_mult
        ttc = eff_target / party_rate
        if stochastic and rng is not None:
            var_rate = variance_rate(prepared, tier)
            if var_rate > 0:
                sd = math.sqrt(eff_target * var_rate / party_rate ** 3)
                ttc = rng.gauss(ttc, sd)
                if ttc <= 0:   # a degenerate draw; the tier cannot take no time
                    ttc = 1e-9
        cumulative += ttc
        taus[tier] = cumulative
        # One tier past the buzzer is enough: everything beyond is unreachable
        # under any shock this campaign draws, and racing to max_tier on a
        # crippled party is pure waste in the inner loop.
        if cumulative > config.TRIAL_TIME_BUDGET_SECONDS * 3:
            break
    return taus


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------
@dataclass
class TrialCalibration:
    """Per-trial campaign output."""

    skill: str
    party_size: int
    model_tier: int
    model_tau: dict[int, float]      # unperturbed clearing times
    margin: float                    # the shipped page's margin at model_tier
    sigma: dict[int, float]          # sd(ln tau_t) per tier  == sigma_eps
    bias: dict[int, float]           # mean(ln tau_t / tau_model_t)
    p_empirical: dict[int, float]    # fraction of reps with tau_t <= budget
    reps: int


def house_pool(members: list[MemberRow], skill: str) -> list[int]:
    """Every RECORDED H level for ``skill`` across the guild, as a resample pool.

    Empty when the guild records none — the caller then falls back to
    ``config.DEFAULT_HOUSE_LEVEL``, exactly as the shipped model does. Drawn from
    the WHOLE roster rather than the party, since a blank cell tells us nothing
    about that member and the guild-wide distribution is the best available prior.
    """
    col = trials._sheet_column(skill)
    return [
        m.skills[col].house
        for m in members
        if col in m.skills and m.skills[col].house is not None
    ]


def run_trial(
    seats: list[Seat],
    src: Sources,
    reps: int,
    seed: int,
    pool: Optional[list[int]] = None,
) -> TrialCalibration:
    """Monte-Carlo one trial's party under ``src`` and return its calibration."""
    skill = seats[0].skill
    n = len(seats)
    building_levels = trials.guild_building_skill_levels(skill)
    budget = config.TRIAL_TIME_BUDGET_SECONDS

    # --- the unperturbed reference, straight from the shipped simulator ------
    party = [s.member for s in seats]
    ref = trials.simulate_race(party, skill)
    model_tau = {
        step.tier: step.cumulative_time
        for step in ref.timeline
        if step.cumulative_time is not None
    }
    margin = trials.time_slack_fraction(ref)

    rng = random.Random(seed)
    logs: dict[int, list[float]] = {}
    cleared: dict[int, int] = {}

    for _ in range(reps):
        # SIGN: one-sided and POSITIVE. A sheet snapshot only goes stale in one
        # direction — members gain levels, they do not lose them — so the truth
        # is that the party is FASTER than the recorded roster suggests. This
        # source therefore contributes a favourable BIAS as well as variance,
        # which is exactly why bias is reported separately from sigma.
        drift = rng.randint(0, src.level_common) if src.level_common else 0
        # ONE draw per replicate, shared by the whole party — a community buff is
        # a property of the world, not of a member.
        buffs = (
            rng.uniform(-src.buff_gathering, src.buff_gathering)
            if src.buff_gathering else 0.0,
            rng.uniform(-src.buff_production, src.buff_production)
            if src.buff_production else 0.0,
            rng.uniform(-src.buff_enhancing, src.buff_enhancing)
            if src.buff_enhancing else 0.0,
        )
        prepared = [
            p for p in (
                _prepare_perturbed(s, src, rng, building_levels, drift, pool, buffs)
                for s in seats
            ) if p is not None
        ]
        if not prepared:
            continue
        target_mult = (
            math.exp(rng.gauss(0.0, src.target_cv)) if src.target_cv else 1.0
        )
        taus = race(prepared, n, target_mult, rng=rng, stochastic=src.stochastic)
        for tier, tau in taus.items():
            logs.setdefault(tier, []).append(math.log(tau))
            if tau <= budget:
                cleared[tier] = cleared.get(tier, 0) + 1

    sigma, bias, p_emp = {}, {}, {}
    for tier, vals in sorted(logs.items()):
        if len(vals) < 2:
            continue
        sigma[tier] = statistics.stdev(vals)
        if tier in model_tau:
            bias[tier] = statistics.fmean(vals) - math.log(model_tau[tier])
        p_emp[tier] = cleared.get(tier, 0) / reps

    return TrialCalibration(
        skill=skill,
        party_size=n,
        model_tier=ref.tier_reached,
        model_tau=model_tau,
        margin=margin,
        sigma=sigma,
        bias=bias,
        p_empirical=p_emp,
        reps=reps,
    )


# ---------------------------------------------------------------------------
# The bridge: margin -> probability
# ---------------------------------------------------------------------------
def phi(z: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def p_from_margin(margin: float, sigma: float, bias: float = 0.0) -> float:
    """``Phi( (-ln(1 - m) - b) / sigma )`` — research §4.2 with a bias term.

    The margin enters as ``-ln(1 - m)``, i.e. the LOG of the slowdown the party
    can absorb, because the shock is multiplicative. For small margins this is
    ~m, which is why the linear reading is a decent approximation on a thin
    lineup and a bad one on a comfortable lineup.
    """
    if sigma <= 0:
        return 1.0 if margin > 0 else 0.0
    return phi((-math.log(max(1e-12, 1.0 - margin)) - bias) / sigma)


def expected_points(cal: TrialCalibration) -> float:
    """E[points] from the empirical survival curve (research §3).

    ``points(T) = 100 + 100*T``, and the tier events are NESTED (any shock that
    raises rates can only move a tier from not-cleared to cleared), so
    ``E[points] = BASE * S(1) + PER_TIER * sum_t S(t)`` — no need for the tier
    distribution itself.
    """
    s = cal.p_empirical
    if not s:
        return 0.0
    return (
        config.TRIAL_POINTS_BASE * s.get(1, 0.0)
        + config.TRIAL_POINTS_PER_TIER * sum(s.values())
    )


# ---------------------------------------------------------------------------
# Golden test
# ---------------------------------------------------------------------------
def _selftest_stats() -> None:
    """Every reconstructed stat must reproduce its config constant at +7 / +3."""
    checks = [
        (_stat(TOOL_SPEED_HOLY, 7), config.TOOL_SPEED_HOLY_PLUS7),
        (_stat(TOOL_SPEED_CELESTIAL, 7), config.TOOL_SPEED_CELESTIAL_PLUS7),
        (_stat(TOOL_SUCCESS_HOLY, 7), config.TOOL_SUCCESS_HOLY_PLUS7),
        (_stat(TOOL_SUCCESS_CELESTIAL, 7), config.TOOL_SUCCESS_CELESTIAL_PLUS7),
        (_stat(CAPE_SPEED, 3), config.CAPE_SPEED_PLUS3),
        (_stat(ARMOUR_EFFICIENCY, 7), config.ARMOUR_EFFICIENCY_PLUS7),
        (_stat(GLOVES_ENHANCING_SPEED, 7), config.GLOVES_ENHANCING_SPEED_PLUS7),
    ]
    for got, want in checks:
        assert abs(got - want) < 1e-12, (got, want)


def selftest(seats: list[Seat]) -> float:
    """sigma -> 0 identity: unperturbed, this module must BE ``simulate_race``.

    Returns the worst relative deviation in clearing time across every tier, and
    asserts the tier reached is identical. The bonus assembly is re-implemented
    here (per-slot enhancement levels cannot be expressed through config's
    scalars), so without this the campaign would be measuring its own arithmetic.
    """
    _selftest_stats()
    skill = seats[0].skill
    n = len(seats)
    building_levels = trials.guild_building_skill_levels(skill)
    rng = random.Random(0)
    off = Sources()
    prepared = [
        p for p in (
            _prepare_perturbed(s, off, rng, building_levels, 0) for s in seats
        ) if p is not None
    ]
    ref = trials.simulate_race([s.member for s in seats], skill)
    ref_prepared = [
        p for p in (
            trials._prepare_member(s.member, skill, building_levels) for s in seats
        ) if p is not None
    ]
    assert len(prepared) == len(ref_prepared), (len(prepared), len(ref_prepared))

    taus = race(prepared, n)
    worst = 0.0
    for step in ref.timeline:
        if step.cumulative_time is None:
            continue
        got = taus[step.tier]
        worst = max(worst, abs(got - step.cumulative_time) / step.cumulative_time)
    budget = config.TRIAL_TIME_BUDGET_SECONDS
    got_tier = max([t for t, v in taus.items() if v <= budget], default=0)
    assert got_tier == ref.tier_reached, (got_tier, ref.tier_reached)
    assert worst < 1e-9, worst
    return worst


# ---------------------------------------------------------------------------
# Loading the shipped lineup
# ---------------------------------------------------------------------------
def load_seats(
    signup_path: str, members: list[MemberRow]
) -> list[list[Seat]]:
    """Rebuild each trial's party from the shipped sign-up plan.

    The sign-up plan (not the unconstrained optimum) is the right subject: it is
    what actually runs, its margins are whatever the real volunteers left, and
    its ``status`` field is the only record of who VOLUNTEERED versus who the
    optimizer filled in — which is what sets each seat's turnout probability.
    """
    with open(signup_path) as fh:
        plan = json.load(fh)
    by_name = {m.name: m for m in members}
    out = []
    for t in plan["trials"]:
        seats = []
        for r in t["roster"]:
            m = by_name.get(r["name"])
            if m is None:
                raise KeyError(
                    f"{r['name']!r} is in the shipped plan but not on the live "
                    "roster — refresh _site/signup.json before calibrating"
                )
            seats.append(
                Seat(member=m, skill=t["skill"],
                     volunteered=r.get("status") == "assigned")
            )
        out.append(seats)
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _fmt_pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:.2f}%"


def report(cals: list[TrialCalibration], src: Sources) -> None:
    print(f"\n=== sources: {src.label()} ===")
    print(f"{'trial':<10} {'N':>3} {'tier':>5} {'margin':>8} {'sigma':>7} "
          f"{'bias':>7} {'P(emp)':>7} {'P(fit)':>7} {'E[pts]':>7} {'det':>5}")
    for c in cals:
        t = c.model_tier
        sig = c.sigma.get(t, float("nan"))
        b = c.bias.get(t, 0.0)
        print(
            f"{c.skill:<10} {c.party_size:>3} {t:>5} {_fmt_pct(c.margin):>8} "
            f"{sig:>7.4f} {b:>+7.4f} {c.p_empirical.get(t, 0.0):>7.3f} "
            f"{p_from_margin(c.margin, sig, b):>7.3f} "
            f"{expected_points(c):>7.1f} "
            f"{trials.points_for_tier(t):>5}"
        )


def report_tier_profile(cal: TrialCalibration) -> None:
    """Is sigma constant across tiers? The single-sigma model lives or dies here."""
    print(f"\n--- {cal.skill}: sigma by tier (Model 2 assumes one sigma) ---")
    print(f"{'tier':>5} {'tau_model':>10} {'margin':>8} {'sigma':>7} {'bias':>7} "
          f"{'P(emp)':>7} {'P(fit)':>7}")
    budget = config.TRIAL_TIME_BUDGET_SECONDS
    for tier in sorted(cal.sigma):
        tau = cal.model_tau.get(tier)
        m = (1 - tau / budget) if tau else None
        sig = cal.sigma[tier]
        b = cal.bias.get(tier, 0.0)
        fit = p_from_margin(m, sig, b) if m is not None else float("nan")
        print(f"{tier:>5} {tau if tau else float('nan'):>10.1f} {_fmt_pct(m):>8} "
              f"{sig:>7.4f} {b:>+7.4f} {cal.p_empirical.get(tier, 0.0):>7.3f} "
              f"{fit:>7.3f}")


def ablation(
    parties: list[list[Seat]], reps: int, seed: int
) -> list[tuple[str, Sources, list[TrialCalibration]]]:
    """One source at a time: the variance budget.

    Sigma adds in QUADRATURE across independent sources, so the single-source
    sigmas here should roughly reproduce the combined one — and where they do
    not, the sources are interacting (the SUCCESS_FLOOR clamp and the
    ``floor(work_power)`` truncation are both non-linear, so some interaction is
    expected and worth seeing).
    """
    d = DEFAULT
    single = [
        ("level (common drift)", Sources(level_common=d.level_common)),
        ("level (independent)", Sources(level_indep=d.level_indep)),
        ("house", Sources(house=d.house)),
        ("augment", Sources(augment=d.augment)),
        ("tool checkbox", Sources(tool_flip=d.tool_flip)),
        ("turnout", Sources(q_signed=d.q_signed, q_filled=d.q_filled)),
        ("model form (target)", Sources(target_cv=d.target_cv)),
        ("STOCHASTIC (per-action)", Sources(stochastic=True)),
    ]
    out = []
    for name, s in single:
        cals = [run_trial(p, s, reps, seed) for p in parties]
        out.append((name, s, cals))
    return out


def scenario_buffs_lapsed(parties: list[list[Seat]], reps: int, seed: int):
    """The community gathering buff lapsing: a REGIME, not a Gaussian.

    ``DOUBLE_CHANCE`` is 0.20 community + 0.05 gear, so a lapse takes the
    gathering multiplier from 1.25 to 1.05 — a 16% rate cut applied to the whole
    party at once, with no offsetting upside. Modelled by temporarily dropping
    the community component, and reported as its own line rather than folded
    into sigma, because a bimodal risk averaged into a symmetric one is a lie
    told with a straight face.
    """
    original = config.DOUBLE_CHANCE
    original_prod = config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF
    try:
        config.DOUBLE_CHANCE = config.GEAR_DOUBLE_CHANCE
        config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF = 0.0
        return [run_trial(p, DEFAULT, reps, seed) for p in parties]
    finally:
        config.DOUBLE_CHANCE = original
        config.COMMUNITY_PRODUCTION_EFFICIENCY_BUFF = original_prod


# ---------------------------------------------------------------------------
# Validating the aleatoric term against a DIRECT action-level simulation
# ---------------------------------------------------------------------------
def direct_tier_check(
    prepared: list[tuple],
    n: int,
    tier: int,
    reps: int = 4000,
    seed: int = 7,
    grid: int = 3000,
) -> tuple[float, float, float, float]:
    """Roll every die, one action at a time, and compare with the Wald formula.

    Returns ``(mean_direct, sd_direct, mean_analytic, sd_analytic)`` for the
    time to clear ``tier`` alone.

    WHY BOTHER, given :func:`variance_rate` is derived exactly? Because the
    derivation rests on THREE things that could each be wrong, and only a direct
    roll tests them jointly: (a) that the CLT has bitten at this action count,
    (b) that first passage is Wald-distributed rather than merely
    mean-Y/R, and (c) that treating the action count as deterministic — the
    member's clock ticks every ``a`` seconds regardless of outcome — is the
    right reading of the engine. If the shipped model's margin is going to be
    published AS A PROBABILITY, the aleatoric floor under it should be measured,
    not asserted.

    METHOD: each member's k-th action lands at ``k * a_m``, and pays
    ``W * S * (1 + D)``. Cumulative party work is evaluated on a time grid and
    the first crossing of the tier target is read off. The grid is the only
    approximation and its resolution is reported by the caller.
    """
    import numpy as np

    rs = np.random.default_rng(seed)
    ttc_det = trials.effective_target(tier, n, config.TARGET_SCALE) / sum(
        trials.success(lv, tier, sb, b) * d * wp / a
        for lv, sb, b, d, wp, a in prepared
    )
    horizon = ttc_det * 3.0
    times = np.linspace(0.0, horizon, grid)
    total = np.zeros((reps, grid))

    for level, success_bonus, building, double, wp, asec in prepared:
        p = trials.success(level, tier, success_bonus, building)
        delta = double - 1.0
        k = int(horizon // asec) + 1
        if k <= 0:
            continue
        succ = rs.random((reps, k)) < p
        dbl = rs.random((reps, k)) < delta if delta > 0 else np.zeros((reps, k), bool)
        work = wp * succ * (1.0 + dbl)
        cum = np.cumsum(work, axis=1)
        # actions completed by time t is floor(t / a); index 0 -> no work yet
        idx = np.floor(times / asec).astype(int)
        idx = np.clip(idx, 0, k)
        padded = np.concatenate([np.zeros((reps, 1)), cum], axis=1)
        total += padded[:, idx]

    target = trials.effective_target(tier, n, config.TARGET_SCALE)
    crossed = total >= target
    # argmax on a boolean row gives the first True; rows that never cross are
    # censored at the horizon and would bias sd downward, so they are dropped
    # and their count surfaced by the caller through a short sample.
    first = np.argmax(crossed, axis=1)
    ok = crossed[np.arange(reps), first]
    tt = times[first[ok]]

    var_rate = variance_rate(prepared, tier)
    rate = sum(
        trials.success(lv, tier, sb, b) * d * wp / a
        for lv, sb, b, d, wp, a in prepared
    )
    sd_analytic = math.sqrt(target * var_rate / rate ** 3)
    return float(tt.mean()), float(tt.std(ddof=1)), ttc_det, sd_analytic


def report_direct_check(seats: list[Seat], tiers: Iterable[int], reps: int = 4000) -> None:
    """Print the direct-vs-Wald comparison for a trial's top few tiers."""
    skill = seats[0].skill
    n = len(seats)
    bl = trials.guild_building_skill_levels(skill)
    rng = random.Random(0)
    prepared = [
        p for p in (_prepare_perturbed(s, Sources(), rng, bl, 0) for s in seats)
        if p is not None
    ]
    print(f"\n--- {skill}: aleatoric term, direct action-level roll vs Wald ---")
    print(f"{'tier':>5} {'mean_dir':>9} {'mean_det':>9} {'sd_direct':>10} "
          f"{'sd_Wald':>9} {'sd/mean':>8}")
    for tier in tiers:
        md, sd, mdet, sda = direct_tier_check(prepared, n, tier, reps=reps)
        print(f"{tier:>5} {md:>9.1f} {mdet:>9.1f} {sd:>10.2f} {sda:>9.2f} "
              f"{sd / mdet:>7.3%}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reps", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=20260801)
    ap.add_argument("--guild", default="sc", choices=sorted(config.TABS))
    ap.add_argument("--signup", default=None,
                    help="path to signup.json (default: _site[/li]/signup.json)")
    ap.add_argument("--no-ablation", action="store_true")
    ap.add_argument("--no-direct", action="store_true",
                    help="skip the action-level validation of the aleatoric term")
    args = ap.parse_args(argv)

    root = os.path.dirname(os.path.dirname(__file__))
    signup_path = args.signup or os.path.join(
        root, "_site" if args.guild == "sc" else os.path.join("_site", args.guild),
        "signup.json",
    )

    from .scraper import scrape_member_tab
    data = scrape_member_tab(config.TABS[args.guild])
    print(f"roster: {data.member_count} members ({config.TABS[args.guild]}), "
          f"fetched {data.fetched_at}")

    parties = load_seats(signup_path, data.members)

    print("\ngolden test (sigma -> 0 must reproduce simulate_race):")
    for p in parties:
        worst = selftest(p)
        print(f"  {p[0].skill:<10} max relative deviation {worst:.2e}  OK")

    if not args.no_direct:
        for p in parties:
            ref = trials.simulate_race([s.member for s in p], p[0].skill)
            top = ref.tier_reached
            report_direct_check(p, range(max(1, top - 2), top + 2))

    cals = [run_trial(p, DEFAULT, args.reps, args.seed) for p in parties]
    report(cals, DEFAULT)

    det = sum(trials.points_for_tier(c.model_tier) for c in cals)
    exp = sum(expected_points(c) for c in cals)
    print(f"\n  deterministic total {det}   E[points] {exp:.1f}   "
          f"bias {exp - det:+.1f}")

    for c in cals:
        report_tier_profile(c)

    if not args.no_ablation:
        print("\n=== variance budget (one source at a time) ===")
        print(f"{'source':<22} " + " ".join(f"{c.skill:>10}" for c in cals))
        for name, _s, acals in ablation(parties, max(1000, args.reps // 4), args.seed):
            row = " ".join(
                f"{a.sigma.get(a.model_tier, float('nan')):>10.4f}" for a in acals
            )
            print(f"{name:<22} {row}")
        combined = " ".join(
            f"{c.sigma.get(c.model_tier, float('nan')):>10.4f}" for c in cals
        )
        print(f"{'ALL (combined)':<22} {combined}")

    print("\n=== scenario: community buffs lapsed (regime, not sigma) ===")
    lapsed = scenario_buffs_lapsed(parties, max(1000, args.reps // 4), args.seed)
    report(lapsed, DEFAULT)
    print(f"  deterministic total under lapse "
          f"{sum(trials.points_for_tier(c.model_tier) for c in lapsed)}"
          f"   E[points] {sum(expected_points(c) for c in lapsed):.1f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
