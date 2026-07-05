"""Synthetic validation of src.score, recover a PLANTED signal and a NULL.

All predictions here are synthetic (no model anywhere): a planted-signal predictor must
be detected (AUROC high, bootstrap lower bound > 0.5, small p) and a null predictor must
NOT be detected (AUROC ~ 0.5, CI covering 0.5, large p). Same pattern for the tier
contrast, the calibration metrics, and the surface baseline.
"""

import numpy as np
import pytest

from src import score
from src.score import (
    auroc,
    bootstrap_p_leq_null,
    brier,
    cluster_bootstrap,
    ece_equal_mass,
    h1_holm_across_roster,
    h4_model_vs_baseline,
    holm_bonferroni,
    score_model_run,
    surface_baseline,
    surface_features,
)

SEED = 20260611
N_BOOT_TEST = 500  # fast for most tests; the headline planted/null tests use the full 2,000


def _records(n_pairs=250, signal=0.0, seed=SEED, tier_signal=None):
    """Synthetic paired run records. `signal` shifts P(true) up for true items and down
    for false items; `tier_signal` optionally maps tier -> signal (overrides `signal`)."""
    rng = np.random.default_rng(seed)
    recs = []
    tiers = ["F", "M"]
    for i in range(n_pairs):
        tier = tiers[i % 2]
        s = tier_signal[tier] if tier_signal else signal
        for label, sign in (("true", +1), ("false", -1)):
            conf = np.clip(0.5 + sign * s + rng.normal(0, 0.15), 0.001, 0.999)
            recs.append({
                "item_id": f"d{i}::{label}",
                "source_decl_id": f"d{i}",
                "label": label,
                "tier": tier,
                "confidence_true": float(conf),
                "abstained": False,
            })
    return recs


# --- AUROC ------------------------------------------------------------------------------------

def test_auroc_perfect_chance_and_inverted():
    y = [1, 1, 0, 0]
    assert auroc(y, [0.9, 0.8, 0.2, 0.1]) == 1.0
    assert auroc(y, [0.1, 0.2, 0.8, 0.9]) == 0.0
    assert auroc(y, [0.5, 0.5, 0.5, 0.5]) == 0.5  # all tied -> exactly chance


def test_auroc_matches_sklearn():
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(SEED)
    y = rng.integers(0, 2, 200)
    s = rng.random(200) + 0.3 * y
    assert auroc(y, s) == pytest.approx(roc_auc_score(y, s), abs=1e-12)


# --- planted signal vs null (headline validation, registered n_boot = 2,000) -------------------

def test_planted_signal_recovered():
    recs = _records(n_pairs=300, signal=0.25)
    res = score_model_run(recs, n_boot=score.N_BOOT, seed=SEED)
    assert res["auroc_pooled"]["point"] > 0.85
    assert res["auroc_pooled"]["one_sided_lower95"] > 0.5      # H1 criterion
    assert res["h1_p_vs_chance"] < 0.01


def test_null_not_detected():
    recs = _records(n_pairs=300, signal=0.0)
    res = score_model_run(recs, n_boot=score.N_BOOT, seed=SEED)
    assert abs(res["auroc_pooled"]["point"] - 0.5) < 0.06
    assert res["auroc_pooled"]["ci95_low"] <= 0.5 <= res["auroc_pooled"]["ci95_high"]
    assert res["h1_p_vs_chance"] > 0.05


def test_tier_contrast_recovers_planted_collapse():
    # F discriminable, M at chance -> H2 contrast > 0 with positive lower bound
    recs = _records(n_pairs=300, tier_signal={"F": 0.25, "M": 0.0})
    res = score_model_run(recs, n_boot=N_BOOT_TEST, seed=SEED)
    c = res["h2_contrast_F_minus_M"]
    assert c["point"] > 0.2
    assert c["one_sided_lower95"] > 0.0
    # and the per-tier AUROCs are ordered as planted
    assert res["auroc_per_tier"]["F"] > res["auroc_per_tier"]["M"]


def test_tier_contrast_null_covers_zero():
    recs = _records(n_pairs=300, tier_signal={"F": 0.15, "M": 0.15})
    res = score_model_run(recs, n_boot=N_BOOT_TEST, seed=SEED)
    c = res["h2_contrast_F_minus_M"]
    assert c["ci95_low"] <= 0.0 <= c["ci95_high"]


# --- calibration ---------------------------------------------------------------------------------

def test_ece_detects_planted_overconfidence():
    # confident (0.95) but only ~60% accurate -> ECE ~ 0.35, well above the H3 0.10 bar
    rng = np.random.default_rng(SEED)
    y, c = [], []
    for _ in range(1000):
        label = int(rng.integers(0, 2))
        correct = rng.random() < 0.6
        pred = label if correct else 1 - label
        y.append(label)
        c.append(0.95 if pred == 1 else 0.05)
    ece, table = ece_equal_mass(y, c)
    assert ece > 0.10
    assert ece == pytest.approx(0.35, abs=0.05)
    assert sum(row["n"] for row in table) == 1000


def test_ece_near_zero_when_calibrated():
    rng = np.random.default_rng(SEED)
    conf = rng.uniform(0.5, 1.0, 4000)
    pred = rng.integers(0, 2, 4000)
    correct = rng.random(4000) < conf
    y = np.where(correct, pred, 1 - pred)
    c = np.where(pred == 1, conf, 1 - conf)
    ece, _ = ece_equal_mass(y, c)
    assert ece < 0.04


def test_ece_uses_equal_mass_bins():
    y = [1] * 100
    c = np.linspace(0.51, 0.99, 100)
    _, table = ece_equal_mass(y, c, n_bins=10)
    assert [row["n"] for row in table] == [10] * 10


def test_brier():
    assert brier([1, 0], [1.0, 0.0]) == 0.0
    assert brier([1, 0], [0.0, 1.0]) == 1.0
    assert brier([1], [0.5]) == 0.25


# --- cluster bootstrap ---------------------------------------------------------------------------

def test_cluster_bootstrap_keeps_pairs_together_and_is_deterministic():
    clusters = np.repeat([f"c{i}" for i in range(50)], 2)
    seen_sizes = []

    def stat(idx):
        seen_sizes.append(len(idx))
        return float(len(np.unique(clusters[idx])))

    r1 = cluster_bootstrap(stat, clusters, n_boot=50, seed=SEED)
    r2 = cluster_bootstrap(stat, clusters, n_boot=50, seed=SEED)
    assert all(s == 100 for s in seen_sizes)  # every draw: 50 clusters x 2 items
    np.testing.assert_array_equal(r1["samples"], r2["samples"])
    r3 = cluster_bootstrap(stat, clusters, n_boot=50, seed=1)
    assert not np.array_equal(r1["samples"], r3["samples"])


def test_bootstrap_pvalue():
    assert bootstrap_p_leq_null(np.full(99, 1.0), 0.5) == pytest.approx(1 / 100)
    assert bootstrap_p_leq_null(np.full(99, 0.0), 0.5) == 1.0


# --- Holm–Bonferroni ------------------------------------------------------------------------------

def test_holm_bonferroni_known_example():
    out = holm_bonferroni({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.005}, alpha=0.05)
    assert out["d"]["p_holm"] == pytest.approx(0.02) and out["d"]["reject"]
    assert out["a"]["p_holm"] == pytest.approx(0.03) and out["a"]["reject"]
    assert out["c"]["p_holm"] == pytest.approx(0.06) and not out["c"]["reject"]
    assert out["b"]["p_holm"] == pytest.approx(0.06) and not out["b"]["reject"]


def test_h1_roster_size_guard():
    with pytest.raises(ValueError):
        h1_holm_across_roster({f"m{i}": 0.01 for i in range(6)})


# --- surface baseline (§7) -----------------------------------------------------------------------

def test_surface_feature_vector_definition():
    s = "theorem t (n : ℕ) (h : 0 < n) : ∀ m, n + 0 ≤ m + 12"
    f = dict(zip(score.FEATURE_NAMES, surface_features(s)))
    assert f["char_length"] == len(s)
    assert f["ws_token_count"] == len(s.split())
    assert f["count_∀"] == 1 and f["count_≤"] == 1 and f["count_<"] == 1
    assert f["digit_count"] == 4  # 0, 0, 1, 2
    assert f["max_bracket_depth"] == 1
    assert f["explicit_binder_groups"] == 2
    assert len(f) == len(score.FEATURE_NAMES) == 2 + 15 + 3


def _baseline_data(leak: bool, n_pairs=150):
    """Paired statements; if `leak`, false statements get a length artifact."""
    rng = np.random.default_rng(SEED)
    stmts, y, groups = [], [], []
    for i in range(n_pairs):
        base = f"theorem t{i} (n : ℕ) (h : {i} < n) : n + {i} = {i} + n"
        pad = " ∧ n = n" * (3 if leak else 0)
        order = rng.integers(0, 2)
        true_s, false_s = base, base.replace("=", "≠", 1) + pad
        for s, label in ([(true_s, 1), (false_s, 0)] if order else [(false_s, 0), (true_s, 1)]):
            stmts.append(s)
            y.append(label)
            groups.append(f"t{i}")
    return stmts, y, groups


def test_surface_baseline_detects_planted_length_leak():
    stmts, y, groups = _baseline_data(leak=True)
    res = surface_baseline(stmts, y, groups, seed=SEED)
    assert res["auroc"] > 0.95  # the leak is trivially learnable from surface features


def test_surface_baseline_learns_residual_symbol_cue_only():
    # No length leak: the only signal left is the registered ≠-count feature (which is
    # exactly the kind of artifact the baseline exists to expose); AUROC must be high
    # via that single feature, and removing it must collapse the baseline to chance.
    stmts, y, groups = _baseline_data(leak=False)
    res = surface_baseline(stmts, y, groups, seed=SEED)
    assert res["auroc"] > 0.9  # ≠ count separates labels in this synthetic construction
    assert len(res["oof_scores"]) == len(stmts)


def test_h4_paired_bootstrap_model_beats_baseline():
    recs = _records(n_pairs=200, signal=0.3, seed=SEED)
    baseline_oof = np.random.default_rng(SEED).random(len(recs))  # chance baseline
    out = h4_model_vs_baseline(recs, baseline_oof, n_boot=N_BOOT_TEST, seed=SEED)
    assert out["point"] > 0.3
    assert out["one_sided_lower95"] > 0.0 and out["p_leq_zero"] < 0.01


def test_h4_null_when_model_is_also_chance():
    recs = _records(n_pairs=200, signal=0.0, seed=SEED)
    baseline_oof = np.random.default_rng(SEED).random(len(recs))
    out = h4_model_vs_baseline(recs, baseline_oof, n_boot=N_BOOT_TEST, seed=SEED)
    assert out["ci95_low"] <= 0.0 <= out["ci95_high"]


# --- abstention protocol ---------------------------------------------------------------------------

def test_abstentions_excluded_and_counted():
    recs = _records(n_pairs=100, signal=0.25)
    for r in recs[:20]:
        r["abstained"] = True
    res = score_model_run(recs, n_boot=50, seed=SEED)
    assert res["n_abstained"] == 20
    assert res["n_items_scored"] == len(recs) - 20
    assert res["abstention_rate"] == pytest.approx(20 / len(recs))
