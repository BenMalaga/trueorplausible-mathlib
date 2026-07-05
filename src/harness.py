"""Model-run harness for TrueOrPlausible, frozen prompt, logprob confidence, EMBARGOED.

================================  EMBARGO  ================================
No real model may be queried until an explicitly recorded go decision (model runs are
sequenced after the benchmark is frozen and hashed; see PRE_REGISTRATION.md §9,
locked 2026-06-11). The invocation embargo is enforced in code, twice:

  1. **Explicit opt-in flag.** ``allow_real_models=True`` must be passed to the
     ``LlamaCppLLM`` constructor. The default is ``False`` and raises
     ``EmbargoViolation``. Nothing in this repository passes ``True``.
  2. **Lock-file check.** Construction (and every subsequent scoring call) verifies
     that ``PRE_REGISTRATION.md`` exists at the repo root, real outcome data may
     only ever be produced under a locked pre-registration.

The ONLY backend that constructs without both gates is ``MockLLM`` (deterministic,
seeded, test-only). The CLI is intentionally inert: it can explain the embargo and
run a mock smoke pass, nothing else.
===========================================================================

What is frozen here (PRE_REGISTRATION.md §5):
  - the zero-shot prompt template (verbatim; its sha256 is recorded in every run config)
  - greedy decoding (temperature 0), single forward pass per item
  - primary confidence = P(True) / (P(True) + P(False)) from the log-probabilities at
    the answer position, with the answer-token surface-form sets recorded in the config
  - items answering neither True nor False are abstentions (counted, excluded from AUROC)

The secondary verbalized 0-100 confidence elicitation (separate prompt) is exploratory
and analyzed separately; hosted-API models without logprobs use only that path and are
never pooled with the primary cohort.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "results" / "raw"  # gitignored: holds embargoed outcome data

#: Pre-registration lock file (module-level so tests can point it elsewhere).
PREREG_LOCK_FILE = ROOT / "PRE_REGISTRATION.md"

# --- Frozen prompt (PRE_REGISTRATION.md §5, byte-for-byte) ---------------------------------

PROMPT_TEMPLATE = """You are given a formal Lean 4 statement from a mathematics library. Decide whether
the statement is TRUE (a provable theorem) or FALSE (not provable). Answer with
exactly one word: True or False.

Statement:
{statement}

Answer:"""

PROMPT_TEMPLATE_SHA256 = hashlib.sha256(PROMPT_TEMPLATE.encode("utf-8")).hexdigest()

#: Secondary, EXPLORATORY verbalized-confidence prompt (separate query; never pooled
#: with the primary logprob cohort).
VERBALIZED_CONFIDENCE_TEMPLATE = """You are given a formal Lean 4 statement from a mathematics library and a proposed
verdict. On a scale from 0 to 100, how confident are you that the verdict is correct?
Answer with a single integer between 0 and 100.

Statement:
{statement}

Verdict: {verdict}

Confidence:"""

#: Answer-token surface forms (PRE_REGISTRATION.md §5: "the token-id sets covering each
#: surface form are recorded in the harness config"). At real-run time the backend maps
#: these strings to model-specific token ids and records that mapping in the run config.
TRUE_SURFACE_FORMS = ["True", " True", "true", " true", "TRUE", " TRUE"]
FALSE_SURFACE_FORMS = ["False", " False", "false", " false", "FALSE", " FALSE"]

DECODING = {"temperature": 0.0, "strategy": "greedy", "forward_passes_per_item": 1}


class EmbargoViolation(RuntimeError):
    """Raised when anything tries to construct or use a real-model backend under embargo."""


def _check_gates(allow_real_models: bool, backend: str) -> None:
    """Enforce both embargo gates; called at construction AND on every scoring call."""
    if not allow_real_models:
        raise EmbargoViolation(
            f"{backend}: real-model backends are embargoed. Construction requires an "
            "explicit allow_real_models=True; real runs begin only at an explicitly "
            "recorded go decision."
        )
    if not PREREG_LOCK_FILE.exists():
        raise EmbargoViolation(
            f"{backend}: pre-registration lock file not found at {PREREG_LOCK_FILE}. "
            "Real outcome data may only be produced under a locked PRE_REGISTRATION.md."
        )


# --- Readings ---------------------------------------------------------------------------------

@dataclass
class Reading:
    """One model reading of one item: mass on each answer set at the answer position."""

    p_true_mass: float    # total next-token probability over TRUE_SURFACE_FORMS tokens
    p_false_mass: float   # total next-token probability over FALSE_SURFACE_FORMS tokens
    top_token: str        # the greedy next token (surface form)

    @property
    def abstained(self) -> bool:
        """Neither answer form carries usable mass / the greedy token is neither word."""
        if self.p_true_mass + self.p_false_mass <= 0.0:
            return True
        top = self.top_token.strip()
        return top not in {s.strip() for s in TRUE_SURFACE_FORMS + FALSE_SURFACE_FORMS}

    @property
    def confidence_true(self) -> float:
        """Primary score (frozen): P(True) / (P(True) + P(False))."""
        denom = self.p_true_mass + self.p_false_mass
        return float(self.p_true_mass / denom) if denom > 0 else 0.5

    @property
    def answer(self) -> str:
        if self.abstained:
            return "abstain"
        return "true" if self.confidence_true >= 0.5 else "false"


class LLMInterface:
    """Minimal backend interface: score one prompt, return a Reading."""

    model_id: str = "abstract"

    def read(self, prompt: str) -> Reading:  # pragma: no cover - interface
        raise NotImplementedError


class MockLLM(LLMInterface):
    """Deterministic test backend, the only backend that runs under embargo.

    Default behavior: confidence derived from a seeded hash of the prompt (uninformative
    null). Tests may inject ``score_fn(prompt) -> p_true_mass`` to plant a signal.
    """

    def __init__(self, seed: int = 20260611, score_fn=None, model_id: str = "mock-llm"):
        self.seed = seed
        self.score_fn = score_fn
        self.model_id = model_id

    def read(self, prompt: str) -> Reading:
        if self.score_fn is not None:
            p_true = float(self.score_fn(prompt))
        else:
            h = hashlib.sha256(f"{self.seed}:{prompt}".encode("utf-8")).digest()
            p_true = int.from_bytes(h[:8], "big") / 2**64  # uniform [0, 1), deterministic
        p_true = min(max(p_true, 0.0), 1.0)
        scale = 0.98  # leave a little mass off the two answer tokens, like a real model
        return Reading(
            p_true_mass=p_true * scale,
            p_false_mass=(1.0 - p_true) * scale,
            top_token="True" if p_true >= 0.5 else "False",
        )


class LlamaCppLLM(LLMInterface):
    """Real local backend (llama.cpp GGUF), DOUBLE-GATED, never constructed under embargo.

    Both gates (explicit ``allow_real_models=True`` + PRE_REGISTRATION.md lock file) are
    checked at construction and re-checked on every ``read``. The ``llama_cpp`` import is
    deferred so the embargoed repository never even imports an inference library.
    """

    def __init__(self, model_path: str, allow_real_models: bool = False,
                 n_ctx: int = 4096, model_id: str | None = None):
        _check_gates(allow_real_models, "LlamaCppLLM")
        self._allow = allow_real_models
        self.model_path = model_path
        self.model_id = model_id or Path(model_path).stem
        self.n_ctx = n_ctx
        self._llm = None  # lazy; loaded on first read, post-gates

    def _load(self):
        from llama_cpp import Llama  # deferred import: post-embargo only

        return Llama(model_path=self.model_path, n_ctx=self.n_ctx, logits_all=False,
                     verbose=False)

    def read(self, prompt: str) -> Reading:
        _check_gates(self._allow, "LlamaCppLLM.read")
        if self._llm is None:
            self._llm = self._load()
        out = self._llm(prompt, max_tokens=1, temperature=0.0, logprobs=40)
        top = out["choices"][0]["logprobs"]
        import math

        token_lps = top["top_logprobs"][0] if top["top_logprobs"] else {}
        p_true = sum(math.exp(lp) for tok, lp in token_lps.items()
                     if tok in TRUE_SURFACE_FORMS)
        p_false = sum(math.exp(lp) for tok, lp in token_lps.items()
                      if tok in FALSE_SURFACE_FORMS)
        return Reading(p_true_mass=p_true, p_false_mass=p_false,
                       top_token=out["choices"][0]["text"])


# --- Runner -----------------------------------------------------------------------------------

def run_config(llm: LLMInterface, benchmark_sha256: str) -> dict:
    """The frozen-settings record written next to every run's raw outputs."""
    return {
        "model_id": llm.model_id,
        "prompt_template_sha256": PROMPT_TEMPLATE_SHA256,
        "decoding": DECODING,
        "true_surface_forms": TRUE_SURFACE_FORMS,
        "false_surface_forms": FALSE_SURFACE_FORMS,
        "confidence": "P(True) / (P(True) + P(False)) at the answer position (primary)",
        "benchmark_sha256": benchmark_sha256,
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def run_benchmark(items: list[dict], llm: LLMInterface, out_path: Path,
                  benchmark_sha256: str = "", primary_only: bool = True) -> dict:
    """Query ``llm`` on each benchmark item; write per-item JSONL + a run config sidecar.

    ``primary_only=True`` restricts to ``primary_set`` items (Family A), Family-B items
    are never scored while their labels are pending Lean verification.
    Resume-safe: items already present in ``out_path`` are skipped.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done: set[str] = set()
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            done = {json.loads(l)["item_id"] for l in f if l.strip()}
    cfg = run_config(llm, benchmark_sha256)
    cfg_path = out_path.with_suffix(".config.json")
    if not cfg_path.exists():
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")

    n_run = n_abstain = 0
    with open(out_path, "a", encoding="utf-8") as f:
        for it in items:
            if primary_only and not it.get("primary_set", False):
                continue
            if it["item_id"] in done:
                continue
            prompt = PROMPT_TEMPLATE.format(statement=it["statement"])
            r = llm.read(prompt)
            rec = {
                "item_id": it["item_id"],
                "pair_id": it["pair_id"],
                "source_decl_id": it["source_decl_id"],
                "label": it["label"],
                "tier": it["tier"],
                "operator": it["operator"],
                "model_id": llm.model_id,
                "answer": r.answer,
                "p_true_mass": r.p_true_mass,
                "p_false_mass": r.p_false_mass,
                "confidence_true": r.confidence_true,
                "abstained": r.abstained,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_run += 1
            n_abstain += int(r.abstained)
    return {"items_run": n_run, "abstentions": n_abstain, "config": cfg,
            "out_path": str(out_path)}


# --- CLI, intentionally inert under embargo ---------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="TrueOrPlausible run harness (EMBARGOED: mock backend only)"
    )
    ap.add_argument("--explain-embargo", action="store_true")
    args = ap.parse_args()
    if args.explain_embargo:
        print(__doc__)
        return
    print(
        "No action taken. Real-model runs are under an invocation embargo: the only "
        "backend this repository constructs is the deterministic MockLLM used by the "
        "test suite. The real backend is double-gated (allow_real_models=True + "
        "PRE_REGISTRATION.md lock file) and is enabled only at a recorded go decision."
    )


if __name__ == "__main__":
    main()
