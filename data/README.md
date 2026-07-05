# Data access (raw data NOT committed, fetch with the commands below)

All sources are public Hugging Face datasets. Verified live on 2026-06-10; re-verified
and **revision-pinned on 2026-06-11** (see `PRE_REGISTRATION.md` §4: the pinned hashes
below are the locked versions used by `src/fetch_data.py`).
Raw downloads are git-ignored (see `.gitignore`); only the small released pair-set
goes in `results/`.

| Source | Pinned HF revision (2026-06-11) |
|---|---|
| `l3lab/ntp-mathlib` | `03b2ea6c3cf0a55203596445722ebb61c2328889` |
| `mathlib-initiative/mathlib-types` | `f48c9324924a7a5b43ed6a5a6420028ecbcf09a6` |
| `l3lab/miniCTX` | `ba24e70d112679a004510b487ebdeee8c6606ec4` |
| `l3lab/miniCTX-v2` | `91bd27f994c6fd6e3e1a85e7ad01c4ee0e6a01de` |

## Primary statement source (RECOMMENDED): `l3lab/ntp-mathlib`

307,049 rows of Lean 4 declarations extracted from Mathlib4 (commit
`cf8e23a62939ed7cc530fbb68e83539730f32f86`, toolchain `leanprover/lean4:v4.4.0`).
The `decl` field holds the full theorem statement text (`theorem NAME (args) : <prop>`),
which is what we perturb. No Lean build needed to read statements.

**Size correction (measured 2026-06-12 via the HF tree API at the pinned revision):** the
single raw JSONL is **7.8 GB** (every per-tactic row carries the full source file up to
that tactic), not the hundreds of MB previously assumed. The supported path therefore
streams the file and keeps only the two fields we use:

```bash
# RECOMMENDED: stream the pinned revision, keep only (declId, decl) (~70 MB on disk).
# Writes data/ntp-mathlib/pool_decls.jsonl + a .meta.json sidecar (counts, sha256).
python -m src.fetch_data --pool
```

```bash
# NOT recommended (7.8 GB!): the full raw file, only if you need the other fields.
huggingface-cli download l3lab/ntp-mathlib Mathlib/tactic_prediction.jsonl \
  --repo-type dataset --revision 03b2ea6c3cf0a55203596445722ebb61c2328889 \
  --local-dir data/ntp-mathlib
```

Fields: `state, srcUpToTactic, nextTactic, declUpToTactic, declId, decl, file_tag`.
We use `decl` (statement) and `declId` (provenance). Many rows share a `decl`
(one row per tactic step). Dedupe on `declId`/`decl` before sampling.

**License caveat:** `ntp-mathlib` declares NO license on its HF card. Underlying
Mathlib4 is Apache-2.0, but for a *released* derived dataset we must attach an explicit
license and cite Mathlib (DOI 10.1145/3372885.3373824) + miniCTX (arXiv:2408.03350).
Prefer pulling the statement text directly from the explicitly-Apache-2.0
`mathlib-initiative/*` datasets if redistribution licensing is a blocker (see below).

## Explicitly Apache-2.0 alternatives: `mathlib-initiative/*`

- `mathlib-initiative/mathlib-types`: 766,243 rows, 90 MB, Apache-2.0, schema
  `{name, module, type, allowCompletion}`. NOTE: these are **types of declarations**
  (incl. defs, instances, auto-generated `_sizeOf`/`_simp` lemmas), NOT curated theorem
  statements. The `type` field is a Pi-type/Prop string. Usable as raw material but
  noisier than `ntp-mathlib`'s `decl`; needs filtering to real `theorem`/`lemma` Props.
- `mathlib-initiative/mathlib-const-dep`: 766,243 rows, ~120 MB, Apache-2.0
  (dependency graph; useful for premise-aware mutations later).

```bash
huggingface-cli download mathlib-initiative/mathlib-types \
  --repo-type dataset --local-dir data/mathlib-types   # parquet, part-000..NNN
```

## Held-out / freshness probe: `l3lab/miniCTX` and `l3lab/miniCTX-v2`

Small, curated, **timestamped** theorem statements (`theoremStatement`, `theoremName`,
`theoremCreated.date`). miniCTX mathlib split = 50 valid + 50 test (100 total);
miniCTX-v2 adds post-2024-11-28 theorems (carleson, ConNF, FLT, ...). Apache-2.0.
Tiny but valuable as a contamination-controlled / recent-statement held-out probe.

```bash
huggingface-cli download l3lab/miniCTX minictx-test/mathlib.jsonl \
  --repo-type dataset --local-dir data/minictx
```

## Prior-art dataset to engage (NOT a statement source): `INSAIT-Institute/BrokenMath`

10K-100K rows, CC-BY-NC-SA-4.0. Natural-language competition theorems perturbed to
false. We cite/contrast it (the closest sibling), do NOT redistribute (NC-SA).
