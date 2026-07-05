# PRE-REGISTRATION: TrueOrPlausible

**Status: LOCKED 2026-06-11.**
This document fixes the hypotheses, thresholds, dataset versions, mutation taxonomy,
model roster, metrics, and analysis plan **before any outcome data exists**. Any analysis
not specified here will be labeled *exploratory* in the writeup.

> **No model queried at lock.** As of this commit (2026-06-11), no language model, local
> or hosted, has been queried with any benchmark item, no mutant set has been generated,
> and no outcome data of any kind exists. The statement pool has not been sampled. Prior-art
> and dataset-liveness checks (HTTP metadata only) were re-run on 2026-06-11.

---

## 1. Research question

Can a small (≤4B-parameter) open language model, prompted with a single formal Lean 4
statement and no proof, distinguish a **true** (library-provable) theorem from a
**subtly-false near-miss**, and is its confidence **calibrated**, or does it collapse
exactly where the perturbation is closest to true?

Ground truth is machine-checkable: true statements come from Mathlib4 (every one carries a
formal proof in the library); false statements are produced by mutation operators that are
falsifying by construction (Family A) or are machine-verified false (Family B).

## 2. Hypotheses (falsifiable; thresholds fixed here)

- **H1: discrimination.** At least one model in the locked roster (§6) achieves pooled
  AUROC **> 0.60** on the primary (Family-A) benchmark, with the one-sided 95% bootstrap
  lower confidence bound **> 0.50**. Null: prompted veracity judgment is at chance
  (AUROC = 0.5). Per-model tests are Holm-Bonferroni corrected across the roster (m = 5).
- **H2: tier collapse.** For each model, AUROC decreases as the perturbation gets
  surface-subtler: AUROC(Tier F) > AUROC(Tier M) > AUROC(Tier N). **Primary contrast:**
  AUROC(Tier F) − AUROC(Tier M) **> 0.05** with one-sided 95% bootstrap lower bound > 0
  (both tiers are Family A, so this contrast is always available). **Secondary contrast**
  (only if the Family-B set passes verification, §4): AUROC(Tier F) − AUROC(Tier N) > 0.05,
  same test. Monotonicity across all available tiers is additionally summarized with a
  per-model Spearman trend (descriptive).
- **H3: miscalibration.** For each model, ECE **> 0.10** on the primary benchmark
  (binning: 10 equal-mass bins over the model's confidence in its predicted label).
  Brier score and reliability diagrams are reported alongside.
- **H4: not a surface artifact.** The best model's pooled AUROC exceeds the
  surface-feature-only baseline's AUROC (§7) by **≥ 0.05**, paired bootstrap one-sided 95%
  lower bound > 0. **If H4 fails, a positive H1 is uninterpretable as statement
  understanding and will be reported as such.**
- **A null is a result.** If all models sit at AUROC ≈ 0.5, the released benchmark and the
  finding that small models cannot judge formal-statement veracity are the contribution;
  this outcome will be reported in full, not shelved.

## 3. Mutation taxonomy (fixed; this defines the artifact)

Each benchmark item is a single standalone Lean 4 statement: either an unmodified true
Mathlib4 theorem/lemma or one mutant derived from it. Mutants are produced by exactly one
operator application per item.

**Family A: falsifying by construction (no Lean check needed; the primary set):**
If the source statement (hypotheses H, conclusion C) is provable and its hypotheses are
jointly satisfiable, each operator below yields a non-theorem:

| Op | Definition | Tier |
|----|-----------|------|
| A1 | Negate the conclusion: wrap C's head in `¬ (...)` (or strip an outermost `¬`) | **F** (far) |
| A2 | Quantifier negation in the conclusion: `∀ x, P x` → `∃ x, ¬ P x`; `∃ x, P x` → `∀ x, ¬ P x` | **F** (far) |
| A3 | Complementary-relation swap in the conclusion's head relation: `=`→`≠`, `≤`→`>`, `<`→`≥`, `∈`→`∉`, and their inverses | **M** (mid) |

A3 swaps are logically equivalent to negation for the relations listed (in the preorder /
membership semantics Mathlib uses) but introduce no explicit negation symbol, they are
surface-subtle, logically far.

*Stated assumption (reported, spot-checked):* Family A's falsity relies on the source
theorem's hypotheses being jointly satisfiable (a vacuous theorem's negated form can be
vacuously true). Such theorems are rare in Mathlib by design; if a Lean verification pass
runs (§4), a random sample of ≥ 50 Family-A mutants is also machine-checked, and the
observed failure rate is reported.

**Family B: truth-uncertain near-misses (requires machine verification; Tier N):**

| Op | Definition | Tier |
|----|-----------|------|
| B1 | Drop one explicit hypothesis binder | **N** (near) |
| B2 | Strict ↔ non-strict swap: `<` ↔ `≤`, `>` ↔ `≥` (single site) | **N** (near) |
| B3 | Off-by-one: a numeric literal or index bound `n` → `n+1` or `n−1` (single site) | **N** (near) |

A Family-B mutant may still be true (e.g., dropping a redundant hypothesis). **Verification
protocol:** each B-mutant must be machine-confirmed false before inclusion, via a one-time
Lean 4 pass against prebuilt Mathlib (counterexample search with `plausible`/`decide`, or
proving the negation with `decide`/`norm_num`/`omega` where decidable), run headless with
narrowed imports on a hosted runner or a ≥16GB machine (no from-scratch Mathlib build; no
cost above free tiers). Mutants whose falsity cannot be machine-confirmed are **excluded
and counted**; the **drop/uncertain rate is a reported result**, never a silent filter.
**Fallback (pre-committed):** if the verification pass is infeasible, v1 ships
**Family A only** (Tiers F and M), Family B is documented as a limitation, and H2's
secondary contrast is not run. Unverified B labels are never used.

**Tier order for H2 (fixed):** F (explicit negation; textually obvious) → M (complementary
relation swap; same length, no negation symbol) → N (minimal near-miss edits; Lean-verified
false).

## 4. Data and sampling plan (versions pinned 2026-06-11)

**Pinned sources (all re-verified live via HTTP on 2026-06-11; public, ungated):**

| Source | Role | Pinned revision | License |
|---|---|---|---|
| `l3lab/ntp-mathlib` (HF) | primary statement pool (`decl` field) | `03b2ea6c3cf0a55203596445722ebb61c2328889` | undeclared on card (text is Mathlib4-derived, Apache-2.0) |
| Mathlib4 (GitHub) | upstream provenance of statement text | commit `cf8e23a62939ed7cc530fbb68e83539730f32f86` (toolchain v4.4.0) | Apache-2.0 |
| `l3lab/miniCTX-v2` (HF) | held-out recency probe (exploratory) | `91bd27f994c6fd6e3e1a85e7ad01c4ee0e6a01de` | Apache-2.0 |
| `l3lab/miniCTX` (HF) | secondary held-out probe | `ba24e70d112679a004510b487ebdeee8c6606ec4` | Apache-2.0 |
| `mathlib-initiative/mathlib-types` (HF) | backup statement source only (not used unless ntp-mathlib fails) | `f48c9324924a7a5b43ed6a5a6420028ecbcf09a6` | Apache-2.0 |

**Pool construction (idempotent, logged):**
1. Read `decl` + `declId` from `l3lab/ntp-mathlib` at the pinned revision.
2. Dedupe: first row per `declId`, then drop exact-duplicate `decl` texts.
3. Filter to genuine statements: `decl` matches `^\s*(theorem|lemma)\s`; exclude
   `decl` containing `sorry`; exclude auto-generated names (`declId` containing any of
   `_sizeOf`, `_simp`, `.mk.`, `.rec`, `.casesOn`, `.noConfusion`, `eq_def`, `proof_`);
   exclude statements longer than 600 characters or spanning more than 12 lines.
4. **Sample N = 1,200 source theorems** uniformly without replacement,
   seed **20260611** (`numpy.random.default_rng(20260611)`).
5. For each sampled theorem, enumerate applicable operators; keep at most **2 mutants per
   source theorem** (uniform choice among applicable operators, same RNG stream), targeting
   ≥ 300 items per tier. Every cap, drop, and exclusion is logged and reported, no silent
   scope cuts.
6. **Pairing + balance:** each included mutant is paired with its unmodified source
   statement (label true), yielding a 50/50 true/false set, paired by source theorem.
7. **Length control:** pairs with an absolute whitespace-token-count difference > 5 are
   excluded (logged). Residual length deltas are reported, and H4's surface baseline is the
   binding control.

**Held-out recency probe (exploratory, not part of H1-H4):** miniCTX-v2 statements created
after 2024-11-28 (≤ 100), run through the same mutation pipeline, to contrast performance
on likely-in-pretraining vs post-cutoff statements.

**Released artifact + license:** the benchmark pair set (statement text, label, operator,
tier, source `declId`, length stats) is released under **Apache-2.0** with attribution to
Mathlib4 (DOI 10.1145/3372885.3373824), the ntp-mathlib extraction, and miniCTX
(arXiv:2408.03350). Statement text originates from Apache-2.0 Mathlib4; the undeclared
ntp-mathlib card license is bridged by citing the extraction and pinning the upstream
Mathlib4 commit. The BrokenMath dataset (CC-BY-NC-SA-4.0) is cited for contrast only and
never redistributed or derived from.

## 5. Task, prompt, and confidence elicitation (frozen)

Zero-shot, one statement per query, frozen prompt template:

```
You are given a formal Lean 4 statement from a mathematics library. Decide whether
the statement is TRUE (a provable theorem) or FALSE (not provable). Answer with
exactly one word: True or False.

Statement:
{statement}

Answer:
```

- Decoding: temperature 0 (greedy), single forward pass per item.
- **Primary confidence score:** normalized next-token probability
  `P(True) / (P(True) + P(False))` read from the log-probabilities at the answer position
  (the token-id sets covering each surface form are recorded in the harness config).
- **Secondary (exploratory):** verbalized 0-100 confidence elicited in a separate prompt.
- Hosted-API models without token log-probabilities use the verbalized score and are
  analyzed separately (different elicitation; never pooled with the primary cohort).

## 6. Model roster (fixed before any run; ≤4B Q4, 8GB Apple-silicon constraint)

Local cohort (GGUF, Q4_K_M or nearest available Q4 variant, exact repo + file recorded in
the run config before the first query; training-cutoff dates recorded from official model
cards at the same time):

1. Qwen2.5-3B-Instruct
2. Qwen3-4B-Instruct-2507
3. Phi-4-mini-instruct (3.8B)
4. SmolLM3-3B
5. Llama-3.2-3B-Instruct

Substitution rule: if a listed model has no usable ≤4B Q4 GGUF at run time, the substitute
(same family, nearest size) is recorded with justification before any query.

Optional exploratory cohort: up to 3 small hosted-API models (mini/flash tier), total spend
< $10, verbalized confidence only, labeled exploratory throughout.

## 7. Surface-feature baseline (binding control for H4)

Logistic regression (scikit-learn, L2, C = 1.0) on per-statement features:
character length; whitespace-token count; counts of each symbol in
{`∀ ∃ ¬ ≠ ≤ < ≥ > = ∈ ∉ → ↔ ∧ ∨`}; digit count; maximum bracket nesting depth; number of
explicit binder groups. Evaluated by 5-fold **group-stratified** cross-validation grouped
by source theorem (a theorem and its mutant never span folds); baseline AUROC is computed
from out-of-fold predictions.

## 8. Metrics, uncertainty, and corrections

- **Primary metric:** AUROC, pooled and per tier, per model.
- **Calibration:** ECE (10 equal-mass bins), Brier score, reliability diagrams.
- **Uncertainty:** cluster bootstrap resampling **source theorems** (pairs stay together),
  **n_boot = 2,000**, seed 20260611; 95% percentile intervals.
- **Multiple comparisons:** H1 Holm-Bonferroni across the 5 local models; H2/H3 are
  per-model descriptions with CIs; H4 tests only the single best model (selected by pooled
  AUROC) against the baseline.
- Items where a model emits neither `True` nor `False` in the answer position are scored as
  abstentions: excluded from AUROC, counted, and the abstention rate reported per model.

## 9. Analysis order (firewall against peeking)

1. Build the statement pool and mutant set; freeze and hash the benchmark file.
2. Run the surface baseline (§7) on the frozen set.
3. Run the local cohort (§6) with the frozen prompt (§5).
4. Compute pre-registered tests H1-H4; only then any exploratory analyses (so labeled).

## 10. Ethics and footprint

The data are public formal-mathematics statements; no human subjects, no personal data, no
sensitive content. Compute is laptop-scale inference plus one optional hosted verification
pass within free tiers; total API spend capped under $10. The released benchmark targets
evaluation integrity (measuring overconfidence on plausible-but-false formal claims) and
carries no foreseeable dual-use concern. Mathlib4 contributors are credited via the
Apache-2.0 attribution chain (§4).

**Known limitation stated up front:** Mathlib4 is present in most open models' pretraining
corpora. True statements may be memorized; mutants are novel strings. The task therefore
measures true-vs-near-miss *discrimination*, not contamination-free reasoning; the
miniCTX-v2 recency probe (§4) is the exploratory check on this confound, and the surface
baseline (§7) controls for trivial cues. This is discussed, not hidden, in the writeup.

---

*Locked 2026-06-11. Committed before any statement pool was sampled, any mutant was
generated, or any model was queried. Changes after this commit appear only as labeled
amendments in this file's git history.*

---

## Amendments

**AMENDMENT 1 (2026-06-11, pre-outcome, analysis clarification).** §7 registers the
surface-feature baseline as "logistic regression (scikit-learn, L2, C = 1.0)" over the listed
features without specifying feature preprocessing. The implementation (`src/score.py`)
standardizes features per training fold (z-scoring fit on each fold's training split) before
the regression. With C fixed, scaling changes the effective per-feature regularization, so we
record it explicitly: the scaler is **included**. Rationale: unscaled features (character
lengths vs. binary flags) make an L2 penalty at fixed C unit-dependent and arbitrary;
standardization is the standard-practice reading. This choice is conservative with respect to
H4, it strengthens the baseline, making H4's ≥0.05 margin *harder* to achieve. Recorded
before any model has been queried on any benchmark item; H1-H4 thresholds unchanged.
