"""Permanent record of every business that got a first email, and its PDF report.

The pipeline's merge step can drop already-emailed leads from LEADS_MASTER.csv and their PDFs from
4A_reports.zip when a new town is processed. Then a "yes" from a version-B business (promised the report)
would get a reply without it. So after every run:
- 0_sent_leads.csv gets one row per emailed business (never removed),
- sent_reports/<Report_File> keeps its PDF on Drive (never removed; not downloaded each run, fetched when needed).
"""
import io
import os
import zipfile

import pandas as pd

COLS = ["place_id", "first_sent_at", "email", "name", "city", "search_category", "website", "Template",
        "Report_File", "Attachment_Name", "Email_Subject", "pdf_saved"]
NAME = "0_sent_leads.csv"
PDF_DIR = "sent_reports"


def _read(path):
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()


def run(home, log=print):
    sent = _read(os.path.join(home, "0_sent_log.csv"))
    if sent.empty or "place_id" not in sent.columns:
        return 0
    path = os.path.join(home, NAME)
    have = _read(path)
    known = set(have.get("place_id", pd.Series(dtype=str)))
    first = sent[sent["place_id"] != ""].sort_values("sent_at").drop_duplicates("place_id", keep="first")
    new = first[~first["place_id"].isin(known)]
    m = _read(os.path.join(home, "LEADS_MASTER.csv"))
    m = m.drop_duplicates("place_id", keep="last").set_index("place_id") if "place_id" in m.columns else pd.DataFrame()
    zpath = os.path.join(home, "latest", "4A_reports.zip")
    z = zipfile.ZipFile(zpath) if os.path.exists(zpath) else None
    names = {os.path.basename(n): n for n in z.namelist()} if z else {}
    healed = _heal(home, have, m, z, names, path) if len(have) else 0
    if healed:
        log(f"[archive] {healed} earlier row(s) completed (version / PDF found now)")
    if new.empty:
        return 0
    rows = []
    for _, s in new.iterrows():
        r = m.loc[s["place_id"]] if s["place_id"] in m.index else {}
        get = (lambda c: str(r.get(c, "")) if len(r) else "")
        row = {"place_id": s["place_id"], "first_sent_at": s.get("sent_at", ""), "email": s.get("email", ""),
               "name": get("Clean_Name") or s.get("name", ""), "city": get("city"),
               "search_category": get("search_category"), "website": get("website") or get("Website"),
               "Template": get("Template"), "Report_File": get("Report_File"),
               "Attachment_Name": get("Attachment_Name"), "Email_Subject": get("Email_Subject") or s.get("subject", ""),
               "pdf_saved": "no"}
        f = row["Report_File"]
        if f and f in names:
            os.makedirs(os.path.join(home, PDF_DIR), exist_ok=True)
            with open(os.path.join(home, PDF_DIR, f), "wb") as out:
                out.write(z.read(names[f]))
            row["pdf_saved"] = "yes"
        rows.append(row)
    pd.DataFrame(rows)[COLS].to_csv(path, mode="a", header=not os.path.exists(path), index=False)
    lost = sum(r["pdf_saved"] == "no" for r in rows)
    log(f"[archive] {len(rows)} emailed business(es) kept for good" + (f" ({lost} without a PDF on hand)" if lost else ""))
    return len(rows)


def _heal(home, have, m, z, names, path):
    """Rows archived without their version or PDF get them as soon as they are available."""
    n = 0
    for i, row in have.iterrows():
        pid, changed = row["place_id"], False
        if pid in m.index:
            for c in ("Template", "Report_File", "Attachment_Name"):
                v = str(m.loc[pid].get(c, ""))
                if not have.at[i, c] and v:
                    have.at[i, c] = v
                    changed = True
        f = have.at[i, "Report_File"]
        if have.at[i, "pdf_saved"] != "yes" and f and f in names:
            os.makedirs(os.path.join(home, PDF_DIR), exist_ok=True)
            with open(os.path.join(home, PDF_DIR, f), "wb") as out:
                out.write(z.read(names[f]))
            have.at[i, "pdf_saved"] = "yes"
            changed = True
        n += changed
    if n:
        have[COLS].to_csv(path, index=False)
    return n


def lookup(home, place_id):
    """The archived row for a business, or {}."""
    a = _read(os.path.join(home, NAME))
    hit = a[a.get("place_id", pd.Series(dtype=str)) == place_id] if len(a) else a
    return hit.iloc[0].to_dict() if len(hit) else {}


def pdf(home, report_file):
    """PDF bytes from sent_reports/ (fetched from Drive when this run doesn't have it), or None."""
    if not report_file:
        return None
    path = os.path.join(home, PDF_DIR, report_file)
    if not os.path.exists(path) and os.environ.get("FRONTAGE_RCLONE"):
        import subprocess
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.call(["rclone", "copyto", f"gdrive:Frontage/{PDF_DIR}/{report_file}", path, "--quiet"],
                        timeout=120)
    return open(path, "rb").read() if os.path.exists(path) else None
