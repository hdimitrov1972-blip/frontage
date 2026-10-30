"""Count which website problems Google's speed test found across all saved audits.

    python tools/analyze_audits.py LIGHTHOUSE_DIR OUT.csv

Prints the list as notes on the run page (problem names and counts only, no business data)."""
import collections
import glob
import json
import os
import sys

folder, out = sys.argv[1], sys.argv[2]
fails, warn, titles, values, units, n = collections.Counter(), collections.Counter(), {}, collections.defaultdict(list), {}, 0
for p in glob.glob(os.path.join(folder, "*.json")):
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    lh = d.get("lighthouseResult", d)
    audits = lh.get("audits", {})
    if not audits:
        continue
    n += 1
    for aid, a in audits.items():
        mode = a.get("scoreDisplayMode")
        score = a.get("score")
        if mode in ("informative", "manual", "notApplicable", "error") or score is None:
            continue
        titles[aid] = a.get("title", aid)
        if score < 0.5:
            fails[aid] += 1
        elif score < 0.9:
            warn[aid] += 1
        else:
            continue
        if isinstance(a.get("numericValue"), (int, float)):
            values[aid].append(a["numericValue"])
            units[aid] = a.get("numericUnit", "")
rows = []
for aid in set(fails) | set(warn):
    v = sorted(values[aid])
    rows.append({"audit": aid, "title": titles[aid], "failed": fails[aid], "warning": warn[aid],
                 "sites_with_problem": fails[aid] + warn[aid],
                 "share_of_sites": round((fails[aid] + warn[aid]) / n, 3) if n else 0,
                 "median_value": round(v[len(v) // 2], 1) if v else "", "unit": units.get(aid, "")})
rows.sort(key=lambda r: -r["sites_with_problem"])
import csv
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["audit"])
    w.writeheader()
    w.writerows(rows)
print(f"::notice::audits read: {n}   different problems found: {len(rows)}")
for r in rows[:40]:
    print(f"::notice::{r['sites_with_problem']:>4} sites ({r['share_of_sites']:.0%})  {r['audit']}  — {r['title'][:70]}"
          + (f"  [median {r['median_value']} {r['unit']}]" if r["median_value"] != "" else ""))
