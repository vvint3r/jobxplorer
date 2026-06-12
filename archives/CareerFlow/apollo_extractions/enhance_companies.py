#!/usr/bin/env python3
"""Enhance MASTER_companies.csv into an app-ready company index.

Steps
-----
1. Exclude confirmed foreign-HQ companies (US-only index). A removed-foreign
   report is written for whitelist review.
2. Rename: Location->Headquarters, # Employees->Total Employees,
   Keywords->Keywords (Descriptors). Drop Source.
3. Clean Apollo "+N" chip artifacts from Industry/Keywords.
4. Normalize Industry to a canonical sector; derive Sub-Industry (comma-sep
   granular tags). Fortune/Top-1000 sector data used where a name matches.
5. New columns: Keywords (Primary), Description, US Market, Fortune, Ownership,
   Recruiter Email Status, Recruiter Counts.

Reads reference/fortune1000_2023.csv and joins MASTER_recruiters.csv +
archived Apollo account exports (for Description). No live Apollo calls.
"""

import csv
import glob
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

# Rebuild from the clean deduped base (raw fields + Source), not the enhanced file.
SOURCE = SCRIPT_DIR / "MASTER_companies.pre_enhance.csv"
RECRUITERS = SCRIPT_DIR / "MASTER_recruiters.csv"
FORTUNE = SCRIPT_DIR / "reference" / "fortune1000_2023.csv"
ARCHIVE_EXPORTS = SCRIPT_DIR / "_archive_consolidated" / "apollo_indexes" / "Companies - Enterprise"
OUT = SCRIPT_DIR / "MASTER_companies.csv"
REMOVED_REPORT = SCRIPT_DIR / "removed_foreign_companies.csv"
REMOVED_NONTECH = SCRIPT_DIR / "removed_nontech_companies.csv"

OUT_COLS = ["Company", "Also Known As", "LinkedIn URL", "Website", "Headquarters",
            "Total Employees", "Industry", "Sub-Industry", "Keywords (Descriptors)",
            "Keywords (Primary)", "Description", "US Market", "Fortune", "Ownership",
            "Recruiter Email Status", "Recruiter Counts"]

# Tech signal: keep companies whose raw industry/keywords match these (others are
# dropped unless Fortune 1000). Word-boundary matched.
TECH_KEYWORDS = [
    "software", "saas", "information technology", "it service", "it consulting",
    "internet", "technology", "tech ", "semiconductor", "hardware", "electronics",
    "cyber", "computer", "data ", "artificial intelligence", "machine learning",
    "cloud", "telecommunication", "telecom", "developer", "devops", "fintech",
    "biotech", "edtech", "e-commerce", "ecommerce", "digital", "platform", "app ",
    "mobile", "analytics", "automation", "robotics", "blockchain", "web ",
    "information services", "network", "database", "ai ",
]

US_STATES = {'alabama', 'alaska', 'arizona', 'arkansas', 'california', 'colorado',
             'connecticut', 'delaware', 'florida', 'georgia', 'hawaii', 'idaho',
             'illinois', 'indiana', 'iowa', 'kansas', 'kentucky', 'louisiana', 'maine',
             'maryland', 'massachusetts', 'michigan', 'minnesota', 'mississippi',
             'missouri', 'montana', 'nebraska', 'nevada', 'new hampshire', 'new jersey',
             'new mexico', 'new york', 'north carolina', 'north dakota', 'ohio',
             'oklahoma', 'oregon', 'pennsylvania', 'rhode island', 'south carolina',
             'south dakota', 'tennessee', 'texas', 'utah', 'vermont', 'virginia',
             'washington', 'west virginia', 'wisconsin', 'wyoming', 'district of columbia'}

FOREIGN = {'china', 'taiwan', 'south korea', 'korea', 'japan', 'india', 'germany',
           'france', 'united kingdom', 'uk', 'england', 'netherlands', 'switzerland',
           'sweden', 'canada', 'australia', 'israel', 'singapore', 'hong kong', 'spain',
           'italy', 'ireland', 'finland', 'denmark', 'norway', 'brazil', 'mexico',
           'russia', 'south africa', 'saudi arabia', 'united arab emirates', 'uae',
           'belgium', 'austria', 'poland', 'luxembourg', 'thailand', 'indonesia',
           'malaysia', 'philippines', 'vietnam', 'turkey', 'argentina', 'chile',
           'colombia', 'new zealand', 'portugal', 'greece', 'czech republic', 'romania',
           'hungary', 'qatar', 'kuwait', 'nigeria', 'egypt', 'bermuda', 'cayman islands',
           'estonia', 'lithuania', 'ukraine', 'pakistan', 'bangladesh'}

# Canonical Industry sectors -> ordered match keywords (first hit wins).
SECTOR_RULES = [
    ("Cybersecurity", ["cyber", "network security", "information security", "infosec"]),
    ("Semiconductors", ["semiconductor", "chips", "microchip"]),
    ("Financial Services", ["financ", "fintech", "banking", "bank", "insurance", "investment",
                            "capital market", "payments", "venture capital", "private equity",
                            "accounting", "wealth"]),
    ("Healthcare & Life Sciences", ["health", "hospital", "medical", "biotech", "pharma",
                                    "life science", "wellness", "clinical", "genomic", "therapeutics"]),
    ("Telecommunications", ["telecom", "wireless", "broadband", "communications equipment"]),
    ("Hardware & Electronics", ["hardware", "electronics", "consumer electronics", "computer hardware",
                                "devices", "iot", "robotics"]),
    ("Media & Entertainment", ["media", "entertainment", "gaming", "video game", "music",
                               "publishing", "advertis", "marketing", "broadcast", "film"]),
    ("Education", ["education", "edtech", "e-learning", "university", "school", "training",
                   "academic"]),
    ("Energy & Utilities", ["energy", "oil", "gas", "renewable", "solar", "utilit", "power",
                            "petroleum", "mining"]),
    ("Manufacturing & Industrial", ["manufactur", "industrial", "machinery", "automotive",
                                    "aerospace", "defense", "chemical", "materials", "construction equipment"]),
    ("Retail & Consumer", ["retail", "consumer goods", "apparel", "food", "beverage",
                           "ecommerce", "e-commerce", "cpg", "fashion", "restaurant"]),
    ("Real Estate & Construction", ["real estate", "construction", "property", "proptech",
                                    "architecture"]),
    ("Transportation & Logistics", ["logistics", "transportation", "shipping", "supply chain",
                                    "freight", "airline", "automotive"]),
    ("Professional Services", ["staffing", "recruit", "human resources", "consulting",
                               "research", "legal", "outsourcing", "professional services"]),
    ("Government & Nonprofit", ["government", "nonprofit", "non-profit", "public sector",
                                "ngo"]),
    ("Internet", ["internet", "online", "web ", "marketplace", "social media", "search engine",
                  "saas platform", "cloud platform"]),
    ("Computer Software", ["software", "saas", "application", "developer tools", "database",
                           "analytics", "artificial intelligence", "machine learning", "data "]),
    ("Information Technology & Services", ["information technology", "it service", "it consulting",
                                           "tech", "technology", "systems integrat", "managed service",
                                           "cloud", "data center"]),
]


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def co_key(name):
    s = norm(name).replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[.,/()'\-]", " ", s)
    legal = {"inc", "llc", "ltd", "corp", "corporation", "co", "the", "limited",
             "plc", "group", "holdings", "company"}
    return " ".join(t for t in s.split() if t not in legal)


def strip_chip_counts(value):
    """Remove Apollo '+N' collapsed-chip tokens; return cleaned ';'-joined tags."""
    if not value:
        return []
    out = []
    for part in value.split(";"):
        p = part.strip()
        if not p or re.fullmatch(r"\+\d+", p):
            continue
        out.append(p)
    return out


def title_tag(t):
    # Preserve known acronyms, else title-case.
    if t.isupper() and len(t) <= 5:
        return t
    return " ".join(w if w.isupper() else w.capitalize() for w in t.split())


def last_segment_country(loc):
    seg = [s.strip() for s in norm(loc).split(",")]
    return seg[-1] if seg else ""


def is_us(loc):
    l = norm(loc)
    if not l:
        return None  # unknown
    if "united states" in l or l.endswith(", usa") or l.endswith(", us"):
        return True
    for seg in (s.strip() for s in l.split(",")):
        if seg in US_STATES:
            return True
    if last_segment_country(loc) in FOREIGN:
        return False
    return None  # ambiguous (e.g., corrupted "Company, Inc")


# Authoritative override for well-known companies (diversified mega-caps that
# any tag heuristic gets wrong). Keys are co_key() normalized names.
CURATED = {
    "apple": "Hardware & Electronics", "meta": "Internet", "facebook": "Internet",
    "google": "Internet", "alphabet": "Internet", "microsoft": "Computer Software",
    "amazon": "Internet", "netflix": "Media & Entertainment", "nvidia": "Semiconductors",
    "intel": "Semiconductors", "amd": "Semiconductors", "advanced micro devices": "Semiconductors",
    "tesla": "Manufacturing & Industrial", "oracle": "Computer Software",
    "salesforce": "Computer Software", "adobe": "Computer Software",
    "ibm": "Information Technology & Services", "cisco": "Hardware & Electronics",
    "qualcomm": "Semiconductors", "paypal": "Financial Services", "stripe": "Financial Services",
    "uber": "Internet", "airbnb": "Internet", "lyft": "Internet", "snap": "Internet",
    "snapchat": "Internet", "twitter": "Internet", "linkedin": "Internet",
    "dell": "Hardware & Electronics", "dell technologies": "Hardware & Electronics",
    "hp": "Hardware & Electronics", "hewlett packard": "Hardware & Electronics",
    "broadcom": "Semiconductors", "texas instruments": "Semiconductors", "micron": "Semiconductors",
    "servicenow": "Computer Software", "workday": "Computer Software", "snowflake": "Computer Software",
    "datadog": "Computer Software", "databricks": "Computer Software", "palantir": "Computer Software",
    "zoom": "Computer Software", "dropbox": "Computer Software", "block": "Financial Services",
    "coinbase": "Financial Services", "robinhood": "Financial Services", "intuit": "Computer Software",
    "vmware": "Computer Software", "sap": "Computer Software", "atlassian": "Computer Software",
}

# Fortune Sector -> canonical, for NON-tech sectors only (Fortune lumps all tech
# as "Technology", which is too coarse, so those fall through to the heuristic).
FORTUNE_SECTOR_CANON = {
    "Financials": "Financial Services", "Energy": "Energy & Utilities",
    "Health Care": "Healthcare & Life Sciences", "Retailing": "Retail & Consumer",
    "Food & Drug Stores": "Retail & Consumer", "Food, Beverages & Tobacco": "Retail & Consumer",
    "Household Products": "Retail & Consumer", "Apparel": "Retail & Consumer",
    "Hotels, Restaurants & Leisure": "Retail & Consumer", "Wholesalers": "Retail & Consumer",
    "Business Services": "Professional Services", "Industrials": "Manufacturing & Industrial",
    "Materials": "Manufacturing & Industrial", "Chemicals": "Manufacturing & Industrial",
    "Aerospace & Defense": "Manufacturing & Industrial", "Motor Vehicles & Parts": "Manufacturing & Industrial",
    "Engineering & Construction": "Real Estate & Construction",
    "Transportation": "Transportation & Logistics", "Media": "Media & Entertainment",
    "Telecommunications": "Telecommunications",
}


def classify_industry(tags_lower):
    """Classify by the first industry tag that matches a sector rule
    (word-boundary match)."""
    for t in tags_lower:
        for sector, kws in SECTOR_RULES:
            if any(re.search(r"\b" + re.escape(kw), t) for kw in kws):
                return sector
    return ""


# Map our company names to Fortune's (aliases for renamed/holding companies).
FORTUNE_ALIAS = {"meta": "meta platforms", "facebook": "meta platforms",
                 "google": "alphabet"}


def load_fortune():
    rank_by_name = {}
    sector_by_name = {}
    with open(FORTUNE, encoding="utf-8", errors="ignore") as h:
        for row in csv.DictReader(h):
            k = co_key(row.get("Company", ""))
            if not k:
                continue
            try:
                rank = int(float(row.get("Rank", "0")))
            except ValueError:
                continue
            sec = (row.get("Sector", ""), row.get("Industry", ""))
            for key in (k, k.replace(" ", "")):       # also space-insensitive
                rank_by_name.setdefault(key, rank)
                sector_by_name.setdefault(key, sec)
    return rank_by_name, sector_by_name


def fortune_lookup(k, table):
    return (table.get(k) or table.get(k.replace(" ", ""))
            or table.get(FORTUNE_ALIAS.get(k, ""), None))


def fortune_tier(rank):
    if rank <= 100:
        return "100"
    if rank <= 500:
        return "500"
    return "1000"


def load_recruiter_stats():
    rec_count = defaultdict(int)
    email_count = defaultdict(int)
    NULLS = {"", "n/a", "na", "no email", "none", "null", "-", "--"}
    with open(RECRUITERS, encoding="utf-8") as h:
        for r in csv.DictReader(h):
            k = co_key(r.get("Company", ""))
            if not k:
                continue
            rec_count[k] += 1
            em = (r.get("Email") or "").strip().lower()
            if em not in NULLS and "@" in em:
                email_count[k] += 1
    return rec_count, email_count


def load_archive_meta():
    """From archived Apollo account exports: description, founded year, funding flag."""
    desc, founded, funded = {}, {}, {}
    for f in sorted(glob.glob(str(ARCHIVE_EXPORTS / "*.csv"))):
        with open(f, encoding="utf-8", errors="ignore") as h:
            for row in csv.DictReader(h):
                k = co_key(row.get("Company", ""))
                if not k:
                    continue
                d = (row.get("Short Description") or row.get("SEO Description") or "").strip()
                if d and k not in desc:
                    desc[k] = d
                fy = re.sub(r"[^\d]", "", row.get("Founded Year", "") or "")
                if fy and k not in founded:
                    founded[k] = int(fy)
                tf = (row.get("Total Funding") or row.get("Latest Funding Amount") or "").strip()
                if tf and tf not in ("0", "$0") and k not in funded:
                    funded[k] = True
    return desc, founded, funded


def has_ticker(kw_descriptors):
    return any(t.lower().startswith("ticker:") for t in kw_descriptors)


_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2600-\u26FF\u2700-\u27BF]"
)


def clean_text(s):
    """Standardize a text field: strip control chars/newlines, smart quotes,
    emoji and symbols (R, TM, deg), transliterate accents to ASCII, collapse
    whitespace, and trim surrounding quotes."""
    if not s:
        return ""
    s = s.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = _EMOJI.sub("", s)
    # Strip trademark/symbol marks explicitly (NFKD would turn TM into "TM").
    s = re.sub(r"[\u00ae\u2122\u00b0\u00a9\u2120\u2117\u2105\u2106]", "", s)
    # Transliterate to closest ASCII (Schrodinger, etc.); drop remaining non-ascii.
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = "".join(ch for ch in s if ord(ch) >= 32)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip('"').strip("'").strip()
    return re.sub(r"\s+", " ", s).strip()


_JUNK_NAMES = {"inc", "llc", "ltd", "corp", "co", "the", "unnamed", "n/a", "na",
               "none", "null", "company", "group", "test", "tbd", "unknown"}

# Trailing comma-separated legal-entity suffixes to drop from DISPLAY names so
# they no longer contain commas (which force CSV quoting and look inconsistent).
_LEGAL_SUFFIX = re.compile(
    r",\s*(incorporated|inc|llc|l\.l\.c\.|ltd|limited|corp|corporation|co|company|"
    r"plc|lp|llp|l\.p\.|pc|pbc|gmbh|ag|s\.a\.|sa|n\.v\.|nv|b\.v\.|bv|pllc|p\.c\.)\.?\s*$",
    re.IGNORECASE,
)


def clean_name(s):
    name = clean_text(s)
    name = name.replace('"', "").replace("\u201c", "").replace("\u201d", "")
    # Strip wrapping parens/brackets and dangling separators.
    name = re.sub(r"^[\(\[\{]+|[\)\]\}]+$", "", name).strip()
    name = re.sub(r"^[\s\-,;:|/]+|[\s\-,;:|/]+$", "", name).strip()
    # Drop trailing legal-entity suffix(es): "11 Main, Inc." -> "11 Main".
    prev = None
    while prev != name:
        prev = name
        name = _LEGAL_SUFFIX.sub("", name).strip()
    return re.sub(r"[\s,]+$", "", name).strip()


def clean_description(s):
    """One-line, ASCII, URL/bullet-free description; trimmed to first sentence(s)."""
    s = clean_text(s)                       # strips emoji, newlines->space, non-ascii
    s = re.sub(r"https?://\S+|www\.\S+", "", s)
    s = re.sub(r"\b(join the team|join the community|learn more|follow us)\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip(" .;:-|")
    if len(s) > 230:                        # keep ~first sentence(s)
        cut = s[:230]
        s = cut.rsplit(". ", 1)[0] if ". " in cut else cut
    return s.strip()


def valid_company_name(name):
    """Reject junk: needs >=2 chars, at least one letter, and not a bare
    legal/placeholder token."""
    if len(name) < 2 or not re.search(r"[A-Za-z]", name):
        return False
    if co_key(name) in _JUNK_NAMES or not co_key(name):
        return False
    return True


def is_tech_signal(industry, keywords):
    blob = (" " + (industry or "") + " ; " + (keywords or "") + " ").lower()
    for kw in TECH_KEYWORDS:
        if re.search(r"(^|[^a-z])" + re.escape(kw.strip()) + r"([^a-z]|$)", blob):
            return True
    return False


def variant_key(name):
    """Space- and punctuation-insensitive key to merge name variants like
    'Exxon Mobil' / 'ExxonMobil'."""
    return co_key(name).replace(" ", "")


def load_llm_descriptions():
    cache = SCRIPT_DIR / "descriptions_cache.json"
    if not cache.exists():
        return {}
    import json
    return json.loads(cache.read_text(encoding="utf-8"))


def build_enhanced(r, aka, refs):
    rank_by_name, sector_by_name, rec_count, email_count, descriptions, founded_year, funded, llm_desc = refs
    name = r["Company"]
    k = co_key(name)
    loc = r.get("Location") or ""
    us = is_us(loc)
    ind_tags = strip_chip_counts(r.get("Industry"))
    kw_tags = strip_chip_counts(r.get("Keywords"))
    ind_lower = [t.lower() for t in ind_tags]

    f_sec = fortune_lookup(k, sector_by_name)
    fortune_canon = FORTUNE_SECTOR_CANON.get(f_sec[0]) if f_sec else None
    primary_industry = (CURATED.get(k) or fortune_canon or classify_industry(ind_lower)
                        or (title_tag(ind_tags[0]) if ind_tags else ""))
    sub = []
    for t in ind_tags:
        tt = title_tag(t)
        if tt and tt.lower() != (primary_industry or "").lower() and tt not in sub:
            sub.append(tt)
    if f_sec and f_sec[1] and f_sec[1] not in sub:
        sub.insert(0, f_sec[1])

    kw_clean = [t for t in kw_tags if not t.lower().startswith("ticker:")]
    descriptors = "; ".join(kw_clean)
    primary_kw = "; ".join(kw_clean[:3])

    f_rank = fortune_lookup(k, rank_by_name)
    fortune = fortune_tier(f_rank) if f_rank else ""
    ticker = has_ticker(kw_tags)
    try:
        emp = int(re.sub(r"[^\d]", "", r.get("# Employees") or "") or "0")
    except ValueError:
        emp = 0
    is_startup = (founded_year.get(k, 0) >= 2015 and funded.get(k) and emp < 1000)
    ownership = "Public" if (ticker or fortune) else ("Startup" if is_startup else "Private")

    us_market = "Headquarters" if us is True else ("Yes" if us is None else "")
    # Description: prefer the clean LLM one-liner; fall back to cleaned archived text.
    llm = llm_desc.get(k, "")
    if llm and llm.upper() != "UNKNOWN":
        description = clean_description(llm)
    else:
        description = clean_description(descriptions.get(k, ""))

    rc = rec_count.get(k, 0)
    ec = email_count.get(k, 0)
    if rc == 0:
        rstatus, rcounts = "", ""
    elif ec > 0:
        rstatus, rcounts = "Emails available", f"{rc} recruiters / {ec} emails"
    else:
        rstatus, rcounts = "Recruiters (no email)", f"{rc} recruiters / 0 emails"

    return {
        "Company": name, "Also Known As": aka,
        "LinkedIn URL": r.get("LinkedIn URL", ""), "Website": r.get("Website", ""),
        "Headquarters": loc, "Total Employees": r.get("# Employees", ""),
        "Industry": primary_industry, "Sub-Industry": ", ".join(sub),
        "Keywords (Descriptors)": descriptors, "Keywords (Primary)": primary_kw,
        "Description": description, "US Market": us_market, "Fortune": fortune,
        "Ownership": ownership, "Recruiter Email Status": rstatus, "Recruiter Counts": rcounts,
    }


RAW_FIELDS = ("LinkedIn URL", "Website", "Location", "# Employees", "Industry", "Keywords")


def main():
    rank_by_name, sector_by_name = load_fortune()
    rec_count, email_count = load_recruiter_stats()
    descriptions, founded_year, funded = load_archive_meta()
    llm_desc = load_llm_descriptions()
    refs = (rank_by_name, sector_by_name, rec_count, email_count, descriptions,
            founded_year, funded, llm_desc)

    raw = list(csv.DictReader(open(SOURCE, encoding="utf-8")))

    # 1. Clean every text field; drop rows whose name cleans to empty.
    cleaned = []
    for r in raw:
        name = clean_name(r.get("Company", ""))
        if not valid_company_name(name):
            continue
        cleaned.append({
            "Company": name,
            "LinkedIn URL": clean_text(r.get("LinkedIn URL", "")),
            "Website": clean_text(r.get("Website", "")),
            "Location": clean_text(r.get("Location", "")),
            "# Employees": clean_text(r.get("# Employees", "")),
            "Industry": clean_text(r.get("Industry", "")),
            "Keywords": clean_text(r.get("Keywords", "")),
            "Source": r.get("Source", ""),
        })

    # 2. Normalize name variants FIRST (merge ExxonMobil/Exxon Mobil -> 1 canonical
    #    + AKA), so name-only rows gain industry data from their tech twin before
    #    the tech filter runs.
    groups = defaultdict(list)
    for r in cleaned:
        groups[variant_key(r["Company"])].append(r)

    def has_li(x):
        return 1 if (x.get("LinkedIn URL") or "").strip() else 0

    def fcount(x):
        return sum(1 for f in RAW_FIELDS if (x.get(f) or "").strip())

    merged = []
    for grp in groups.values():
        grp.sort(key=lambda x: (-has_li(x), -fcount(x), len(x["Company"])))
        canon = dict(grp[0])
        for o in grp[1:]:
            for f in RAW_FIELDS:
                if not (canon.get(f) or "").strip() and (o.get(f) or "").strip():
                    canon[f] = o[f]
        aka = sorted({o["Company"] for o in grp if o["Company"] != canon["Company"]})
        merged.append((canon, "; ".join(aka)))

    # 3. Lean + US filter: keep US companies that are tech OR Fortune 1000.
    kept, rem_foreign, rem_nontech = [], [], []
    for canon, aka in merged:
        k = co_key(canon["Company"])
        is_fortune = fortune_lookup(k, rank_by_name) is not None
        if is_us(canon["Location"]) is False:
            rem_foreign.append(canon)
        elif not (is_tech_signal(canon["Industry"], canon["Keywords"]) or is_fortune):
            rem_nontech.append(canon)
        else:
            kept.append((canon, aka))

    # 4. Build enhanced rows.
    out = [build_enhanced(r, aka, refs) for r, aka in kept]
    out.sort(key=lambda x: x["Company"].lower())

    with open(OUT, "w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=OUT_COLS)
        w.writeheader()
        w.writerows(out)

    for path, rowset in ((REMOVED_REPORT, rem_foreign), (REMOVED_NONTECH, rem_nontech)):
        with open(path, "w", newline="", encoding="utf-8") as h:
            w = csv.writer(h)
            w.writerow(["Company", "Location", "Industry", "Source"])
            for r in sorted(rowset, key=lambda x: x.get("Company", "")):
                w.writerow([r.get("Company", ""), r.get("Location", ""),
                            (r.get("Industry") or "")[:60], r.get("Source", "")])

    # Report
    from collections import Counter
    n = len(out)
    def cov(col):
        c = sum(1 for r in out if (r.get(col) or "").strip())
        return f"{c} ({100*c//n}%)"
    print(f"Cleaned {len(cleaned)} -> {len(merged)} after variant-merge -> kept {n} "
          f"(removed {len(rem_foreign)} foreign, {len(rem_nontech)} non-tech).")
    for c in OUT_COLS:
        print(f"   {c:24} {cov(c)}")
    print("Ownership:", dict(Counter(r["Ownership"] for r in out)))
    print("Fortune:", dict(Counter(r["Fortune"] for r in out if r["Fortune"])))
    print("Top sectors:", dict(Counter(r["Industry"] for r in out if r["Industry"]).most_common(12)))
    aka_n = sum(1 for r in out if r["Also Known As"])
    print(f"rows with Also-Known-As: {aka_n}")
    print(f"Reports -> {REMOVED_REPORT.name}, {REMOVED_NONTECH.name}")


if __name__ == "__main__":
    main()
