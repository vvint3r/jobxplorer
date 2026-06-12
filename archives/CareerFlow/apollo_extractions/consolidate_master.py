#!/usr/bin/env python3
"""Consolidate ALL historically collected company and recruiter data into a
single deduped master CSV for each.

Sources
-------
Historical (archived under _archive_consolidated/, mirroring original layout):
  * Scraper output (with/without header)
  * Apollo native exports (accounts 32-col, contacts 59-col)
Incoming third-party lists (incoming/):
  * companiesmarketcap.com - Largest tech companies by market cap.csv
  * company index - biz index.csv            (name-only)
  * Top 1000 technology companies.csv
  * networking index _ recruiters + colleagues - recruiters.csv

Dedupe
------
Primary key = normalized LinkedIn URL. A secondary normalized-NAME index lets
name-only rows (the market-cap / top-1000 / biz-index lists, which have no
LinkedIn) match LinkedIn-keyed Apollo records (e.g. "Apple Inc." -> "Apple").
Colliding rows are merged field-by-field (empty cells filled from the other;
recruiters prefer a row that has an email). Historical sources are processed
first and incoming lists last, so new files only fill gaps or add net-new rows.

Excludes apollo_indexes/Listing_of_Active_Businesses.csv (LA city business
registry, not Apollo data).
"""

import csv
import glob
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
HIST = SCRIPT_DIR / "_archive_consolidated"
INC = SCRIPT_DIR / "_archive_consolidated" / "incoming"
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

COMPANY_COLS = ["Company", "LinkedIn URL", "Website", "Location",
                "# Employees", "Industry", "Keywords", "Source"]
RECRUITER_COLS = ["Name", "Title", "Company", "Email", "LinkedIn URL",
                  "Location", "# Employees", "Industry", "Keywords", "Source"]

COMPANY_MASTER = SCRIPT_DIR / "MASTER_companies.csv"
RECRUITER_MASTER = SCRIPT_DIR / "MASTER_recruiters.csv"

_LEGAL = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
          "co", "plc", "sa", "gmbh", "ag", "nv", "bv", "srl", "spa", "the"}


def norm_linkedin(url):
    u = (url or "").strip().lower()
    if not u or u == "n/a":
        return ""
    if u.startswith("/"):                       # relative "/in/..." or "/company/..."
        u = "linkedin.com" + u
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.split("?")[0].rstrip("/")
    return u


def norm_name(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def strong_company_norm(name):
    s = norm_name(name).replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)          # drop parentheticals e.g. "Alphabet (Google)"
    s = re.sub(r"[.,/()']", " ", s)
    toks = [t for t in s.split() if t and t not in _LEGAL]
    return " ".join(toks).strip()


def join_loc(*parts):
    vals = [p.strip() for p in parts if p and p.strip() and p.strip().lower() != "n/a"]
    return ", ".join(vals)


def read_rows(path):
    with open(path, encoding="utf-8", errors="ignore", newline="") as h:
        yield from csv.reader(h)


def is_header(row, first_cell_values):
    return bool(row) and row[0].strip() in first_cell_values


# ---------------- Company mappers ----------------

def company_from_scraper(row):
    g = lambda i: row[i].strip() if i < len(row) else ""
    return {"Company": g(0), "LinkedIn URL": g(1), "Website": "",
            "Location": g(2), "# Employees": g(3), "Industry": g(4), "Keywords": g(5)}


def company_from_export(row):
    g = lambda i: row[i].strip() if i < len(row) else ""
    return {"Company": g(0), "LinkedIn URL": g(8), "Website": g(7),
            "Location": join_loc(g(12), g(13), g(14)),
            "# Employees": g(4), "Industry": g(5), "Keywords": g(17)}


def company_from_marketcap(row):
    # Rank, Name, Symbol, marketcap, price (USD), country
    g = lambda i: row[i].strip() if i < len(row) else ""
    return {"Company": g(1), "LinkedIn URL": "", "Website": "",
            "Location": g(5), "# Employees": "", "Industry": "",
            "Keywords": f"ticker:{g(2)}" if g(2) else ""}


def company_from_top1000(row):
    # Ranking, Company, Market Cap, Stock, Country, Sector, Industry
    g = lambda i: row[i].strip() if i < len(row) else ""
    return {"Company": g(1), "LinkedIn URL": "", "Website": "",
            "Location": g(4), "# Employees": "", "Industry": g(6) or g(5),
            "Keywords": f"ticker:{g(3)}" if g(3) else ""}


def company_from_bizindex(row):
    # Company Name, Preference Score, Total Employees, Industry, Sub-Industry, ...
    g = lambda i: row[i].strip() if i < len(row) else ""
    return {"Company": g(0), "LinkedIn URL": "", "Website": "",
            "Location": "", "# Employees": g(2), "Industry": g(3), "Keywords": g(5)}


# ---------------- Recruiter mappers ----------------

def recruiter_from_scraper(row):
    g = lambda i: row[i].strip() if i < len(row) else ""
    return {"Name": g(0), "Title": g(1), "Company": g(2), "Email": g(3),
            "LinkedIn URL": g(4), "Location": g(5), "# Employees": g(6),
            "Industry": g(7), "Keywords": g(8)}


def recruiter_from_export(row):
    g = lambda i: row[i].strip() if i < len(row) else ""
    return {"Name": (g(0) + " " + g(1)).strip(), "Title": g(2), "Company": g(3),
            "Email": g(5), "LinkedIn URL": g(27), "Location": join_loc(g(32), g(33), g(34)),
            "# Employees": g(24), "Industry": g(25), "Keywords": g(26)}


def recruiter_from_network(row):
    # Recruiter First, Last, Job Title, Email, LinkedIn, Company
    g = lambda i: row[i].strip() if i < len(row) else ""
    return {"Name": (g(0) + " " + g(1)).strip(), "Title": g(2), "Company": g(5),
            "Email": g(3), "LinkedIn URL": g(4), "Location": "",
            "# Employees": "", "Industry": "", "Keywords": ""}


def score(rec, cols):
    return sum(1 for c in cols if (rec.get(c, "") or "").strip() not in ("", "N/A"))


def merge(cur, new, cols, prefer_email):
    out = dict(cur)
    for c in cols:
        if c == "Source":
            continue
        cv = (out.get(c, "") or "").strip()
        nv = (new.get(c, "") or "").strip()
        if cv in ("", "N/A") and nv not in ("", "N/A"):
            out[c] = nv
    if prefer_email:
        if (out.get("Email") or "").strip() in ("", "N/A") and (new.get("Email") or "").strip() not in ("", "N/A"):
            out["Email"] = new["Email"]
    return out


def consolidate(sources, cols, entity, prefer_email=False):
    """entity: 'company' or 'recruiter'. Returns (rows, raw, added_per_source)."""
    best, order, name_index = {}, [], {}
    raw = 0
    added = {}

    def name_key(rec):
        if entity == "company":
            return strong_company_norm(rec.get("Company"))
        nm = strong_company_norm(rec.get("Name"))
        co = strong_company_norm(rec.get("Company"))
        return f"{nm}|{co}" if nm else ""

    for path, label, mapper, header_firsts in sources:
        added.setdefault(label, 0)
        for i, row in enumerate(read_rows(path)):
            if not row or not any((c or "").strip() for c in row):
                continue
            if i == 0 and is_header(row, header_firsts):
                continue
            rec = mapper(row)
            rec["Source"] = label
            if not (rec.get("Company") or rec.get("Name")):
                continue
            raw += 1
            li = norm_linkedin(rec.get("LinkedIn URL"))
            nk = name_key(rec)

            target = None
            if li and li in best:
                target = li
            elif nk and nk in name_index:
                target = name_index[nk]

            if target is None:
                key = li or ("nm:" + nk) or f"row:{len(order)}"
                rec["LinkedIn URL"] = (rec.get("LinkedIn URL") or "")
                if li:
                    rec["LinkedIn URL"] = "https://www." + li if not li.startswith("http") else li
                best[key] = rec
                order.append(key)
                if nk:
                    name_index.setdefault(nk, key)
                added[label] += 1
            else:
                best[target] = merge(best[target], rec, cols, prefer_email)
                if nk:
                    name_index.setdefault(nk, target)
    return [best[k] for k in order], raw, added


def write_master(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def main():
    # ---- Company sources (historical first, incoming last) ----
    company_sources = []
    for p in [HIST / "companies/apollo_records.csv",
              HIST / "companies/apollo_records_companies_1.csv",
              HIST / "companies/apollo_records_companies_2.csv"]:
        if p.exists():
            company_sources.append((str(p), "legacy_scrape", company_from_scraper, {"Company"}))
    for p in sorted(glob.glob(str(HIST / "companies/lists/MajorCompanies/*.csv"))):
        company_sources.append((p, "majorcompanies", company_from_scraper, {"Company"}))
    for p in sorted(glob.glob(str(HIST / "companies/lists/TechCompanies/*.csv"))):
        company_sources.append((p, "techcompanies", company_from_scraper, {"Company"}))
    for p in sorted(glob.glob(str(HIST / "apollo_indexes/Companies - Enterprise/*.csv"))):
        company_sources.append((p, "apollo_export", company_from_export, {"Company"}))
    # incoming
    company_sources += [
        (str(INC / "companiesmarketcap.com - Largest tech companies by market cap.csv"),
         "companiesmarketcap", company_from_marketcap, {"Rank"}),
        (str(INC / "Top 1000 technology companies.csv"),
         "top1000_tech", company_from_top1000, {"Ranking"}),
        (str(INC / "company index - biz index.csv"),
         "biz_index", company_from_bizindex, {"Company Name"}),
    ]

    comp_rows, comp_raw, comp_added = consolidate(company_sources, COMPANY_COLS, "company")
    write_master(COMPANY_MASTER, comp_rows, COMPANY_COLS)

    # ---- Recruiter sources ----
    recruiter_sources = []
    for p in [HIST / "apollo_recruiters/apollo_recruiter_records.csv",
              HIST / "apollo_recruiters/apollo_recruiter_records_2.csv"]:
        if p.exists():
            recruiter_sources.append((str(p), "legacy_scrape", recruiter_from_scraper, {"Name"}))
    for p in sorted(glob.glob(str(HIST / "apollo_recruiters/lists/TechnicalRecruitersTargetOrgs/*.csv"))):
        recruiter_sources.append((p, "target_orgs", recruiter_from_scraper, {"Name"}))
    for p in sorted(glob.glob(str(HIST / "apollo_recruiters/lists/TechnicalRecruitersPublic/*.csv"))):
        recruiter_sources.append((p, "public", recruiter_from_scraper, {"Name"}))
    for p in sorted(glob.glob(str(HIST / "apollo_indexes/Recruiters/*.csv"))):
        recruiter_sources.append((p, "apollo_export", recruiter_from_export, {"First Name"}))
    # incoming
    recruiter_sources.append(
        (str(INC / "networking index _ recruiters + colleagues - recruiters.csv"),
         "network", recruiter_from_network, {"Recruiter First Name"}))

    rec_rows, rec_raw, rec_added = consolidate(recruiter_sources, RECRUITER_COLS, "recruiter", prefer_email=True)
    write_master(RECRUITER_MASTER, rec_rows, RECRUITER_COLS)

    # ---- Report ----
    def src_counts(rows):
        out = {}
        for r in rows:
            out[r["Source"]] = out.get(r["Source"], 0) + 1
        return out

    print("=" * 64)
    print(f"COMPANIES  raw={comp_raw}  unique master={len(comp_rows)}  -> {COMPANY_MASTER.name}")
    print("  net-new rows added per source:")
    for s, n in sorted(comp_added.items(), key=lambda x: -x[1]):
        print(f"     {s:<18} +{n}")
    li = sum(1 for r in comp_rows if norm_linkedin(r["LinkedIn URL"]))
    print(f"  with LinkedIn: {li}/{len(comp_rows)}")

    print("=" * 64)
    print(f"RECRUITERS raw={rec_raw}  unique master={len(rec_rows)}  -> {RECRUITER_MASTER.name}")
    print("  net-new rows added per source:")
    for s, n in sorted(rec_added.items(), key=lambda x: -x[1]):
        print(f"     {s:<18} +{n}")
    em = sum(1 for r in rec_rows if (r.get("Email") or "").strip() not in ("", "N/A"))
    li = sum(1 for r in rec_rows if norm_linkedin(r["LinkedIn URL"]))
    print(f"  with email: {em}/{len(rec_rows)}   with LinkedIn: {li}/{len(rec_rows)}")


if __name__ == "__main__":
    main()
