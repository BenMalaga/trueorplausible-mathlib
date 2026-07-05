"""Idempotent data fetch for TrueOrPlausible.

Pulls the public formal-math statement sources (verified live 2026-06-10; re-verified and
revision-pinned 2026-06-11, see PRE_REGISTRATION.md §4).
Raw data lands under data/ (gitignored). Re-running skips completed downloads.

Usage:
    python -m src.fetch_data --small     # tiny held-out/recency probe only (default, ~MBs)
    python -m src.fetch_data --pool      # stream-extract (declId, decl) from ntp-mathlib (RECOMMENDED)
    python -m src.fetch_data --statements # primary statement pool, FULL raw file (7.8 GB! prefer --pool)
    python -m src.fetch_data --types      # Apache-2.0 backup source (mathlib-types parquet, 90 MB)
    python -m src.fetch_data --all        # small + pool + types (never the raw 7.8 GB file)

Design notes (see data/README.md):
- NO Lean build is needed to read statement TEXT from any of these sources.
- `ntp-mathlib` has many rows per theorem (one per tactic step) -> dedupe on declId/decl.
- `mathlib-types` rows are declaration *types* (incl. auto-gen junk) -> filter to real Props.
- The Lean (B)-family verification pass (elan + `lake exe cache get`) is intentionally NOT
  done here; it is a one-time, heavier, later step. See the note at the bottom.

HARD CONSTRAINTS honored by this script: $0 spend, no model runs. The --statements / --types
downloads are hundreds-of-MB and are OPT-IN (not run by default).
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# --- Pinned dataset coordinates (revisions pinned 2026-06-11; PRE_REGISTRATION.md §4) ------
# The HF dataset revision is not the same as the Mathlib4 source commit the data was
# extracted from; both are recorded.

# Primary statement pool. License UNDECLARED on the HF card (Mathlib4 itself is Apache-2.0):
# attach an explicit license + Mathlib/miniCTX citation before redistributing any derivative.
# NOTE (measured 2026-06-12 via the HF tree API at the pinned revision): the single raw
# JSONL is 7,806,138,228 bytes (~7.8 GB) because every per-tactic row carries the full
# source file up to that tactic. We only need two small fields (`declId`, `decl`), so the
# default path is `--pool`: stream the file over HTTP and keep ONLY those fields
# (~tens of MB on disk); the 7.8 GB raw file is never written to disk.
NTP_MATHLIB = {
    "repo_id": "l3lab/ntp-mathlib",
    "filename": "Mathlib/tactic_prediction.jsonl",  # single raw JSONL, 7.8 GB (see note)
    "local_dir": DATA / "ntp-mathlib",
    "revision": "03b2ea6c3cf0a55203596445722ebb61c2328889",  # pinned 2026-06-11
    "mathlib_src_commit": "cf8e23a62939ed7cc530fbb68e83539730f32f86",  # provenance only
}
NTP_POOL_FILE = DATA / "ntp-mathlib" / "pool_decls.jsonl"
NTP_POOL_META = DATA / "ntp-mathlib" / "pool_decls.meta.json"

# Explicitly Apache-2.0 backup source. NOTE: declaration *types*, not curated theorems.
MATHLIB_TYPES = {
    "repo_id": "mathlib-initiative/mathlib-types",
    "local_dir": DATA / "mathlib-types",
    "revision": "f48c9324924a7a5b43ed6a5a6420028ecbcf09a6",  # pinned 2026-06-11
    "mathlib_src_commit": "c5ea00351c28e24afc9f0f84379aa41082b1188f",  # provenance only
}

# Tiny, timestamped held-out / recency probe (Apache-2.0).
# NOTE: the datasets auto-loader fails on miniCTX (mixed columns) -> read raw JSONL directly.
MINICTX = {
    "repo_id": "l3lab/miniCTX",
    "filename": "minictx-test/mathlib.jsonl",  # ~100 mathlib statements, tiny
    "local_dir": DATA / "minictx",
    "revision": "ba24e70d112679a004510b487ebdeee8c6606ec4",  # pinned 2026-06-11
}
MINICTX_V2 = {
    "repo_id": "l3lab/miniCTX-v2",
    # config files vary (carleson/ConNF/FLT/...); fetch the whole small repo snapshot.
    "local_dir": DATA / "minictx-v2",
    "revision": "91bd27f994c6fd6e3e1a85e7ad01c4ee0e6a01de",  # pinned 2026-06-11
}


def _hf_download_file(repo_id, filename, local_dir, revision=None):
    """Download a single file from an HF dataset repo (idempotent via HF cache)."""
    from huggingface_hub import hf_hub_download

    local_dir.mkdir(parents=True, exist_ok=True)
    print(f"[fetch] {repo_id}:{filename}  (rev={revision or 'HEAD'}) -> {local_dir}")
    path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        repo_type="dataset",
        revision=revision,
        local_dir=str(local_dir),
    )
    print(f"[fetch]   -> {path}")
    return path


def _hf_snapshot(repo_id, local_dir, revision=None):
    """Download a full dataset repo snapshot (idempotent via HF cache)."""
    from huggingface_hub import snapshot_download

    local_dir.mkdir(parents=True, exist_ok=True)
    print(f"[fetch] snapshot {repo_id}  (rev={revision or 'HEAD'}) -> {local_dir}")
    snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        revision=revision,
        local_dir=str(local_dir),
    )


def fetch_small() -> None:
    """Tiny, license-clean (Apache-2.0) held-out / recency probe (a few MB)."""
    _hf_download_file(**{k: MINICTX[k] for k in ("repo_id", "filename", "local_dir", "revision")})
    _hf_snapshot(**{k: MINICTX_V2[k] for k in ("repo_id", "local_dir", "revision")})


def fetch_statements() -> None:
    """Primary statement pool, FULL raw file (7.8 GB!). Prefer extract_pool() / --pool."""
    _hf_download_file(
        **{k: NTP_MATHLIB[k] for k in ("repo_id", "filename", "local_dir", "revision")}
    )


# --- Streaming pool extraction (the recommended path for the primary source) ---------------

def _scan_json_string(line: bytes, start: int) -> int:
    """Return the index of the closing unescaped '\"' of a JSON string starting at `start`."""
    i = start
    while True:
        j = line.index(b'"', i)
        nbs = 0
        k = j - 1
        while k >= start and line[k] == 0x5C:  # backslash
            nbs += 1
            k -= 1
        if nbs % 2 == 0:
            return j
        i = j + 1


def _extract_field(line: bytes, key: bytes):
    """Fast-path extraction of a top-level JSON string field from one compact JSONL row.

    The needle b'\"<key>\":\"' cannot occur inside another string value (raw quotes are
    escaped inside JSON string values), so a plain find is safe. Returns the decoded
    Python string, or None if the key is absent.
    """
    import json as _json

    for needle in (b'"' + key + b'":"', b'"' + key + b'": "'):
        p = line.find(needle)
        if p >= 0:
            start = p + len(needle)
            end = _scan_json_string(line, start)
            return _json.loads(b'"' + line[start:end] + b'"')
    return None


def extract_pool(force: bool = False) -> Path:
    """Stream the pinned 7.8 GB ntp-mathlib JSONL over HTTP, keeping ONLY (declId, decl).

    Writes data/ntp-mathlib/pool_decls.jsonl (one compact JSON object per source row, file
    order preserved, dedup happens later in src.build_benchmark exactly as registered in
    PRE_REGISTRATION.md §4) plus a .meta.json with row counts, the pinned revision, and a
    sha256 of the pool file. Idempotent: skips if the meta file exists (unless force).
    The raw 7.8 GB file is never written to disk.
    """
    import hashlib
    import json
    import urllib.request

    if NTP_POOL_META.exists() and not force:
        meta = json.loads(NTP_POOL_META.read_text())
        print(f"[pool] already extracted ({meta['rows_written']} rows) -> {NTP_POOL_FILE}")
        return NTP_POOL_FILE

    url = (
        f"https://huggingface.co/datasets/{NTP_MATHLIB['repo_id']}/resolve/"
        f"{NTP_MATHLIB['revision']}/{NTP_MATHLIB['filename']}"
    )
    NTP_POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = NTP_POOL_FILE.with_suffix(".jsonl.tmp")
    print(f"[pool] streaming {url}")
    rows_read = rows_written = parse_fallbacks = bytes_read = 0
    sha = hashlib.sha256()
    with urllib.request.urlopen(url) as resp, open(tmp, "wb") as out:
        buf = b""
        while True:
            chunk = resp.read(8 * 1024 * 1024)
            if not chunk:
                break
            bytes_read += len(chunk)
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                if not line.strip():
                    continue
                rows_read += 1
                decl_id = _extract_field(line, b"declId")
                decl = _extract_field(line, b"decl")
                if decl_id is None or decl is None:  # fall back to a full JSON parse
                    parse_fallbacks += 1
                    row = json.loads(line)
                    decl_id, decl = row.get("declId"), row.get("decl")
                    if decl_id is None or decl is None:
                        continue  # malformed row: counted via parse_fallbacks
                rec = json.dumps(
                    {"declId": decl_id, "decl": decl}, ensure_ascii=False
                ).encode("utf-8") + b"\n"
                out.write(rec)
                sha.update(rec)
                rows_written += 1
                if rows_written % 50_000 == 0:
                    print(f"[pool]   {rows_written} rows ({bytes_read/1e9:.1f} GB read)")
        if buf.strip():  # final unterminated line, if any
            rows_read += 1
            row = json.loads(buf)
            if "declId" in row and "decl" in row:
                rec = json.dumps(
                    {"declId": row["declId"], "decl": row["decl"]}, ensure_ascii=False
                ).encode("utf-8") + b"\n"
                out.write(rec)
                sha.update(rec)
                rows_written += 1
    tmp.rename(NTP_POOL_FILE)
    meta = {
        "source_repo": NTP_MATHLIB["repo_id"],
        "source_filename": NTP_MATHLIB["filename"],
        "source_revision": NTP_MATHLIB["revision"],
        "mathlib_src_commit": NTP_MATHLIB["mathlib_src_commit"],
        "source_bytes_read": bytes_read,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "parse_fallbacks": parse_fallbacks,
        "pool_sha256": sha.hexdigest(),
        "fields_kept": ["declId", "decl"],
    }
    NTP_POOL_META.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"[pool] wrote {rows_written} rows -> {NTP_POOL_FILE}")
    print(f"[pool] meta -> {NTP_POOL_META}")
    return NTP_POOL_FILE


def fetch_types() -> None:
    """Apache-2.0 backup source (90 MB parquet). Opt-in; never fetched by default."""
    _hf_snapshot(**{k: MATHLIB_TYPES[k] for k in ("repo_id", "local_dir", "revision")})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--small", action="store_true", help="tiny recency/held-out probe (default)")
    ap.add_argument("--pool", action="store_true", help="stream-extract (declId, decl) pool")
    ap.add_argument("--statements", action="store_true", help="FULL raw ntp-mathlib (7.8 GB!)")
    ap.add_argument("--types", action="store_true", help="mathlib-types parquet (90 MB)")
    ap.add_argument("--all", action="store_true", help="small + pool + types (not the raw file)")
    ap.add_argument("--force", action="store_true", help="re-extract the pool even if present")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)
    did_anything = False
    if args.all or args.small or not (args.pool or args.statements or args.types or args.all):
        # Default to the small probe so an accidental bare run never pulls GBs.
        fetch_small()
        did_anything = True
    if args.all or args.pool:
        extract_pool(force=args.force)
        did_anything = True
    if args.statements:
        fetch_statements()
        did_anything = True
    if args.all or args.types:
        fetch_types()
        did_anything = True

    if did_anything:
        print("[fetch] done")

    # --- NOTE: Lean (B)-family verification pass (NOT done here) ---------------------------
    # This is the hardest engineering step and is intentionally deferred (see
    # PRE_REGISTRATION.md §3). Do NOT attempt a from-scratch mathlib4 build on 8GB.
    # Realistic path:
    #   1. curl -sSf https://elan.lean-lang.org/elan-init.sh | sh   # install elan
    #   2. lake exe cache get                                       # pull precompiled .olean
    #   3. for each (B) mutant: emit a tiny .lean importing ONLY the modules its declId needs
    #      (use file_tag / a mathlib-const-dep graph), then `lake env lean` headless, one
    #      statement at a time. A mutant that still typechecks as a theorem is STILL TRUE ->
    #      drop it (and the drop rate is a reported result).
    #   Fallback: offload this one-time pass to a free hosted runner (Colab / GH Actions),
    #   or ship (A)-only for v1 and document (B) as a limitation. Never keep unverified (B)
    #   labels silently.


if __name__ == "__main__":
    main()
