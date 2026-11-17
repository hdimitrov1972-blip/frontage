"""Make 'Frontage Sender v2.6 LIVE.ipynb' from 'Frontage Sender v2.5 LIVE.ipynb'.

    python tools/upgrade_sender_v26.py OLD.ipynb NEW.ipynb

The only change (Anzhel's decision, 17 Nov 2026): a SAFE_ONLY setting for the bounce brake's slow mode.
With SAFE_ONLY = True the sender only emails addresses on the business's own website domain
(info@pub.ie for pub.ie or www.pub.ie), the addresses least likely to bounce. The others stay pending
and are sent normally once the brake is back to normal. The runner sets SAFE_ONLY = True while
0_SLOW.txt is on Drive. Default False: nothing changes in normal sending.
Text, limits, pacing, logging, do-not-contact: untouched. Stops if v2.5 isn't exactly as expected.
"""
import json
import sys

CHANGES = [
    ('''# Two reply buttons ("Yes, send me the report" / "No thanks") in every no-PDF email.
BUTTONS = True
''', '''# Two reply buttons ("Yes, send me the report" / "No thanks") in every no-PDF email.
BUTTONS = True
# SLOW MODE (bounce brake, from 17 Nov 2026): True = only addresses on the business's own website
# domain (info@pub.ie for pub.ie). The runner sets it while bounces are over 3%. Normal: False.
SAFE_ONLY = False
'''),
    ('''def eligible_leads(df):
''', '''def _site_domain(url):
    """'https://www.Pub.ie/menu' -> 'pub.ie'."""
    u = re.sub(r"^[a-z][a-z0-9+.-]*://", "", safe_str(url).strip().lower())
    u = re.split(r"[/?#:]", u, maxsplit=1)[0]
    return u[4:] if u.startswith("www.") else u


def same_domain_as_site(row):
    """True when the address is on the business's own website domain (or a sub-domain of it)."""
    to = safe_str(row.get("_to")).lower()
    dom = to.rsplit("@", 1)[-1] if "@" in to else ""
    site = _site_domain(row.get("Website")) or _site_domain(row.get("website"))
    return bool(dom and site) and (dom == site or dom.endswith("." + site) or site.endswith("." + dom))


def eligible_leads(df):
'''),
    ('''    eligible["_score"] = (pd.to_numeric(eligible["Lead_Score"], errors="coerce").fillna(0)
''', '''    if SAFE_ONLY and len(eligible):
        safe = eligible.apply(same_domain_as_site, axis=1).astype(bool)
        print(f"🐢 Slow mode: only addresses on the business's own website domain today "
              f"({int(safe.sum())} of {len(eligible)}; the rest wait for normal sending)")
        eligible = eligible[safe]

    eligible["_score"] = (pd.to_numeric(eligible["Lead_Score"], errors="coerce").fillna(0)
'''),
    ('FRONTAGE SENDER v2.5 (one domain, long/short test, buttons)',
     'FRONTAGE SENDER v2.6 (one domain, long/short test, buttons, safe-only slow mode)'),
]


def upgrade(src):
    for old, new in CHANGES:
        if src.count(old) != 1:
            raise SystemExit(f"v2.5 is not as expected; nothing changed. Missing: {old[:60]!r}")
        src = src.replace(old, new)
    return src


def main(old_path, new_path):
    nb = json.load(open(old_path, encoding="utf-8"))
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    if len(code) != 1:
        raise SystemExit("expected one code cell")
    for c in nb["cells"]:
        src = "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
        if c["cell_type"] == "code":
            c["source"] = upgrade(src).splitlines(keepends=True)
            c["outputs"], c["execution_count"] = [], None
        else:
            c["source"] = src.replace("v2.5", "v2.6").splitlines(keepends=True)
    json.dump(nb, open(new_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("Sender v2.6 made: SAFE_ONLY slow-mode setting added; everything else unchanged.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
