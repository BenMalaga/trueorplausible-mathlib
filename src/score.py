"""Scoring for TrueOrPlausible, the pre-registered metrics, exactly as locked (§7-§8).

Implements:
  - AUROC (tie-aware, rank-based), pooled, per tier, per model
  - calibration: ECE with 10 EQUAL-MASS bins over the model's confidence in its
    PREDICTED label; Brier score; reliability-diagram bin table
  - the surface-feature logistic baseline (scikit-learn LogisticRegression, L2, C = 1.0;
    5-fold group-stratified CV grouped by source theorem; AUROC from out-of-fold scores)
  - cluster bootstrap resampling SOURCE THEOREMS (pairs stay together),
    n_boot = 2,000, seed 20260611, 95% percentile intervals (+ one-sided lower bounds)
  - Holm-Bonferroni correction across the locked roster (m = 5) for H1
  - abstention protocol: items answering neither True nor False are excluded from the
    metrics and the abstention rate is reported (never silently dropped)

This module sees only (label, confidence) records, it contains no model code and runs
identically on mock and (post-embargo) real outputs. Validated on synthetic predictions
with a planted signal and a null in tests/test_score.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .mutate import MutationError, explicit_binder_groups, split_signature

# --- Registered constants (PRE_REGISTRATION.md §7-§8) ----------------------------------------

N_BOOT = 2000
BOOT_SEED = 20260611
ECE_BINS = 10
ROSTER_SIZE = 5            # Holm-Bonferroni m for H1
BASELINE_C = 1.0           # logistic-regression L2 strength (sklearn C)
BASELINE_FOLDS = 5
SURFACE_SYMBOLS = list("∀∃¬≠≤<≥>=∈∉→↔∧∨")   # §7 symbol-count features


# --- Core metrics ------------------------------------------------------------------------------

def auroc(y_true, score) -> float:
    """Tie-aware AUROC via the rank (Mann-Whitney) statistic."""
    y = np.asarray(y_true, dtype=float)
    s = np.asarray(score, dtype=float)
    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    ranks[order] = np.arange(1, len(s) + 1)
    # average ranks for ties
    s_sorted = s[order]
    i = 0
    while i < len(s_sorted):
        j = i
        while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = ranks[order[i : j + 1]].mean()
        i = j + 1
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def predicted_label_confidence(conf_true) -> tuple[np.ndarray, np.ndarray]:
    """Map P(true) to (predicted_label, confidence-in-predicted-label)."""
    c = np.asarray(conf_true, dtype=float)
    pred = (c >= 0.5).astype(int)
    conf = np.where(pred == 1, c, 1.0 - c)
    return pred, conf


def ece_equal_mass(y_true, conf_true, n_bins: int = ECE_BINS):
    """ECE over n_bins EQUAL-MASS bins of confidence in the predicted label (§8).

    Returns (ece, bin_table) where bin_table rows are
    (bin_size, mean_confidence, accuracy) for the reliability diagram.
    """
    y = np.asarray(y_true, dtype=int)
    pred, conf = predicted_label_confidence(conf_true)
    correct = (pred == y).astype(float)
    order = np.argsort(conf, kind="mergesort")
    bins = np.array_split(order, n_bins)
    n = len(y)
    ece = 0.0
    table = []
    for b in bins:
        if len(b) == 0:
            continue
        mc, acc = float(conf[b].mean()), float(correct[b].mean())
        ece += (len(b) / n) * abs(acc - mc)
        table.append({"n": int(len(b)), "mean_confidence": mc, "accuracy": acc})
    return float(ece), table


def brier(y_true, conf_true) -> float:
    """Brier score of P(true) against the binary truth label."""
    y = np.asarray(y_true, dtype=float)
    c = np.asarray(conf_true, dtype=float)
    return float(np.mean((c - y) ** 2))


# --- Cluster bootstrap (§8) --------------------------------------------------------------------

def cluster_bootstrap(stat_fn, clusters, n_boot: int = N_BOOT, seed: int = BOOT_SEED):
    """Bootstrap a statistic by resampling CLUSTERS (source theorems) with replacement.

    ``stat_fn(idx)`` computes the statistic on item indices ``idx``; ``clusters`` is the
    per-item cluster label (pairs share a cluster, so pairs stay together, §8).
    Returns point estimate, bootstrap samples, two-sided 95% percentile CI, and the
    one-sided 95% lower bound (5th percentile).
    """
    clusters = np.asarray(clusters)
    uniq = np.unique(clusters)
    members = {c: np.flatnonzero(clusters == c) for c in uniq}
    rng = np.random.default_rng(seed)
    point = float(stat_fn(np.arange(len(clusters))))
    samples = np.empty(n_boot)
    for b in range(n_boot):
        chosen = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([members[c] for c in chosen])
        samples[b] = stat_fn(idx)
    samples = samples[~np.isnan(samples)]
    return {
        "point": point,
        "n_boot": n_boot,
        "n_boot_valid": int(len(samples)),
        "ci95_low": float(np.percentile(samples, 2.5)),
        "ci95_high": float(np.percentile(samples, 97.5)),
        "one_sided_lower95": float(np.percentile(samples, 5.0)),
        "samples": samples,
    }


def bootstrap_p_leq_null(samples, null_value: float) -> float:
    """One-sided bootstrap p-value: evidence that the statistic exceeds ``null_value``."""
    s = np.asarray(samples, dtype=float)
    return float((1 + int((s <= null_value).sum())) / (len(s) + 1))


def holm_bonferroni(pvals: dict, alpha: float = 0.05) -> dict:
    """Holm-Bonferroni step-down correction. Returns {name: (p_adjusted, reject)}."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, running_max, still_rejecting = {}, 0.0, True
    for rank, (name, p) in enumerate(items):
        adj = min(1.0, (m - rank) * p)
        running_max = max(running_max, adj)
        reject = still_rejecting and running_max <= alpha
        if not reject:
            still_rejecting = False
        out[name] = {"p_raw": float(p), "p_holm": float(running_max), "reject": bool(reject)}
    return out


# --- Surface-feature baseline (§7) ---------------------------------------------------------------

FEATURE_NAMES = (
    ["char_length", "ws_token_count"]
    + [f"count_{s}" for s in SURFACE_SYMBOLS]
    + ["digit_count", "max_bracket_depth", "explicit_binder_groups"]
)


def surface_features(statement: str) -> list[float]:
    """The §7 feature vector for one statement (registered list, nothing more)."""
    feats = [float(len(statement)), float(len(statement.split()))]
    feats += [float(statement.count(sym)) for sym in SURFACE_SYMBOLS]
    feats.append(float(sum(ch.isdigit() for ch in statement)))
    depth = max_depth = 0
    for ch in statement:
        if ch in "([{⟨⦃":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch in ")]}⟩⦄":
            depth -= 1
    feats.append(float(max_depth))
    try:
        header, _, _ = split_signature(statement)
        n_binders = len(explicit_binder_groups(header))
    except (MutationError, ValueError):
        n_binders = 0
    feats.append(float(n_binders))
    return feats


def surface_baseline(statements, y_true, groups, seed: int = BOOT_SEED):
    """§7 baseline: L2 logistic regression (C = 1.0) on surface features, evaluated by
    5-fold group-stratified CV grouped by source theorem; AUROC from out-of-fold scores.

    Returns {"auroc", "oof_scores", "n_folds"}; oof_scores align with the input order
    (needed for H4's paired bootstrap against the best model).
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedGroupKFold
    from sklearn.preprocessing import StandardScaler

    X = np.asarray([surface_features(s) for s in statements], dtype=float)
    y = np.asarray(y_true, dtype=int)
    g = np.asarray(groups)
    cv = StratifiedGroupKFold(n_splits=BASELINE_FOLDS, shuffle=True, random_state=seed)
    oof = np.full(len(y), np.nan)
    for train, test in cv.split(X, y, g):
        scaler = StandardScaler().fit(X[train])
        clf = LogisticRegression(penalty="l2", C=BASELINE_C, max_iter=1000)
        clf.fit(scaler.transform(X[train]), y[train])
        oof[test] = clf.predict_proba(scaler.transform(X[test]))[:, 1]
    assert not np.isnan(oof).any(), "out-of-fold coverage incomplete"
    return {"auroc": auroc(y, oof), "oof_scores": oof, "n_folds": BASELINE_FOLDS}


# --- Run-level scoring (per model) ----------------------------------------------------------------

def _to_arrays(records):
    """records: dicts with label / confidence_true / abstained / source_decl_id / tier."""
    kept = [r for r in records if not r.get("abstained", False)]
    y = np.array([1 if r["label"] == "true" else 0 for r in kept], dtype=int)
    c = np.array([r["confidence_true"] for r in kept], dtype=float)
    cl = np.array([r["source_decl_id"] for r in kept])
    tiers = np.array([r.get("tier", "") for r in kept])
    return y, c, cl, tiers, len(records) - len(kept)


def score_model_run(records, n_boot: int = N_BOOT, seed: int = BOOT_SEED) -> dict:
    """All pre-registered per-model metrics for one model's run records."""
    y, c, clusters, tiers, n_abstained = _to_arrays(records)
    res: dict = {
        "n_items_scored": int(len(y)),
        "n_abstained": int(n_abstained),
        "abstention_rate": float(n_abstained / max(1, len(records))),
    }

    boot = cluster_bootstrap(lambda idx: auroc(y[idx], c[idx]), clusters, n_boot, seed)
    samples = boot.pop("samples")
    res["auroc_pooled"] = boot
    res["h1_p_vs_chance"] = bootstrap_p_leq_null(samples, 0.5)

    res["auroc_per_tier"] = {}
    for tier in sorted(set(tiers)):
        mask = tiers == tier
        res["auroc_per_tier"][tier] = float(auroc(y[mask], c[mask]))

    # H2 primary contrast: AUROC(F) − AUROC(M), same cluster resample for both tiers.
    if {"F", "M"} <= set(tiers):
        def contrast(idx):
            t = tiers[idx]
            return auroc(y[idx][t == "F"], c[idx][t == "F"]) - auroc(
                y[idx][t == "M"], c[idx][t == "M"]
            )

        cb = cluster_bootstrap(contrast, clusters, n_boot, seed)
        cb.pop("samples")
        res["h2_contrast_F_minus_M"] = cb

    ece, bin_table = ece_equal_mass(y, c)
    res["ece"] = ece
    res["reliability_bins"] = bin_table
    res["brier"] = brier(y, c)
    return res


def h1_holm_across_roster(per_model_p: dict) -> dict:
    """H1's multiple-comparison correction across the locked roster (m = 5)."""
    if len(per_model_p) > ROSTER_SIZE:
        raise ValueError(f"roster has {ROSTER_SIZE} models; got {len(per_model_p)} p-values")
    return holm_bonferroni(per_model_p)


def h4_model_vs_baseline(records, baseline_oof, n_boot=N_BOOT, seed=BOOT_SEED) -> dict:
    """H4: paired cluster bootstrap of (best-model AUROC − surface-baseline AUROC).

    ``records`` must align one-to-one with ``baseline_oof`` (same item order).
    """
    y = np.array([1 if r["label"] == "true" else 0 for r in records], dtype=int)
    c = np.array([r["confidence_true"] for r in records], dtype=float)
    clusters = np.array([r["source_decl_id"] for r in records])
    b = np.asarray(baseline_oof, dtype=float)

    def diff(idx):
        return auroc(y[idx], c[idx]) - auroc(y[idx], b[idx])

    out = cluster_bootstrap(diff, clusters, n_boot, seed)
    samples = out.pop("samples")
    out["p_leq_zero"] = bootstrap_p_leq_null(samples, 0.0)
    return out


def load_run_records(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]
