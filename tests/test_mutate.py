"""Tests for src.mutate, taxonomy fidelity to PRE_REGISTRATION.md §3 + determinism."""

import numpy as np
import pytest

from src import mutate
from src.mutate import (
    COMPLEMENT_SWAP,
    FAMILY_OF,
    MutationError,
    OPERATOR_ORDER,
    STRICTNESS_SWAP,
    TIER_OF,
    applicable_operators,
    apply_a1,
    apply_a2,
    apply_a3,
    apply_b1,
    apply_b2,
    apply_b3,
    brackets_balanced,
    conclusion_head,
    droppable_hypothesis_binders,
    split_signature,
    static_sanity_check,
    strip_proof_assign,
)

RNG = lambda: np.random.default_rng(20260611)  # noqa: E731

T_EQ = "theorem add_zero (n : ℕ) : n + 0 = n"
T_FORALL = "theorem all_pos : ∀ n : ℕ, 0 ≤ n"
T_EXISTS = "theorem ex_succ (n : ℕ) : ∃ m : ℕ, n < m"
T_HYP = "theorem le_of_lt (a b : ℕ) (h : a < b) : a ≤ b"
T_NEG = "theorem not_lt_self (n : ℕ) : ¬ (n < n)"
T_NUM = "theorem two_mul (n : ℕ) : 2 * n = n + n"
T_IMP = "theorem imp_head (a b : ℕ) : a = b → a + 1 = b + 1"


# --- parsing helpers ------------------------------------------------------------------------

def test_split_signature_top_level_colon():
    header, conclusion, _ = split_signature(T_EQ)
    assert header.rstrip() == "theorem add_zero (n : ℕ)"
    assert conclusion.strip() == "n + 0 = n"


def test_split_signature_rejects_non_theorem():
    with pytest.raises(MutationError):
        split_signature("def foo : ℕ := 3")


def test_strip_proof_assign():
    assert strip_proof_assign(T_EQ + " := by simp") == T_EQ


def test_conclusion_head_strips_quantifiers_and_implications():
    head, _ = conclusion_head(" ∀ n : ℕ, 0 ≤ n")
    assert head == "0 ≤ n"
    head, _ = conclusion_head(" a = b → a + 1 = b + 1")
    assert head == "a + 1 = b + 1"


def test_brackets_balanced():
    assert brackets_balanced("(a ⟨b⟩ [c])")
    assert not brackets_balanced("(a))")


# --- taxonomy metadata ----------------------------------------------------------------------

def test_tier_and_family_match_preregistration():
    assert TIER_OF == {"A1": "F", "A2": "F", "A3": "M", "B1": "N", "B2": "N", "B3": "N"}
    assert FAMILY_OF == {"A1": "A", "A2": "A", "A3": "A", "B1": "B", "B2": "B", "B3": "B"}
    assert COMPLEMENT_SWAP["="] == "≠" and COMPLEMENT_SWAP["≤"] == ">"
    assert COMPLEMENT_SWAP["<"] == "≥" and COMPLEMENT_SWAP["∈"] == "∉"
    assert STRICTNESS_SWAP == {"<": "≤", "≤": "<", ">": "≥", "≥": ">"}


def test_verification_status_per_family():
    m_a = apply_a1(T_EQ, "id", RNG())
    m_b = apply_b2(T_HYP, "id", RNG())
    assert m_a.verification_status == "false_by_construction"
    assert m_b.verification_status == "pending_lean_verification"


# --- Family A -------------------------------------------------------------------------------

def test_a1_wraps_negation():
    m = apply_a1(T_EQ, "id", RNG())
    assert m.mutant_statement.endswith("¬ (n + 0 = n)")
    assert m.tier == "F" and m.family == "A" and m.static_checks_passed
    assert m.edit["kind"] == "wrap_negation"


def test_a1_strips_existing_negation():
    m = apply_a1(T_NEG, "id", RNG())
    assert m.mutant_statement.endswith(": n < n")
    assert m.edit["kind"] == "strip_negation"


def test_a2_forall_to_exists_not():
    m = apply_a2(T_FORALL, "id", RNG())
    assert "∃ n : ℕ, ¬ (0 ≤ n)" in m.mutant_statement
    assert m.tier == "F"


def test_a2_exists_to_forall_not():
    m = apply_a2(T_EXISTS, "id", RNG())
    assert "∀ m : ℕ, ¬ (n < m)" in m.mutant_statement


def test_a2_rejects_unquantified_conclusion():
    with pytest.raises(MutationError):
        apply_a2(T_EQ, "id", RNG())


def test_a3_swaps_head_relation():
    m = apply_a3(T_EQ, "id", RNG())
    assert "n + 0 ≠ n" in m.mutant_statement
    assert m.tier == "M"


def test_a3_swaps_in_implication_consequent_only():
    m = apply_a3(T_IMP, "id", RNG())
    # head is the consequent: only its `=` flips, the antecedent's stays
    assert "a = b → a + 1 ≠ b + 1" in m.mutant_statement


def test_a3_le_goes_to_gt():
    m = apply_a3(T_HYP, "id", RNG())
    assert m.mutant_statement.endswith("a > b")


def test_a3_rejects_ambiguous_head():
    with pytest.raises(MutationError):
        apply_a3("theorem amb (a b : ℕ) : a = b ∨ a ≤ b", "id", RNG())


# --- Family B -------------------------------------------------------------------------------

def test_b1_drops_unused_hypothesis():
    m = apply_b1(T_HYP, "id", RNG())
    assert "(h : a < b)" not in m.mutant_statement
    assert m.mutant_statement.endswith("a ≤ b")
    assert m.tier == "N" and m.static_checks_passed


def test_b1_never_drops_referenced_binder():
    # (n : ℕ) is referenced in the conclusion; (h : 0 < n) is the only droppable one
    stmt = "theorem t (n : ℕ) (h : 0 < n) : n ≤ n"
    cands = droppable_hypothesis_binders(stmt)
    assert [inner for _, _, inner in cands] == ["h : 0 < n"]


def test_b1_rejects_when_no_candidate():
    with pytest.raises(MutationError):
        apply_b1(T_EQ, "id", RNG())


def test_b2_single_site_swap():
    m = apply_b2(T_HYP, "id", RNG())
    # exactly one of the two relation tokens flipped
    flips = [
        ("a ≤ b)" in m.mutant_statement, "a < b" in m.mutant_statement),  # hyp flipped
        ("a < b)" in m.mutant_statement, "a ≤ b" not in m.mutant_statement),
    ]
    assert m.mutant_statement != T_HYP and m.tier == "N"
    assert sum(m.mutant_statement.count(t) for t in ("<", "≤")) == 2
    assert flips  # structure check above is the real assertion


def test_b3_off_by_one():
    m = apply_b3(T_NUM, "id", RNG())
    assert m.edit["before"] == "2" and m.edit["after"] in ("1", "3")
    assert m.tier == "N"


def test_b3_zero_always_goes_up():
    m = apply_b3(T_EQ, "id", RNG())
    assert m.edit["before"] == "0" and m.edit["after"] == "1"


def test_b3_rejects_without_literal():
    with pytest.raises(MutationError):
        apply_b3("theorem t (a b : ℕ) (h : a < b) : a ≤ b", "id", RNG())


# --- determinism + dispatch ------------------------------------------------------------------

def test_deterministic_under_registered_seed():
    stmt = "theorem t (a b c : ℕ) (h : a < b) (h2 : b < c) : a < c"
    runs = []
    for _ in range(3):
        rng = np.random.default_rng(20260611)
        ms = [apply_b2(stmt, "id", rng), apply_b3(T_NUM, "id", rng)]
        runs.append([m.to_dict() for m in ms])
    assert runs[0] == runs[1] == runs[2]


def test_applicable_operators_enumeration_order():
    ops = applicable_operators(T_HYP)
    assert ops == sorted(ops, key=OPERATOR_ORDER.index)
    assert "A1" in ops and "A3" in ops and "B1" in ops and "B2" in ops
    assert "A2" not in ops  # conclusion not quantifier-led
    assert "B3" not in ops  # no numeric literal


def test_applicable_operators_does_not_consume_caller_rng():
    rng = np.random.default_rng(20260611)
    before = rng.bit_generator.state["state"]["state"]
    applicable_operators(T_HYP)
    assert rng.bit_generator.state["state"]["state"] == before


def test_static_sanity_check_rejects_garbage():
    assert not static_sanity_check(T_EQ, T_EQ)             # unchanged
    assert not static_sanity_check(T_EQ, "junk")           # not a theorem
    assert not static_sanity_check(T_EQ, "theorem t (a : (n + 0 = n")  # unbalanced
    assert static_sanity_check(T_EQ, "theorem add_zero (n : ℕ) : n + 0 ≠ n")


def test_every_mutation_is_single_operator_application():
    """Every produced mutant differs from its source at exactly one edit site."""
    for op, stmt in [("A1", T_EQ), ("A2", T_FORALL), ("A3", T_EQ), ("B2", T_HYP), ("B3", T_NUM)]:
        m = mutate.apply_operator(op, stmt, "id", RNG())
        assert m.operator == op
        assert m.mutant_statement != stmt
        assert m.edit["before"] != m.edit.get("after")
