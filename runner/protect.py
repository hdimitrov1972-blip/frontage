"""Keep Anzhel's phone edits made on Drive WHILE a run is busy (a run can take up to ~4 hours).

The workflow lists the Drive folder right after downloading (before.json) and again just before saving
(after.json). For the files Anzhel edits by hand, a newer Drive copy is fetched and merged into the run's copy:
- 0_do_not_contact.csv          : both lists together
- 2B_suspect_review.csv          : his yes/no answers kept, new rows from both kept
- Contact_forms_to_send.xlsx     : his Done ticks kept
- 0_PAUSE.txt                    : if he deleted it during the run, the run does not put it back

    python runner/protect.py BEFORE.json AFTER.json DRIVE_DIR
"""
import json
import os
import subprocess
import sys

import pandas as pd

PROTECTED = ["0_do_not_contact.csv", "2B_suspect_review.csv", "Contact_forms_to_send.xlsx", "0_PAUSE.txt"]


def _listing(path):
    try:
        return {f["Path"]: f.get("ModTime", "") for f in json.load(open(path)) if not f.get("IsDir")}
    except Exception:
        return None


def merge_dnc(fresh, local):
    lines = [l.strip() for l in open(local, encoding="utf-8")] if os.path.exists(local) else ["email_or_domain"]
    have = {l.lower() for l in lines}
    add = [l.strip() for l in open(fresh, encoding="utf-8") if l.strip() and l.strip().lower() not in have]
    if add:
        with open(local, "w", encoding="utf-8") as f:
            f.write("\n".join([l for l in lines if l] + add) + "\n")
    return len(add)


def merge_suspects(fresh, local):
    f = pd.read_csv(fresh, dtype=str, keep_default_na=False)
    l = pd.read_csv(local, dtype=str, keep_default_na=False) if os.path.exists(local) else f.iloc[0:0]
    if "place_id" not in f.columns or "Approve" not in f.columns:
        return 0
    answers = {p: a for p, a in zip(f["place_id"], f["Approve"]) if a.strip()}
    n = 0
    for i, p in l["place_id"].items():
        if p in answers and not l.at[i, "Approve"].strip():
            l.at[i, "Approve"] = answers[p]
            n += 1
    extra = f[~f["place_id"].isin(set(l["place_id"]))]
    out = pd.concat([l, extra], ignore_index=True)
    out.to_csv(local, index=False)
    return n + len(extra)


def reconcile(before_path, after_path, drive_dir, fetch=None, log=print):
    before, after = _listing(before_path), _listing(after_path)
    if before is None or after is None:
        log("[protect] Drive listing missing — nothing merged")
        return {}
    fetch = fetch or (lambda name, dest: subprocess.call(
        ["rclone", "copyto", f"gdrive:Frontage/{name}", dest, "--quiet"], timeout=120) == 0)
    done = {}
    for name in PROTECTED:
        local = os.path.join(drive_dir, name)
        if name == "0_PAUSE.txt":
            if name in before and name not in after and os.path.exists(local):
                os.remove(local)                    # deleted by Anzhel during the run: don't bring it back
                done[name] = "kept deleted"
            continue
        if name not in after or after.get(name) == before.get(name):
            continue                                # not touched on Drive during the run
        fresh = os.path.join("/tmp" if not os.environ.get("RUNNER_TEMP") else os.environ["RUNNER_TEMP"],
                             "fresh_" + name)
        if not fetch(name, fresh):
            continue
        if name == "0_do_not_contact.csv":
            done[name] = merge_dnc(fresh, local)
        elif name == "2B_suspect_review.csv":
            done[name] = merge_suspects(fresh, local)
        elif name == "Contact_forms_to_send.xlsx":
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import contactforms
            done[name] = contactforms.merge_done(fresh, local)
    for k, v in done.items():
        log(f"[protect] {k}: your change during the run kept ({v})")
    return done


if __name__ == "__main__":
    reconcile(sys.argv[1], sys.argv[2], sys.argv[3])
