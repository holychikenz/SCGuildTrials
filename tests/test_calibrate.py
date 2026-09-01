"""Unit tests for src/calibrate.py — the dev-only calibration campaign. No network.

The module carries its own golden (``calibrate.selftest``: with every source off
the harness must BE ``trials.simulate_race``), but that one needs the live sheet,
so nothing pinned it offline. R6 gave the campaign two new jobs — it now races the
MERGED rows rather than the manual tab's, and it now skips the uncertainties the
roster has turned into observations — and both are exactly the kind of change that
would leave the harness measuring its own bugs.

WHAT IS PINNED, and why each is exact rather than tolerant:

  - the golden identity, on a roster-backed member: ``_prepare_perturbed`` with
    every source off must reproduce ``trials._prepare_member`` bit for bit. Exact
    ``==`` is right and portable here because the two sides are two live
    computations of the same expressions on the same floats, not a comparison
    against a stored value — the distinction ``tests/test_roster.py``'s golden
    documents.
  - provenance: an OBSERVED quantity must stop being drawn, and a HIDDEN one must
    go on being drawn. Both are asserted over many draws, so a switch that is
    quietly inert cannot pass.
  - R6.4's real invariant: the deterministic score must not depend on
    ``RISK_SIGMA_SYSTEMATIC`` at all.
"""

import random

import pytest

from src import calibrate, config, trials
from src.reader import MemberRow, SkillEntry
from src.roster import MANUAL, ROSTER

_SKILL = "Milking"          # a gathering skill: the tool feeds SPEED
_ENH = "Enhancing"          # the tool feeds SUCCESS, and nothing else does

# One valid Celestial tool per SKILLS entry, resolved out of the catalogue rather
# than typed: ``trials.tool_bonus`` raises on a tool in the wrong slot (a shifted
# header row), so a fixture that puts one item in every slot is rejected by the
# very guard it should be respecting.
_TOOL_FOR = {
    skill: next(
        item for item, stats in config.TOOL_STATS.items()
        if stats[0] == skill and item.startswith("Celestial")
    )
    for skill in config.SKILLS
}


def _roster_member(
    name="Yedic",
    level=120,
    house=6,
    tools=True,
    tool_enhance=5,
    enh_enhance=4,
    shrines=None,
    tool_checkbox=True,
):
    """A member as ``roster.merge`` returns them: fields tagged, roster tools set.

    ``tools=False`` makes them a GEAR-HIDER — the 9 SC / 7 LI members whose tool
    columns are blank while their levels, houses and shrines are full. They are the
    population ``respect_provenance`` must NOT excuse, so they get their own tag.
    """
    skills = {}
    provenance = {"member": ROSTER}
    for skill in config.SKILLS:
        item = _TOOL_FOR[skill] if tools else None
        enhance = None if item is None else (
            enh_enhance if skill == "Enhancing" else tool_enhance
        )
        skills[skill] = SkillEntry(
            level=level, tool=tool_checkbox, top=True, bot=True, house=house,
            tool_item=item, tool_enhance=enhance,
        )
        provenance[f"{skill}.level"] = ROSTER
        provenance[f"{skill}.house"] = ROSTER
        provenance[f"{skill}.tool"] = ROSTER if item is not None else MANUAL
    return MemberRow(
        name=name, main_classes="", flex="", flex_levels=[], skills=skills,
        character_id="14630", captured_at="2026-08-28T11:19:06.697Z",
        shrine_levels={"force": 3, "tempo": 4} if shrines is None else shrines,
        provenance=provenance,
    )


def _prepared(member, skill, src, seed=0, reps=1):
    """``_prepare_perturbed`` ``reps`` times under ``src``, as a list of tuples."""
    rng = random.Random(seed)
    bl = trials.guild_building_skill_levels(skill)
    seat = calibrate.Seat(member=member, skill=skill)
    return [
        calibrate._prepare_perturbed(seat, src, rng, bl, 0, pool=[0, 1, 2, 8])
        for _ in range(reps)
    ]


# --- the golden identity, now on merged rows --------------------------------
def test_unperturbed_prepare_reproduces_prepare_member_on_a_roster_member():
    """Every source off: the harness must BE the shipped model, bit for bit.

    This is ``calibrate.selftest``'s property, moved offline and pointed at the case
    R6 introduced — a member whose tool is a NAMED CATALOGUE ITEM at an OBSERVED
    enhancement level, priced through ``trials.tool_bonus`` rather than through the
    two ``TOOL_SPEED_*_PLUS7`` constants. Before R6 the campaign read the manual
    tab, so this path was never exercised and the golden could not have caught a
    fork in it.
    """
    member = _roster_member()
    for skill in (_SKILL, _ENH, "C.Smithing"):
        bl = trials.guild_building_skill_levels(skill)
        got = _prepared(member, skill, calibrate.Sources())[0]
        want = trials._prepare_member(member, skill, bl)
        assert got == want, skill


def test_unperturbed_prepare_reproduces_prepare_member_for_a_gear_hider():
    """The same identity on the fallback path: no roster tool, so the checkbox."""
    member = _roster_member(tools=False)
    for skill in (_SKILL, _ENH):
        bl = trials.guild_building_skill_levels(skill)
        assert _prepared(member, skill, calibrate.Sources())[0] == \
            trials._prepare_member(member, skill, bl), skill


def test_unperturbed_prepare_uses_the_members_own_shrine_levels():
    """The shrine read is PER MEMBER, not the guild map hoisted once.

    Reading the guild-wide map here — as this module did until R6 — would hand every
    member the modelled level 1 while the roster reports a mean of 2.99 (SC). It
    would also break the identity above the moment the merge started supplying real
    levels, which is the point of pinning it.
    """
    low = _roster_member(name="low", shrines={"force": 0, "tempo": 0})
    high = _roster_member(name="high", shrines={"force": 4, "tempo": 4})
    off = calibrate.Sources()
    _, _, _, _, wp_low, sec_low = _prepared(low, _SKILL, off)[0]
    _, _, _, _, wp_high, sec_high = _prepared(high, _SKILL, off)[0]
    assert wp_high > wp_low        # force -> efficiency -> work power
    assert sec_high < sec_low      # tempo -> action speed -> fewer seconds


# --- provenance: what stops being drawn, and what does not ------------------
def test_respect_provenance_retires_the_observed_tool_enhancement():
    """An OBSERVED enhancement level is data. Drawing it prices a known quantity.

    Enhancing is the sharp case: the tool is the ONLY contributor to
    ``success_bonus``, so any surviving augment draw shows up there and nowhere
    else. With the switch on the value must be exactly ``trials.tool_bonus``'s, on
    every one of 200 draws; with it off the draws must actually move, or the test
    would pass on a switch that does nothing.
    """
    member = _roster_member()
    want = trials.tool_bonus(_ENH, _TOOL_FOR[_ENH], 4)[1]

    on = calibrate.Sources(augment=3, respect_provenance=True)
    assert {p[1] for p in _prepared(member, _ENH, on, reps=200)} == {want}

    off = calibrate.Sources(augment=3, respect_provenance=False)
    assert len({p[1] for p in _prepared(member, _ENH, off, reps=200)}) > 1


def test_respect_provenance_retires_the_observed_house_level():
    """A machine read of the game's own building map is not a transcription."""
    member = _roster_member()
    on = calibrate.Sources(house=1, house_blank=True, respect_provenance=True)
    ref = _prepared(member, _SKILL, calibrate.Sources())[0]
    assert {p[4] for p in _prepared(member, _SKILL, on, reps=200)} == {ref[4]}

    off = calibrate.Sources(house=1, house_blank=True, respect_provenance=False)
    assert len({p[4] for p in _prepared(member, _SKILL, off, reps=200)}) > 1


def test_a_named_roster_tool_makes_the_checkbox_flip_inert_either_way():
    """``tool_flip`` cannot reach a member the roster named a tool for.

    Not because ``respect_provenance`` skips it, but because ``_tool_terms``'s
    precedence never consults the checkbox once the roster has an item — so the flip
    was already dead for those members, in BOTH treatments. Gating it explicitly is
    about stating the intent, not about changing the number, and this test is what
    keeps that claim honest: ``tool_flip=1.0`` flips every single member and moves
    nothing.
    """
    member = _roster_member()
    ref = _prepared(member, _SKILL, calibrate.Sources())[0]
    for rp in (True, False):
        src = calibrate.Sources(tool_flip=1.0, respect_provenance=rp)
        assert {p[5] for p in _prepared(member, _SKILL, src, reps=50)} == {ref[5]}


def test_a_gear_hider_keeps_every_uncertainty_provenance_retires():
    """The population the switch must NOT excuse.

    9 SC and 7 LI members show blank tool columns beside full levels, houses and
    shrines. Their tool tier really is a checkbox guess at an assumed +7, so the
    augment draw and the checkbox flip both still apply — with the switch ON.
    """
    hider = _roster_member(tools=False)
    on = calibrate.Sources(augment=3, tool_flip=1.0, respect_provenance=True)
    assert len({p[5] for p in _prepared(hider, _SKILL, on, reps=200)}) > 1
    assert len({p[1] for p in _prepared(hider, _ENH, on, reps=200)}) > 1


def test_respect_provenance_ignores_a_manual_tagged_house():
    """Per member and per FIELD: a manual house keeps its slip even beside a
    roster-backed tool. The tag is the authority, not the member."""
    member = _roster_member()
    for skill in config.SKILLS:
        member.provenance[f"{skill}.house"] = MANUAL
    on = calibrate.Sources(house=1, respect_provenance=True)
    assert len({p[4] for p in _prepared(member, _SKILL, on, reps=200)}) > 1


def test_provenance_is_ignored_when_the_roster_switches_are_off():
    """``ROSTER_USE_*`` off means the value is NOT roster-priced, tag or no tag."""
    member = _roster_member()
    on = calibrate.Sources(house=1, respect_provenance=True)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "ROSTER_USE_HOUSES", False)
        assert len({p[4] for p in _prepared(member, _SKILL, on, reps=200)}) > 1


# --- the report header, which used to lie about the run it labelled ---------
def test_sources_label_reports_the_boolean_switches():
    """``True == 1`` in Python, and the old label filtered ``v not in (0, 0.0, 1.0)``.

    So ``house_blank``, ``stochastic`` and ``respect_provenance`` were all dropped
    from the label of the very run they governed — and ``house=1`` with them. Every
    figure transcribed into research/ is identified by this string.
    """
    assert calibrate.Sources().label() == "none (golden)"
    label = calibrate.Sources(
        house=1, house_blank=True, stochastic=True, respect_provenance=True
    ).label()
    for expected in ("house=1", "house_blank=True", "stochastic=True",
                     "respect_provenance=True"):
        assert expected in label
    # q_signed defaults to 1.0 and must still be filtered when it is untouched.
    assert "q_signed" not in label
    assert "q_signed=0.9" in calibrate.Sources(q_signed=0.9).label()


def test_ablation_rows_inherit_the_campaigns_provenance_treatment():
    """The control column must be a real second treatment, not a copy of the first.

    A first draft read ``DEFAULT.respect_provenance`` inside ``ablation``, so
    ``--ignore-provenance`` produced a byte-identical table and the R6 "before"
    column was a forgery. Caught by running the campaign twice and noticing the two
    tables agreed to the last digit on every row.
    """
    parties = [[calibrate.Seat(member=_roster_member(), skill=_SKILL)]]
    for rp in (True, False):
        rows = calibrate.ablation(
            parties, reps=2, seed=0,
            src=calibrate.Sources(respect_provenance=rp),
        )
        assert rows, rp
        assert all(s.respect_provenance is rp for _name, s, _cals in rows), rp


# --- R6.4: the recalibration must not leak into the rate model --------------
def test_the_deterministic_score_does_not_depend_on_risk_sigma_systematic():
    """R6 may move ``expected_points`` and ``clear_probability``. Nothing else.

    THE INVARIANT AS THE PLAN STATES IT IS TOO STRONG, and this test is the part of
    it that actually holds. ``config.OPT_OBJECTIVE = "expected"`` means the OPTIMIZER
    maximises ``expected_credit_points``, which reads this constant — so changing
    sigma genuinely can re-seat the parties and move ``credit_points`` with them.
    What must never happen is the score of a FIXED lineup moving: ``credit_points``,
    the tiers and the partial fractions are ``+ - * / floor`` over rates that the
    risk model does not enter. If they move, the recalibration has leaked into the
    rate model, which is the failure R6.4 exists to catch.
    """
    members = [_roster_member(name=f"m{i}", level=110 + i % 9) for i in range(8)]
    skills = ["Milking", "Enhancing"]
    assignment = trials.Assignment(
        parties={"Milking": members[:4], "Enhancing": members[4:]}, bench=[]
    )

    def score(sigma):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(config, "RISK_SIGMA_SYSTEMATIC", sigma)
            return trials.score_assignment(assignment, members, skills=skills)

    lo, hi = score(0.0131), score(0.0122)
    assert lo.total_points == hi.total_points
    assert lo.total_credit_points == hi.total_credit_points
    for a, b in zip(lo.trials, hi.trials, strict=True):
        assert (a.tier_reached, a.partial_fraction, a.credit_points, a.points) == \
               (b.tier_reached, b.partial_fraction, b.credit_points, b.points)
    # And the two figures that MUST move, or the constant is not wired in at all.
    assert lo.total_expected_points != hi.total_expected_points
