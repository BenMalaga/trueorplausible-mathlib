"""Mutation engine for TrueOrPlausible, implements PRE_REGISTRATION.md §3 exactly.

Each benchmark item is a single standalone Lean 4 statement; mutants are produced by
exactly ONE operator application per item. Two families, three tiers (locked):

Family A, falsifying by construction (the primary set; no Lean check needed):
  A1  negate the conclusion: wrap the conclusion in `¬ (...)`, or strip an outermost `¬`   [F]
  A2  quantifier negation in the conclusion: `∀ x, P` → `∃ x, ¬ P`; `∃ x, P` → `∀ x, ¬ P`  [F]
  A3  complementary-relation swap on the conclusion's head relation:
      `=`↔`≠`, `≤`↔`>`, `<`↔`≥`, `∈`↔`∉` (single unambiguous site)                          [M]

Family B, truth-uncertain near-misses (Tier N; REQUIRE machine verification before any
use as a "false" label, see verification_status below):
  B1  drop one explicit hypothesis binder `(h : P)` whose bound names are unused elsewhere [N]
  B2  strict ↔ non-strict swap: `<`↔`≤`, `>`↔`≥` (single site, chosen by the shared RNG)   [N]
  B3  off-by-one: one numeric literal n → n+1 or n−1 (site + direction by the shared RNG)  [N]

verification_status (Lean verification is DEFERRED, no Lean build is run here, per the
pre-registered fallback protocol in §3):
  - Family A mutants:  "false_by_construction"  (assumes the source theorem's hypotheses
    are jointly satisfiable; a ≥50-item spot-check is pre-registered if a Lean pass runs)
  - Family B mutants:  "pending_lean_verification"  (NEVER usable as a false label until a
    one-time Lean pass confirms falsity; if that pass never runs, v1 ships Family A only)
  - unmodified truths: "library_proved" (every source statement carries a proof in Mathlib4
    at the pinned commit)

Determinism: operators take no global state. Site choices inside B1/B2/B3 draw from the
caller-supplied numpy Generator, src.build_benchmark passes the single registered stream
(seed 20260611) through sampling and mutation in a fixed documented order.

Static (pure-Python) sanity checks only, parse/identifier checks, no elaboration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- Lean surface lexicon -------------------------------------------------------------------

OPEN_BRACKETS = "([{⟨⦃«"
CLOSE_BRACKETS = ")]}⟩⦄»"
_BRACKET_OF = dict(zip(OPEN_BRACKETS, CLOSE_BRACKETS))

#: A3, complementary-relation pairs ("and their inverses" → the map is symmetric).
COMPLEMENT_SWAP = {
    "=": "≠", "≠": "=",
    "≤": ">", ">": "≤",
    "<": "≥", "≥": "<",
    "∈": "∉", "∉": "∈",
}

#: B2, strictness toggles (same direction, strict ↔ non-strict).
STRICTNESS_SWAP = {"<": "≤", "≤": "<", ">": "≥", "≥": ">"}

#: Tokens that mark a binder type as a plausible *hypothesis* (Prop-like) for B1.
_PROP_MARKERS = set("=≠≤<≥>∈∉⊆⊂¬∣∥≡≈∼⋖") | {"→", "↔", "∧", "∨", "∀", "∃"}

STATEMENT_RE = re.compile(r"^\s*(theorem|lemma)\s", re.DOTALL)


class MutationError(ValueError):
    """Raised when an operator is not applicable to a statement."""


# --- Parsing helpers (static; no Lean) ------------------------------------------------------

def bracket_depth_scan(s: str):
    """Yield (index, char, depth) where depth counts open brackets BEFORE consuming char."""
    depth = 0
    for i, ch in enumerate(s):
        if ch in OPEN_BRACKETS:
            yield i, ch, depth
            depth += 1
        elif ch in CLOSE_BRACKETS:
            depth -= 1
            yield i, ch, depth
        else:
            yield i, ch, depth


def brackets_balanced(s: str) -> bool:
    stack = []
    for ch in s:
        if ch in _BRACKET_OF:
            stack.append(_BRACKET_OF[ch])
        elif ch in CLOSE_BRACKETS:
            if not stack or stack[-1] != ch:
                return False
            stack.pop()
    return not stack


def split_signature(stmt: str):
    """Split a `theorem`/`lemma` statement at the top-level `:` into (header, conclusion).

    The header holds the keyword, name, and binder groups; the conclusion is the full
    proposition after the first depth-0 `:` (that is not part of `:=`). Returns
    (header, conclusion, colon_index). Raises MutationError if no such colon exists.
    """
    if not STATEMENT_RE.match(stmt):
        raise MutationError("not a theorem/lemma statement")
    for i, ch, depth in bracket_depth_scan(stmt):
        if ch == ":" and depth == 0:
            if i + 1 < len(stmt) and stmt[i + 1] == "=":
                raise MutationError("hit `:=` before a top-level type colon")
            return stmt[:i], stmt[i + 1 :], i
    raise MutationError("no top-level `:` found")


def strip_proof_assign(stmt: str) -> str:
    """Drop a trailing ` := ...` proof body if the row carries one (statement text only)."""
    for i, ch, depth in bracket_depth_scan(stmt):
        if ch == ":" and depth == 0 and i + 1 < len(stmt) and stmt[i + 1] == "=":
            return stmt[:i].rstrip()
    return stmt


def _tokens_with_depth(s: str):
    """Whitespace-split tokens with the bracket depth at each token start.

    Returns a list of (start_index, token, depth_at_start). Pure surface tokenization,
    operators applied below only ever touch tokens that are standalone relation symbols
    or numeric literals, so this is safe without a real Lean lexer.
    """
    out = []
    cur, cur_start, cur_depth = [], None, 0
    depth = 0
    for i, ch in enumerate(s):
        if ch.isspace():
            if cur:
                out.append((cur_start, "".join(cur), cur_depth))
                cur = []
        else:
            if not cur:
                cur_start, cur_depth = i, depth
            cur.append(ch)
        if ch in OPEN_BRACKETS:
            depth += 1
        elif ch in CLOSE_BRACKETS:
            depth -= 1
    if cur:
        out.append((cur_start, "".join(cur), cur_depth))
    return out


def explicit_binder_groups(header: str):
    """Top-level `(...)` binder groups in the signature header.

    Returns a list of (start, end_exclusive, inner_text) for each depth-0 parenthesized
    group. Implicit `{}` / instance `[]` / strict-implicit `⦃⦄` binders are NOT explicit
    binders and are never returned.
    """
    groups, start = [], None
    for i, ch, depth in bracket_depth_scan(header):
        if ch == "(" and depth == 0:
            start = i
        elif ch == ")" and depth == 0 and start is not None:
            groups.append((start, i + 1, header[start + 1 : i]))
            start = None
    return groups


def conclusion_head(conclusion: str) -> tuple[str, int]:
    """Reduce a conclusion to its head clause; return (head, offset_in_conclusion).

    Repeatedly strips (a) leading top-level quantifier binders `∀ ..., ` / `∃ ..., ` and
    (b) top-level implications `H → C` (keeping the final consequent C), so that the
    "head relation" of A3 is well-defined. Offsets index into the original conclusion.
    """
    head, offset = conclusion, 0
    while True:
        stripped = head.lstrip()
        offset += len(head) - len(stripped)
        head = stripped
        if head[:1] in ("∀", "∃"):
            # strip up to the first depth-0 comma
            comma = None
            for i, ch, depth in bracket_depth_scan(head):
                if ch == "," and depth == 0:
                    comma = i
                    break
            if comma is None:
                break
            offset += comma + 1
            head = head[comma + 1 :]
            continue
        # strip top-level implications: keep the final depth-0 `→` consequent
        last_arrow = None
        for i, ch, depth in bracket_depth_scan(head):
            if ch == "→" and depth == 0:
                last_arrow = i
        if last_arrow is not None:
            offset += last_arrow + 1
            head = head[last_arrow + 1 :]
            continue
        break
    stripped = head.lstrip()
    offset += len(head) - len(stripped)
    return stripped.rstrip(), offset


# --- Mutation record -------------------------------------------------------------------------

@dataclass
class Mutation:
    """One operator application to one source statement (PRE_REGISTRATION.md §3)."""

    source_decl_id: str
    operator: str            # A1 | A2 | A3 | B1 | B2 | B3
    family: str              # A | B
    tier: str                # F | M | N
    source_statement: str
    mutant_statement: str
    edit: dict = field(default_factory=dict)   # exact edit: spans + before/after text
    verification_status: str = ""
    static_checks_passed: bool = False

    def __post_init__(self):
        if not self.verification_status:
            self.verification_status = (
                "false_by_construction" if self.family == "A" else "pending_lean_verification"
            )
        self.static_checks_passed = static_sanity_check(
            self.source_statement, self.mutant_statement
        )

    def to_dict(self) -> dict:
        return {
            "source_decl_id": self.source_decl_id,
            "operator": self.operator,
            "family": self.family,
            "tier": self.tier,
            "mutant_statement": self.mutant_statement,
            "edit": self.edit,
            "verification_status": self.verification_status,
            "static_checks_passed": self.static_checks_passed,
        }


def static_sanity_check(source: str, mutant: str) -> bool:
    """Pure-static sanity: mutant differs, still a theorem/lemma, brackets balanced,
    still has a top-level type colon. No Lean elaboration (deferred)."""
    if mutant == source or not mutant.strip():
        return False
    if not STATEMENT_RE.match(mutant):
        return False
    if not brackets_balanced(mutant):
        return False
    try:
        split_signature(mutant)
    except MutationError:
        return False
    return True


# --- Family A operators ----------------------------------------------------------------------

def apply_a1(stmt: str, decl_id: str, rng=None) -> Mutation:
    """A1 (Tier F): negate the conclusion, wrap in `¬ (...)` or strip an outermost `¬`."""
    header, conclusion, colon = split_signature(stmt)
    body = conclusion.strip()
    if not body:
        raise MutationError("empty conclusion")
    if body.startswith("¬"):
        inner = body[1:].lstrip()
        # strip one redundant outer paren layer if it wraps the entire remainder
        if inner.startswith("(") and inner.endswith(")") and brackets_balanced(inner[1:-1]):
            inner = inner[1:-1].strip()
        new_conclusion, kind = inner, "strip_negation"
    else:
        new_conclusion, kind = f"¬ ({body})", "wrap_negation"
    mutant = f"{header}: {new_conclusion}"
    return Mutation(
        source_decl_id=decl_id, operator="A1", family="A", tier="F",
        source_statement=stmt, mutant_statement=mutant,
        edit={"kind": kind, "before": body, "after": new_conclusion,
              "site": "conclusion", "colon_index": colon},
    )


def apply_a2(stmt: str, decl_id: str, rng=None) -> Mutation:
    """A2 (Tier F): `∀ x, P` → `∃ x, ¬ P`; `∃ x, P` → `∀ x, ¬ P` (conclusion's leading
    quantifier; the quantified body is wrapped in `¬ (...)`)."""
    header, conclusion, _ = split_signature(stmt)
    body = conclusion.strip()
    if body[:1] not in ("∀", "∃"):
        raise MutationError("conclusion does not start with a quantifier")
    quant = body[0]
    comma = None
    for i, ch, depth in bracket_depth_scan(body):
        if ch == "," and depth == 0:
            comma = i
            break
    if comma is None:
        raise MutationError("no top-level comma after quantifier binder")
    binder, inner = body[1:comma], body[comma + 1 :].strip()
    if not inner:
        raise MutationError("empty quantified body")
    new_quant = "∃" if quant == "∀" else "∀"
    new_body = f"{new_quant}{binder}, ¬ ({inner})"
    mutant = f"{header}: {new_body}"
    return Mutation(
        source_decl_id=decl_id, operator="A2", family="A", tier="F",
        source_statement=stmt, mutant_statement=mutant,
        edit={"kind": "quantifier_negation", "before": body, "after": new_body,
              "site": "conclusion", "quantifier": f"{quant}->{new_quant}"},
    )


def _single_relation_site(text: str, swap_map: dict):
    """Find depth-0 standalone relation tokens of swap_map in `text`.

    Returns the list of (start_index, token) candidate sites.
    """
    return [
        (start, tok)
        for start, tok, depth in _tokens_with_depth(text)
        if depth == 0 and tok in swap_map
    ]


def apply_a3(stmt: str, decl_id: str, rng=None) -> Mutation:
    """A3 (Tier M): complementary swap of the conclusion's head relation (`=`→`≠`,
    `≤`→`>`, `<`→`≥`, `∈`→`∉`, and inverses). Requires exactly ONE depth-0 relation
    token in the head clause so the "head relation" is unambiguous."""
    header, conclusion, _ = split_signature(stmt)
    head, offset = conclusion_head(conclusion)
    sites = _single_relation_site(head, COMPLEMENT_SWAP)
    if len(sites) != 1:
        raise MutationError(f"head clause has {len(sites)} depth-0 relation tokens (need 1)")
    pos, tok = sites[0]
    new_tok = COMPLEMENT_SWAP[tok]
    abs_pos = offset + pos  # position within the conclusion
    new_conclusion = conclusion[:abs_pos] + new_tok + conclusion[abs_pos + len(tok) :]
    mutant = f"{header}:{new_conclusion}"
    return Mutation(
        source_decl_id=decl_id, operator="A3", family="A", tier="M",
        source_statement=stmt, mutant_statement=mutant,
        edit={"kind": "complement_relation", "before": tok, "after": new_tok,
              "site": "conclusion_head", "conclusion_char_index": abs_pos},
    )


# --- Family B operators ----------------------------------------------------------------------

_NAME_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_'.!?]*")


def _binder_names(inner: str) -> list[str]:
    """Names bound by an explicit binder group `(n m : T)` → ['n', 'm']."""
    for i, ch, depth in bracket_depth_scan(inner):
        if ch == ":" and depth == 0:
            return inner[:i].split()
    return []


def droppable_hypothesis_binders(stmt: str):
    """B1 candidates: explicit `(h : P)` groups that look like hypotheses and whose bound
    names do not occur anywhere else in the statement (so the drop stays name-closed)."""
    header, conclusion, _ = split_signature(stmt)
    out = []
    for start, end, inner in explicit_binder_groups(header):
        names = _binder_names(inner)
        if not names or not all(_NAME_TOKEN_RE.fullmatch(n) for n in names):
            continue
        colon = inner.find(":")
        type_text = inner[colon + 1 :] if colon >= 0 else ""
        looks_prop = any(m in type_text for m in _PROP_MARKERS) or all(
            n[0] == "h" for n in names
        )
        if not looks_prop:
            continue
        rest = header[:start] + header[end:] + ":" + conclusion
        rest_names = set(_NAME_TOKEN_RE.findall(rest))
        if any(n in rest_names for n in names):
            continue
        out.append((start, end, inner))
    return out


def apply_b1(stmt: str, decl_id: str, rng) -> Mutation:
    """B1 (Tier N): drop one explicit hypothesis binder (site chosen by the shared RNG)."""
    header, conclusion, _ = split_signature(stmt)
    candidates = droppable_hypothesis_binders(stmt)
    if not candidates:
        raise MutationError("no droppable explicit hypothesis binder")
    idx = int(rng.integers(len(candidates))) if len(candidates) > 1 else 0
    start, end, inner = candidates[idx]
    new_header = (header[:start].rstrip() + " " + header[end:].lstrip()).rstrip()
    mutant = f"{new_header}:{conclusion}"
    return Mutation(
        source_decl_id=decl_id, operator="B1", family="B", tier="N",
        source_statement=stmt, mutant_statement=mutant,
        edit={"kind": "drop_hypothesis", "before": f"({inner})", "after": "",
              "site": "signature_binder", "header_char_index": start},
    )


def apply_b2(stmt: str, decl_id: str, rng) -> Mutation:
    """B2 (Tier N): strict ↔ non-strict swap at one site (`<`↔`≤`, `>`↔`≥`); the site is
    chosen uniformly by the shared RNG among all standalone relation tokens."""
    sites = [
        (start, tok)
        for start, tok, _depth in _tokens_with_depth(stmt)
        if tok in STRICTNESS_SWAP
    ]
    if not sites:
        raise MutationError("no strict/non-strict relation token")
    idx = int(rng.integers(len(sites))) if len(sites) > 1 else 0
    pos, tok = sites[idx]
    new_tok = STRICTNESS_SWAP[tok]
    mutant = stmt[:pos] + new_tok + stmt[pos + len(tok) :]
    return Mutation(
        source_decl_id=decl_id, operator="B2", family="B", tier="N",
        source_statement=stmt, mutant_statement=mutant,
        edit={"kind": "strictness_swap", "before": tok, "after": new_tok,
              "site": "single_relation_site", "char_index": pos},
    )


def apply_b3(stmt: str, decl_id: str, rng) -> Mutation:
    """B3 (Tier N): off-by-one on one numeric literal (n → n+1 or n−1; site and direction
    chosen by the shared RNG; n = 0 always goes up to avoid negative literals)."""
    _, conclusion, _ = split_signature(stmt)  # validates shape
    sites = [
        (start, tok)
        for start, tok, _depth in _tokens_with_depth(stmt)
        if tok.isdigit()
    ]
    if not sites:
        raise MutationError("no standalone numeric literal")
    idx = int(rng.integers(len(sites))) if len(sites) > 1 else 0
    pos, tok = sites[idx]
    n = int(tok)
    if n == 0:
        new_n = 1
    else:
        new_n = n + 1 if int(rng.integers(2)) == 0 else n - 1
    new_tok = str(new_n)
    mutant = stmt[:pos] + new_tok + stmt[pos + len(tok) :]
    return Mutation(
        source_decl_id=decl_id, operator="B3", family="B", tier="N",
        source_statement=stmt, mutant_statement=mutant,
        edit={"kind": "off_by_one", "before": tok, "after": new_tok,
              "site": "numeric_literal", "char_index": pos},
    )


# --- Applicability + dispatch ----------------------------------------------------------------

OPERATORS = {
    "A1": apply_a1,
    "A2": apply_a2,
    "A3": apply_a3,
    "B1": apply_b1,
    "B2": apply_b2,
    "B3": apply_b3,
}

OPERATOR_ORDER = ["A1", "A2", "A3", "B1", "B2", "B3"]  # fixed enumeration order

TIER_OF = {"A1": "F", "A2": "F", "A3": "M", "B1": "N", "B2": "N", "B3": "N"}
FAMILY_OF = {op: op[0] for op in OPERATOR_ORDER}


def applicable_operators(stmt: str) -> list[str]:
    """Enumerate (in the fixed order) the operators applicable to a statement.

    Applicability is checked with a throwaway RNG, site CHOICE inside an operator never
    affects whether it applies, so this probe does not consume the registered stream.
    """
    import numpy as np

    probe_rng = np.random.default_rng(0)
    out = []
    for op in OPERATOR_ORDER:
        try:
            m = OPERATORS[op](stmt, "probe", probe_rng)
            if m.static_checks_passed:
                out.append(op)
        except MutationError:
            pass
        except Exception:
            pass  # malformed statement for this operator: simply not applicable
    return out


def apply_operator(op: str, stmt: str, decl_id: str, rng) -> Mutation:
    return OPERATORS[op](stmt, decl_id, rng)
