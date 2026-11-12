"""One-off repair of the permanent archive (0_sent_leads.csv + sent_reports/).

Before 11 Nov 2026 the pipeline dropped already-emailed businesses (and their PDFs) from LEADS_MASTER.csv
and 4A_reports.zip every time a new town was processed. Google Drive still keeps the older versions of
those files for about 30 days, and the carry/ folders keep the PDFs that were set aside. This tool reads
all of that (read-only) and fills the archive: version sent (with / without PDF), report file, town,
business type, and the PDF itself.

    python tools/recover_archive.py DRIVE_DIR WORK_DIR

Needs rclone configured as "gdrive" (uses its token only to read older versions of the user's own files).
"""
import configparser
import glob
import io
import json
import os
import subprocess
import sys
import zipfile

import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import archive  # noqa: E402

API = "https://www.googleapis.com/drive/v3/files"
FIELDS = ["Clean_Name", "city", "search_category", "website", "Website", "Template", "Report_File",
          "Attachment_Name", "Email_Subject"]
B_FROM = "2026-11-11"            # from this day every first email went out without the PDF (version B)


def token():
    subprocess.call(["rclone", "about", "gdrive:"], stdout=subprocess.DEVNULL)      # refreshes the token
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.expanduser("~/.config/rclone/rclone.conf"))
    return json.loads(cp["gdrive"]["token"])["access_token"]


def drive_ids():
    out = subprocess.check_output(["rclone", "lsjson", "gdrive:Frontage", "-R", "--files-only",
                                   "--include", "/LEADS_MASTER.csv", "--include", "/latest/LEADS_MASTER.csv",
                                   "--include", "/latest/4A_reports.zip"])
    return {f["Path"]: f["ID"] for f in json.loads(out)}


def revisions(fid, tok):
    r = requests.get(f"{API}/{fid}/revisions", headers={"Authorization": f"Bearer {tok}"},
                     params={"fields": "revisions(id,modifiedTime,size)", "pageSize": 1000}, timeout=60)
    r.raise_for_status()
    return sorted(r.json().get("revisions", []), key=lambda x: x["modifiedTime"])


def download(fid, rid, tok):
    r = requests.get(f"{API}/{fid}/revisions/{rid}", headers={"Authorization": f"Bearer {tok}"},
                     params={"alt": "media"}, timeout=300)
    r.raise_for_status()
    return r.content


def learn(info, frame):
    """Remember the newest non-empty value of each field per business."""
    if "place_id" not in frame.columns:
        return
    for c in FIELDS:
        if c not in frame.columns:
            continue
        part = frame[(frame[c] != "") & (frame["place_id"] != "")]
        for pid, v in zip(part["place_id"], part[c]):
            info.setdefault(pid, {})[c] = v


def fill(home, info, pdfs, log=print):
    """info: {place_id: {field: value}}, pdfs: {file name: bytes}. Returns counts."""
    archive.run(home, log=lambda m: None)
    path = os.path.join(home, archive.NAME)
    a = pd.read_csv(path, dtype=str, keep_default_na=False)
    os.makedirs(os.path.join(home, archive.PDF_DIR), exist_ok=True)
    n = {"rows": len(a), "details_filled": 0, "pdf_saved_now": 0, "version_b": 0, "version_b_with_pdf": 0}
    for i, row in a.iterrows():
        got = info.get(row["place_id"], {})
        before = row.to_dict()
        for col, src in (("name", "Clean_Name"), ("city", "city"), ("search_category", "search_category"),
                         ("Template", "Template"), ("Report_File", "Report_File"),
                         ("Attachment_Name", "Attachment_Name"), ("Email_Subject", "Email_Subject")):
            if not a.at[i, col] and got.get(src):
                a.at[i, col] = got[src]
        if not a.at[i, "website"]:
            a.at[i, "website"] = got.get("website") or got.get("Website") or ""
        if not a.at[i, "Template"]:                    # the sender's mark was lost with the row: go by the date
            a.at[i, "Template"] = "outbox_v1_nopdf" if a.at[i, "first_sent_at"][:10] >= B_FROM else "outbox_v1"
        f = a.at[i, "Report_File"]
        if a.at[i, "pdf_saved"] != "yes" and f and f in pdfs:
            with open(os.path.join(home, archive.PDF_DIR, f), "wb") as out:
                out.write(pdfs[f])
            a.at[i, "pdf_saved"] = "yes"
            n["pdf_saved_now"] += 1
        n["details_filled"] += a.loc[i].to_dict() != before
        if a.at[i, "Template"] == "outbox_v1_nopdf":
            n["version_b"] += 1
            n["version_b_with_pdf"] += a.at[i, "pdf_saved"] == "yes"
    a.to_csv(path, index=False)
    log(f"[recover] archive rows: {n['rows']}   details filled: {n['details_filled']}   PDFs saved now: "
        f"{n['pdf_saved_now']}   sent without PDF (version B): {n['version_b']}, of them with the report kept: "
        f"{n['version_b_with_pdf']}")
    return n


def main(home, work):
    os.makedirs(work, exist_ok=True)
    tok = token()
    ids = drive_ids()
    info, pdfs = {}, {}
    # PDFs and rows the pipeline set aside between towns
    subprocess.call(["rclone", "copy", "gdrive:Frontage/carry", os.path.join(work, "carry"), "--quiet",
                     "--transfers", "16"])
    for p in sorted(glob.glob(os.path.join(work, "carry", "*", "carry_master.csv"))):
        try:
            learn(info, pd.read_csv(p, dtype=str, keep_default_na=False))
        except Exception:
            pass
    for p in glob.glob(os.path.join(work, "carry", "*", "pdfs", "*.pdf")):
        pdfs[os.path.basename(p)] = open(p, "rb").read()
    print(f"[recover] set-aside folders: {len(pdfs)} PDFs")
    # older versions kept by Google Drive
    for path, fid in sorted(ids.items()):
        revs = revisions(fid, tok)
        print(f"[recover] {path}: {len(revs)} older versions on Drive")
        for rv in revs:
            try:
                data = download(fid, rv["id"], tok)
            except Exception as e:
                print(f"[recover]   {rv['modifiedTime']}: not readable ({type(e).__name__})")
                continue
            if path.endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        for nme in z.namelist():
                            if nme.lower().endswith(".pdf"):
                                pdfs.setdefault(os.path.basename(nme), z.read(nme))
                except zipfile.BadZipFile:
                    pass
            else:
                try:
                    learn(info, pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False))
                except Exception:
                    pass
    print(f"[recover] businesses with details found: {len(info)}   PDFs found in total: {len(pdfs)}")
    fill(home, info, pdfs)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
