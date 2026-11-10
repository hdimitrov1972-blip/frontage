"""Writes the first email for approved leads that are ready to send but have no email text yet.

This happens when an address is approved in the weekly check AFTER the pipeline already wrote the emails:
the lead becomes ready, but the sender then fails every day with "no email text".

The text comes from the pipeline notebook itself (the cell that has build_email), so it is exactly the same
email every other business gets — nothing is rewritten here.
"""
import ast
import json
import os

import pandas as pd


def load_writer(nb_path):
    """build_email(row) -> (subject, body) and attachment_name(name), taken from the pipeline notebook."""
    nb = json.load(open(nb_path, encoding="utf-8"))
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        if "def build_email(" not in src:
            continue
        tree = ast.parse(src)
        ns = {"__name__": "frontage_emailtext"}
        for node in tree.body:       # definitions only: nothing in the cell is run, no files are touched
            if not isinstance(node, (ast.FunctionDef, ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom)):
                continue
            try:
                exec(compile(ast.Module(body=[node], type_ignores=[]), nb_path, "exec"), ns)
            except Exception:
                if isinstance(node, ast.FunctionDef):
                    raise
                # Colab-only imports or Colab paths: not needed to write the text
        if "build_email" in ns and "attachment_name" in ns:
            return ns
    raise ValueError("the pipeline notebook has no build_email cell")


def missing_text(m):
    for c in ("Funnel", "Status_Outreach", "Send_Ready", "Email_Approved", "Email_Subject", "Email_Body"):
        if c not in m.columns:
            m[c] = ""
    s = m.astype(object).where(m.notna(), "").astype(str)
    return ((s["Funnel"] == "email") & (s["Status_Outreach"].str.lower() == "pending")
            & s["Send_Ready"].str.lower().isin(["true", "1"]) & s["Email_Approved"].str.lower().isin(["true", "1", "yes"])
            & ((s["Email_Subject"].str.strip() == "") | (s["Email_Body"].str.strip() == "")))


def fill_missing(home, nb_path, log=print):
    """Returns how many emails were written."""
    path = os.path.join(home, "LEADS_MASTER.csv")
    if not os.path.exists(path):
        return 0
    raw = pd.read_csv(path, low_memory=False)          # numbers as numbers, like the pipeline reads it
    need = missing_text(raw.copy())
    if not need.any():
        return 0
    ns = load_writer(nb_path)
    m = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in ("Email_Subject", "Email_Body", "Attachment_Name"):
        if c not in m.columns:
            m[c] = ""
    done = 0
    for idx in raw.index[need]:
        row = raw.loc[idx]
        try:
            subject, body = ns["build_email"](row)
            name = ns["short_name"](ns["txt"](row.get("Clean_Name")) or ns["txt"](row.get("Name")))
            m.at[idx, "Email_Subject"] = subject
            m.at[idx, "Email_Body"] = body
            m.at[idx, "Attachment_Name"] = ns["attachment_name"](name)
            done += 1
            log(f"[email text] written for {name}")
        except Exception as e:
            log(f"[email text] could not write for {row.get('Clean_Name')}: {type(e).__name__}")
    if done:
        m.to_csv(path, index=False)
    return done
