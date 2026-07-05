# Related work

This section surveys the closest prior work and states how this project differs from each
neighbor. The literature covers natural-language perturbation benchmarks, formal-Lean
evaluation, and LLM calibration; the limitations section of the writeup addresses the
"isn't this just X?" question for each of these directly.

**The contribution.** This project performs standalone, prompted, binary
true-vs-minimally-perturbed-false veracity classification on formal Lean / mathlib
statements (machine-checkable ground truth), with small (≤4B) open models, reporting
per-perturbation-tier AUROC and ECE (calibration) against a surface-feature-only baseline.
To our knowledge, no prior work performs this exact combination.

---

## Closest neighbors

### NumPert, Aarnes & Setty, arXiv:2511.09971 (Nov 2025)
- **What it does:** perturbation + label-flip probes for **veracity prediction**, the same
  conceptual frame (perturb a true claim, ask the model to judge truth).
- **How this project differs:** NumPert operates on **natural-language numerical
  claim+evidence pairs**, not formal Lean; calibration is not its focus. Here, ground truth
  is **machine-checkable formal statements**, and per-tier calibration is front and center.

### BrokenMath, arXiv:2510.04721 (Oct 2025, NeurIPS 2025); HF `INSAIT-Institute/BrokenMath`
- **What it does:** independently performs the **"perturb a true theorem into a subtly-
  false near-miss"** construction this project relies on; dataset is live (CC-BY-NC-SA-4.0).
- **How this project differs:** (1) BrokenMath uses **natural-language competition math**,
  not formal Lean; (2) its task is **sycophancy during proof generation**, not standalone
  binary veracity classification; (3) no per-tier AUROC/ECE calibration analysis;
  (4) frontier models, not small open ones.
- **Relationship:** BrokenMath is the strongest evidence that the perturb-a-true-theorem
  idea is shared in the literature, and it is cited as such. Its license is CC-BY-NC-SA-4.0,
  so it is used for citation and contrast only and is not redistributed or used to build a
  released derivative; the NC-SA inheritance would otherwise constrain this project's
  released artifact (Apache-2.0).

---

## Adjacent (same family, clearly different task)

### MATH-Perturb / MATH-P-Hard & -Simple, arXiv:2502.06453 (ICML 2025)
279 perturbed level-5 MATH **problems** for problem-**solving** robustness. Non-formal, no
statement-veracity-classification task, no calibration. Shares only the "perturbation
tiers" vocabulary.

### Trilemma of Truth in LLMs, arXiv:2506.23921 (2025)
True/false/neither veracity classification via a multiclass probe (sAwMIL) over LLM
**internal activations**. Adjacent on the true/false task, but **natural-language**
statements and **internal-state probing**, not prompted standalone classification of
**formal** statements.

### Testing the Limits of Truth Directions in LLMs, arXiv:2604.03754 (Apr 2026)
Shows truth-direction **probes** are layer-, task-, and prompt-dependent, i.e. fragile.
Internal-activation probing of natural-language statements; no formal statements, no
perturbation benchmark. Complements the prompted-classification angle taken here.

### MathlibLemma, arXiv:2602.02561 (Feb 2026)
Generation/proving benchmark of 4,028 type-checked **TRUE** Lean lemmas. **No
perturbed-false negatives, no veracity-classification task.** A same-space neighbor to
cite and a candidate additional TRUE-statement source.

### Construction-Verification, arXiv:2602.01291 (Feb 2026)
Applied-mathematics benchmark in Lean 4; same formal-Lean/mathlib space, different task
(construction + verification, not statement veracity). Cite as a same-space neighbor.

### ALCHEMY (OpenReview)
Mutates Mathlib theorems (≈6M variants, equivalent forms / logical antecedents) as
**training-data augmentation for provers**: truth-preserving mutation for synthesis, not
a falsifying-mutation benchmark and no classification/calibration task. Useful precedent
for statement mutation tooling on mathlib.

### Grammars of Formal Uncertainty, arXiv:2505.20047
Uncertainty quantification (AUROC/ECE/Brier) for **LLM-generated formal artifacts**
(autoformalization error detection). Calibration metrics in the formal-math space, but the
judged objects are model outputs, not perturbed library statements.

### 2026 Lean benchmark wave (cite as context)
LemmaBench (arXiv:2602.24173, lemma **proving** from arXiv preprints), CAM-Bench
(arXiv:2605.17255, computational/applied formalization), VeriSoftBench (arXiv:2602.18307,
repository-scale proof obligations), and LLM-formalization evaluations (arXiv:2606.05632)
show the formal-Lean evaluation area is highly active. None performs perturbed-statement
veracity classification.

---

## Additional 2026 work (through mid-June 2026)

The following works appeared through mid-June 2026. None performs standalone, prompted,
binary true-vs-near-miss veracity classification on formal Lean statements with small open
models and per-tier AUROC/ECE; several are relevant context or motivation.

### Faults in our Formal Benchmarks (Ammanamanchi & Bhat, NeurIPS 2025 Workshop MATH-AI; OpenReview `gJ2CpndJmI`)
Directly relevant to this project's motivation. It independently audits popular Lean
theorem-proving benchmarks and finds systematic "material defects" (omitted side
conditions, misformalization, incorrect/incomplete translations) across all datasets
examined. This is third-party evidence that formal benchmarks can silently harbor
non-theorems, and supports the machine-checkable label discipline used here (the Family-B
Lean verification pass with a reported drop rate, and the stated hypothesis-satisfiability
assumption for Family A) as a response to a documented field problem. It appears in the
same workshop venue this project targets.

### Beyond Correctness: Exposing LLM-generated Logical Flaws via Multi-step ATP (Zheng et al., arXiv:2512.23511, Dec 2025)
Converts natural-language reasoning chains to first-order logic and runs automated
theorem provers to grade step-by-step validity (PrOntoQA-OOD, ProofWriter, FOLIO).
It is adjacent in using an ATP to expose subtle logical errors, but it is not formal Lean
statement veracity classification and not a perturbed-theorem benchmark; it grades
reasoning traces, not standalone library statements. A same-spirit, different-substrate
neighbor.

### Further 2026 formal-Lean benchmarks (context)
LeanCat (arXiv:2512.24796, formal category theory suite), FormalML (arXiv:2510.02335,
formal subgoal completion in ML theory), and LeanGeo (arXiv:2508.14644, competition
geometry formalization) extend the active formal-Lean evaluation area into new
mathematical domains. All measure proving/formalization ability on TRUE targets; none does
perturbed-statement veracity classification or per-tier calibration. They illustrate that
the formal-Lean evaluation area kept expanding through 2026 in directions distinct from the
task studied here.

### Calibration / LLM-as-judge context (NL, not formal)
The LLM-calibration line stayed active in 2026 (e.g. overconfidence in LLM-as-a-judge,
arXiv:2508.06225; EACL 2026 uncertainty/calibration benchmarking, `2026.eacl-long.106`),
all on natural-language tasks. These motivate the ECE/AUROC framing but do not address
formal statement veracity, and so do not overlap with the calibration analysis here.

---

## Datasets we build on or contrast (provenance + licensing)

| Source | Role | License | Note |
|---|---|---|---|
| `l3lab/ntp-mathlib` | **primary** statement pool (`decl` text) | UNDECLARED on HF (Mathlib4 = Apache-2.0) | dedupe per-tactic rows; attach explicit license for any released derivative |
| `mathlib-initiative/mathlib-types` | backup statement source | Apache-2.0 (explicit) | declaration *types* incl. auto-gen junk; filter to real `theorem`/`lemma` Props |
| `l3lab/miniCTX` / `miniCTX-v2` | held-out / **recency** probe | Apache-2.0 | tiny (~100 mathlib stmts); v2 adds post-2024-11-28 theorems |
| `INSAIT-Institute/BrokenMath` | **prior-art contrast only** | CC-BY-NC-SA-4.0 | do NOT redistribute / derive |

Cite Mathlib (DOI 10.1145/3372885.3373824) and miniCTX (arXiv:2408.03350) for any released
statement derivative; both are the upstream provenance for the statement text.

---

## Anticipated objections and responses
1. *"BrokenMath already perturbs true theorems to false."* This is so, but in natural
   language and for proving-sycophancy; this project addresses formal Lean, standalone
   veracity classification, calibrated per tier, with small models.
2. *"NumPert already does perturbation to veracity."* NumPert operates on natural-language
   numerical claims; the formal, machine-checkable ground truth here removes label noise
   and is the key substantive difference.
3. *"The near-misses might still be true."* This is why Family-B mutants pass a machine
   verification step or are dropped, with the drop rate reported. Family A is false by
   construction, with the satisfiability assumption stated and spot-checked.
4. *"The signal could be surface length."* Pairs are length-matched and a surface-only
   logistic baseline is included; a positive LLM result must beat it to be interpretable
   (pre-registered H4).
