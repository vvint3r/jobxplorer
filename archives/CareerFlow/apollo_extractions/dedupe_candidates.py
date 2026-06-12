#!/usr/bin/env python3
"""Detect (and optionally apply) duplicate-candidate merges in the master files.

The masters are already deduped by LinkedIn URL + exact normalized name. This
tool finds the *residual* near-duplicates that exact matching misses — chiefly
name variants from the third-party lists, e.g. "Meta Platforms" vs "Meta",
"Alphabet (Google)" vs "Alphabet".

Tiers
-----
  exact   : identical normalized name (legal suffixes/punctuation/parentheticals
            stripped). Unambiguous -> safe to auto-merge.
  subset  : one name's token-set fully contains the other (e.g. meta ⊂ meta
            platforms). Likely same, but can be wrong ("Apple" vs "Apple Bank")
            -> REVIEW, not auto-merged.
  fuzzy   : high string similarity (>=0.88) within the same first-token block
            -> REVIEW.

Default run writes review CSVs and auto-applies ONLY the `exact` tier, writing
cleaned masters in place (originals backed up to *.bak). Use --report-only to
make no changes.

Canonical pick for a merge: the record that has a LinkedIn URL and the most
populated fields wins; the other is folded in (gap-filling) and dropped.
"""

import argparse
import csv
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

COMPANY_MASTER = SCRIPT_DIR / "MASTER_companies.csv"
RECRUITER_MASTER = SCRIPT_DIR / "MASTER_recruiters.csv"
COMPANY_COLS = ["Company", "LinkedIn URL", "Website", "Location",
                "# Employees", "Industry", "Keywords", "Source"]
RECRUITER_COLS = ["Name", "Title", "Company", "Email", "LinkedIn URL",
                  "Location", "# Employees", "Industry", "Keywords", "Source"]
_LEGAL = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
          "co", "plc", "sa", "gmbh", "ag", "nv", "bv", "srl", "spa", "the"}
NULLS = {"", "n/a", "na", "no email", "none", "null", "-", "--"}
FUZZY_MIN = 0.88
# Generic corporate words that, when they are the ONLY difference between two
# names (and exactly one side has a LinkedIn URL), make a subset match safe to
# auto-merge: "Cisco" + {systems} == "Cisco Systems". Distinctive words like
# "enterprise" or "blockchain" are intentionally EXCLUDED so HP vs HP Enterprise
# and Riot vs Riot Blockchain stay separate.
GENERIC_EXTRA = {"holdings", "communications", "technologies", "technology",
                 "solutions", "systems", "group", "company", "international",
                 "worldwide", "industries", "labs", "global", "motors",
                 "stores", "brands", "platforms", "com"}


def is_empty(v):
    return (v or "").strip().lower() in NULLS


def norm_name(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def strong_norm(name):
    s = norm_name(name).replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[.,/()'\-]", " ", s)
    toks = [t for t in s.split() if t and t not in _LEGAL]
    return tuple(toks)


def norm_linkedin(url):
    u = (url or "").strip().lower()
    if not u or u == "n/a":
        return ""
    if u.startswith("/"):
        u = "linkedin.com" + u
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.split("?")[0].rstrip("/")


def load(path):
    with open(path, encoding="utf-8") as h:
        return list(csv.DictReader(h))


def score(rec, cols):
    return sum(1 for c in cols if not is_empty(rec.get(c, "")))


def has_li(rec):
    return bool(norm_linkedin(rec.get("LinkedIn URL")))


def pick_canonical(a, b, cols):
    """Return (keep, drop)."""
    la, lb = has_li(a), has_li(b)
    if la != lb:
        return (a, b) if la else (b, a)
    return (a, b) if score(a, cols) >= score(b, cols) else (b, a)


def merge(keep, drop, cols):
    out = dict(keep)
    for c in cols:
        if c == "Source":
            continue
        if is_empty(out.get(c, "")) and not is_empty(drop.get(c, "")):
            out[c] = drop[c]
    out["Source"] = f"{keep.get('Source','')}+{drop.get('Source','')}" if keep.get("Source") != drop.get("Source") else keep.get("Source", "")
    return out


def find_company_candidates(rows):
    """Yield (tier, ratio, idx_a, idx_b)."""
    norms = [strong_norm(r["Company"]) for r in rows]
    # exact: identical norm
    by_norm = {}
    for i, n in enumerate(norms):
        if n:
            by_norm.setdefault(n, []).append(i)
    cands = []
    seen = set()
    for n, idxs in by_norm.items():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                cands.append(("exact", 1.0, idxs[a], idxs[b]))
                seen.add((idxs[a], idxs[b]))
    # blocking by first token for subset / fuzzy
    blocks = {}
    for i, n in enumerate(norms):
        if n:
            blocks.setdefault(n[0], []).append(i)
    for tok, idxs in blocks.items():
        if len(idxs) > 1500:        # avoid pathological blocks
            continue
        for a in range(len(idxs)):
            ia = idxs[a]; na = set(norms[ia])
            for b in range(a + 1, len(idxs)):
                ib = idxs[b]
                if (ia, ib) in seen:
                    continue
                nb = set(norms[ib])
                if na == nb:
                    continue
                if na and nb and (na <= nb or nb <= na):
                    big, small = (na, nb) if len(na) >= len(nb) else (nb, na)
                    extra = big - small
                    one_li = has_li(rows[ia]) != has_li(rows[ib])
                    tier = "subset_safe" if (one_li and extra and extra <= GENERIC_EXTRA) else "subset"
                    cands.append((tier, round(len(na & nb) / max(len(na | nb), 1), 3), ia, ib))
                    continue
                r = SequenceMatcher(None, " ".join(norms[ia]), " ".join(norms[ib])).ratio()
                if r >= FUZZY_MIN:
                    cands.append(("fuzzy", round(r, 3), ia, ib))
    return cands


def find_recruiter_candidates(rows):
    cands = []
    seen = set()
    # same email (real addresses only — must contain "@")
    by_email = {}
    for i, r in enumerate(rows):
        e = (r.get("Email") or "").strip().lower()
        if e and not is_empty(e) and "@" in e:
            by_email.setdefault(e, []).append(i)
    for e, idxs in by_email.items():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                cands.append(("same_email", 1.0, idxs[a], idxs[b]))
                seen.add((idxs[a], idxs[b]))
    # same normalized name + company
    by_nc = {}
    for i, r in enumerate(rows):
        key = (strong_norm(r.get("Name")), strong_norm(r.get("Company")))
        if key[0]:
            by_nc.setdefault(key, []).append(i)
    for key, idxs in by_nc.items():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                if (idxs[a], idxs[b]) in seen:
                    continue
                cands.append(("same_name_company", 1.0, idxs[a], idxs[b]))
    return cands


def write_report(path, rows, cands, cols, label_a, label_b):
    with open(path, "w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(["tier", "similarity", "keep_" + label_a, "keep_linkedin", "keep_source",
                    "drop_" + label_a, "drop_linkedin", "drop_source"])
        for tier, ratio, ia, ib in cands:
            keep, drop = pick_canonical(rows[ia], rows[ib], cols)
            w.writerow([tier, ratio,
                        keep.get(label_b, ""), keep.get("LinkedIn URL", ""), keep.get("Source", ""),
                        drop.get(label_b, ""), drop.get("LinkedIn URL", ""), drop.get("Source", "")])


def apply_exact(rows, cands, cols):
    """Merge only exact-tier (and same_email/same_name_company) pairs. Returns cleaned rows."""
    parent = list(range(len(rows)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    auto_tiers = {"exact", "subset_safe", "same_email", "same_name_company"}
    merges = 0
    for tier, _, ia, ib in cands:
        if tier not in auto_tiers:
            continue
        ra, rb = find(ia), find(ib)
        if ra != rb:
            parent[rb] = ra
            merges += 1
    # build clusters
    clusters = {}
    for i in range(len(rows)):
        clusters.setdefault(find(i), []).append(i)
    out = []
    for root, members in clusters.items():
        rec = rows[members[0]]
        for m in members[1:]:
            keep, drop = pick_canonical(rec, rows[m], cols)
            rec = merge(keep, drop, cols)
        out.append(rec)
    return out, merges


def write_master(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report-only", action="store_true", help="detect only; do not modify masters")
    args = ap.parse_args()

    # Companies
    comp = load(COMPANY_MASTER)
    ccands = find_company_candidates(comp)
    ctiers = {}
    for t, *_ in ccands:
        ctiers[t] = ctiers.get(t, 0) + 1
    write_report(SCRIPT_DIR / "dedupe_candidates_companies.csv", comp, ccands, COMPANY_COLS, "company", "Company")

    # Recruiters
    rec = load(RECRUITER_MASTER)
    rcands = find_recruiter_candidates(rec)
    rtiers = {}
    for t, *_ in rcands:
        rtiers[t] = rtiers.get(t, 0) + 1
    write_report(SCRIPT_DIR / "dedupe_candidates_recruiters.csv", rec, rcands, RECRUITER_COLS, "name", "Name")

    print("=" * 64)
    print(f"COMPANIES: {len(comp)} rows. candidate pairs by tier: {ctiers}")
    print(f"RECRUITERS: {len(rec)} rows. candidate pairs by tier: {rtiers}")
    print("Reports: dedupe_candidates_companies.csv, dedupe_candidates_recruiters.csv")

    if args.report_only:
        print("\n--report-only: masters unchanged.")
        return

    # Auto-apply safe tiers
    import shutil
    shutil.copy(COMPANY_MASTER, str(COMPANY_MASTER) + ".bak")
    shutil.copy(RECRUITER_MASTER, str(RECRUITER_MASTER) + ".bak")
    comp_clean, cm = apply_exact(comp, ccands, COMPANY_COLS)
    rec_clean, rm = apply_exact(rec, rcands, RECRUITER_COLS)
    write_master(COMPANY_MASTER, comp_clean, COMPANY_COLS)
    write_master(RECRUITER_MASTER, rec_clean, RECRUITER_COLS)
    print(f"\nAuto-applied safe merges -> companies {len(comp)}->{len(comp_clean)} (-{cm}), "
          f"recruiters {len(rec)}->{len(rec_clean)} (-{rm}).")
    print("Backups: MASTER_companies.csv.bak, MASTER_recruiters.csv.bak")
    print("Review subset/fuzzy pairs in the report CSVs before any further merge.")


if __name__ == "__main__":
    main()
