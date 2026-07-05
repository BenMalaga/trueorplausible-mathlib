"""Tests for src.harness, frozen prompt fidelity, mock determinism, embargo gates."""

import json
import re
from pathlib import Path

import pytest

from src import harness
from src.harness import (
    FALSE_SURFACE_FORMS,
    PROMPT_TEMPLATE,
    TRUE_SURFACE_FORMS,
    EmbargoViolation,
    LlamaCppLLM,
    MockLLM,
    Reading,
    run_benchmark,
)

ROOT = Path(__file__).resolve().parent.parent


# --- frozen prompt -----------------------------------------------------------------------------

def test_prompt_template_matches_preregistration_verbatim():
    """The in-code template must be byte-identical to the fenced block in §5."""
    text = (ROOT / "PRE_REGISTRATION.md").read_text(encoding="utf-8")
    m = re.search(r"frozen prompt template:\s*\n\n```\n(.*?)\n```", text, re.DOTALL)
    assert m, "could not locate the frozen prompt block in PRE_REGISTRATION.md §5"
    assert PROMPT_TEMPLATE == m.group(1)


def test_decoding_is_greedy_single_pass():
    assert harness.DECODING == {
        "temperature": 0.0, "strategy": "greedy", "forward_passes_per_item": 1,
    }


# --- Reading semantics ---------------------------------------------------------------------

def test_confidence_is_normalized_two_token_mass():
    r = Reading(p_true_mass=0.7, p_false_mass=0.2, top_token="True")
    assert r.confidence_true == pytest.approx(0.7 / 0.9)
    assert r.answer == "true" and not r.abstained


def test_abstention_when_no_answer_mass_or_off_vocab_top_token():
    assert Reading(0.0, 0.0, "True").abstained
    assert Reading(0.4, 0.3, "Maybe").abstained
    assert Reading(0.4, 0.3, " True").abstained is False


# --- MockLLM ---------------------------------------------------------------------------------

def test_mock_llm_is_deterministic_across_instances():
    a = MockLLM(seed=20260611).read("prompt one")
    b = MockLLM(seed=20260611).read("prompt one")
    c = MockLLM(seed=20260611).read("prompt two")
    assert a == b
    assert a != c


def test_mock_llm_score_fn_injection():
    llm = MockLLM(score_fn=lambda p: 0.9)
    r = llm.read("anything")
    assert r.answer == "true" and r.confidence_true == pytest.approx(0.9)


# --- embargo gates ----------------------------------------------------------------------------

def test_real_backend_refuses_without_explicit_flag():
    with pytest.raises(EmbargoViolation, match="embargoed"):
        LlamaCppLLM(model_path="/nonexistent.gguf")


def test_real_backend_refuses_without_lock_file(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "PREREG_LOCK_FILE", tmp_path / "PRE_REGISTRATION.md")
    with pytest.raises(EmbargoViolation, match="lock file"):
        LlamaCppLLM(model_path="/nonexistent.gguf", allow_real_models=True)


def test_real_backend_gates_pass_without_loading_any_model():
    # Both gates satisfied -> construction succeeds, but NO model is loaded and no
    # inference library is imported (lazy load happens only on .read()).
    import sys

    llm = LlamaCppLLM(model_path="/nonexistent.gguf", allow_real_models=True)
    assert llm._llm is None
    assert "llama_cpp" not in sys.modules


def test_read_rechecks_gates(monkeypatch, tmp_path):
    llm = LlamaCppLLM(model_path="/nonexistent.gguf", allow_real_models=True)
    monkeypatch.setattr(harness, "PREREG_LOCK_FILE", tmp_path / "missing.md")
    with pytest.raises(EmbargoViolation):
        llm.read("prompt")


# --- runner ----------------------------------------------------------------------------------

def _items():
    out = []
    for i, (fam, tier, primary) in enumerate(
        [("A", "F", True), ("A", "M", True), ("B", "N", False)]
    ):
        for label in ("true", "false"):
            out.append({
                "item_id": f"d{i}#OP::{label}",
                "pair_id": f"d{i}#OP",
                "source_decl_id": f"d{i}",
                "statement": f"theorem t{i} (n : ℕ) : n = {i}",
                "label": label,
                "family": fam,
                "tier": tier,
                "operator": "A1" if fam == "A" else "B2",
                "primary_set": primary,
            })
    return out


def test_run_benchmark_primary_only_and_resume_safe(tmp_path):
    out = tmp_path / "run.jsonl"
    llm = MockLLM()
    res1 = run_benchmark(_items(), llm, out, benchmark_sha256="abc")
    assert res1["items_run"] == 4  # 2 Family-A pairs; Family-B pending items never scored
    res2 = run_benchmark(_items(), llm, out, benchmark_sha256="abc")
    assert res2["items_run"] == 0  # resume-safe: nothing re-queried
    recs = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(recs) == 4
    assert {r["tier"] for r in recs} == {"F", "M"}
    cfg = json.loads(out.with_suffix(".config.json").read_text())
    assert cfg["prompt_template_sha256"] == harness.PROMPT_TEMPLATE_SHA256
    assert cfg["benchmark_sha256"] == "abc"
    assert cfg["true_surface_forms"] == TRUE_SURFACE_FORMS
    assert cfg["false_surface_forms"] == FALSE_SURFACE_FORMS


def test_run_benchmark_counts_abstentions(tmp_path):
    class AbstainingMock(MockLLM):
        def read(self, prompt):
            return Reading(0.0, 0.0, "Hmm")

    res = run_benchmark(_items(), AbstainingMock(), tmp_path / "run.jsonl")
    assert res["abstentions"] == res["items_run"] == 4
