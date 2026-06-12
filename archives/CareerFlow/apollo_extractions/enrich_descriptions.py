#!/usr/bin/env python3
"""Generate concise, factual company descriptions with gpt-4o-mini.

- Batches companies (20/call) using name + industry + HQ + website/LinkedIn as
  grounding context.
- The model is instructed to return "UNKNOWN" when it cannot confidently
  identify a real company, to avoid hallucination.
- Results are cached (descriptions_cache.json) so runs are resumable and cheap.
- Prioritizes recognizable companies first (Fortune > has-recruiters > larger).

Usage:
  python3 enrich_descriptions.py --max-batches 3        # sample/test
  python3 enrich_descriptions.py                        # full pass
  python3 enrich_descriptions.py --apply                # write into master
Run with the venv that has openai installed (JobXplore/venv).
"""

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MASTER = SCRIPT_DIR / "MASTER_companies.csv"
CACHE = SCRIPT_DIR / "descriptions_cache.json"
MODEL = "gpt-4o-mini"
BATCH = 20
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

SYSTEM = (
    "You label real companies with a short factual description. For each company "
    "you are given its name plus context (industry, HQ, website, LinkedIn). Write "
    "ONE concise factual sentence (max 25 words) describing what the company does, "
    "grounded only in widely-known facts consistent with the provided context. "
    "If you are NOT confident the company is real and identifiable, output exactly "
    "\"UNKNOWN\". Never invent facts, funding, or products. Return a JSON object "
    "mapping each id (string) to its description or \"UNKNOWN\"."
)


def co_key(name):
    s = re.sub(r"\(.*?\)", " ", (name or "").lower()).replace("&", " and ")
    s = re.sub(r"[.,/()'\-]", " ", s)
    legal = {"inc", "llc", "ltd", "corp", "corporation", "co", "the", "limited",
             "plc", "group", "holdings", "company"}
    return " ".join(t for t in s.split() if t not in legal)


def load_cache():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def save_cache(c):
    CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=0), encoding="utf-8")


def linkedin_slug(url):
    m = re.search(r"/company/([^/?]+)", url or "")
    return m.group(1) if m else ""


def context_line(r):
    parts = [f"name: {r['Company']}"]
    if r.get("Industry"):
        parts.append(f"industry: {r['Industry']}")
    if r.get("Sub-Industry"):
        parts.append(f"sub: {r['Sub-Industry'][:60]}")
    if r.get("Headquarters"):
        parts.append(f"hq: {r['Headquarters']}")
    if r.get("Website"):
        parts.append(f"web: {r['Website']}")
    slug = linkedin_slug(r.get("LinkedIn URL", ""))
    if slug:
        parts.append(f"linkedin: {slug}")
    if r.get("Keywords (Primary)"):
        parts.append(f"keywords: {r['Keywords (Primary)']}")
    return "; ".join(parts)


def priority(r):
    score = 0
    if r.get("Fortune"):
        score += 100
    if r.get("Recruiter Counts"):
        score += 50
    try:
        score += min(40, int(re.sub(r"[^\d]", "", r.get("Total Employees") or "0") or 0) // 1000)
    except ValueError:
        pass
    return -score  # ascending sort => highest score first


def call_openai(client, batch):
    prompt = "Companies:\n" + "\n".join(f"{i+1}. {context_line(r)}" for i, r in enumerate(batch))
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-batches", type=int, default=0, help="0 = all")
    ap.add_argument("--apply", action="store_true", help="write descriptions into master")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(MASTER, encoding="utf-8")))
    cache = load_cache()

    # Fill known-from-cache first; collect those still needing generation.
    todo = []
    for r in rows:
        k = co_key(r["Company"])
        if (r.get("Description") or "").strip():
            continue
        if k in cache:
            continue
        todo.append(r)
    todo.sort(key=priority)

    if args.max_batches:
        todo = todo[: args.max_batches * BATCH]

    try:
        from openai import OpenAI
        client = OpenAI()
    except Exception as e:
        print(f"OpenAI unavailable: {e}")
        return

    n_batches = (len(todo) + BATCH - 1) // BATCH
    print(f"Generating descriptions for {len(todo)} companies in {n_batches} batches...")
    got = 0
    for bi in range(n_batches):
        batch = todo[bi * BATCH:(bi + 1) * BATCH]
        try:
            result = call_openai(client, batch)
        except Exception as e:
            print(f"  batch {bi+1} error: {e}; retrying once")
            time.sleep(5)
            try:
                result = call_openai(client, batch)
            except Exception as e2:
                print(f"  batch {bi+1} failed: {e2}")
                continue
        for i, r in enumerate(batch):
            desc = (result.get(str(i + 1)) or "").strip()
            cache[co_key(r["Company"])] = desc
            if desc and desc.upper() != "UNKNOWN":
                got += 1
        if (bi + 1) % 10 == 0 or bi + 1 == n_batches:
            save_cache(cache)
            print(f"  {bi+1}/{n_batches} batches done; {got} described so far")
    save_cache(cache)
    print(f"Done. {got} new descriptions ({sum(1 for v in cache.values() if v and v.upper()!='UNKNOWN')} total non-UNKNOWN in cache).")

    if args.apply:
        applied = 0
        for r in rows:
            if (r.get("Description") or "").strip():
                continue
            v = cache.get(co_key(r["Company"]), "")
            if v and v.upper() != "UNKNOWN":
                r["Description"] = v
                applied += 1
        cols = list(rows[0].keys())
        with open(MASTER, "w", newline="", encoding="utf-8") as h:
            w = csv.DictWriter(h, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"Applied {applied} descriptions into {MASTER.name}.")


if __name__ == "__main__":
    main()
