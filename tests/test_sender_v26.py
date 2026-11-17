"""Sender v2.6 slow mode (SAFE_ONLY) on the real notebook, offline.

    FRONTAGE_TEST_SENDER="/path/Frontage Sender v2.5 LIVE.ipynb" python tests/test_sender_v26.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runner"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import colab_stub  # noqa: E402,F401
import pandas as pd  # noqa: E402
import upgrade_sender_v26  # noqa: E402


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


v25 = os.environ.get("FRONTAGE_TEST_SENDER", "")
if not v25:
    print("FRONTAGE_TEST_SENDER not set — skipped\n\nALL SENDER V2.6 TESTS PASSED")
    sys.exit(0)
new = os.path.join(tempfile.mkdtemp(), "v26.ipynb")
upgrade_sender_v26.main(v25, new)
src = "".join("".join(c["source"]) for c in json.load(open(new))["cells"] if c["cell_type"] == "code")
ns = {"__name__": "sender_under_test"}
exec(compile(src, "sender", "exec"), ns)
check("default SAFE_ONLY = False", ns["SAFE_ONLY"] is False)

f = ns["same_domain_as_site"]
for to, site, want in [("info@pub.ie", "https://www.pub.ie/menu", True), ("info@pub.ie", "pub.ie", True),
                       ("hello@mail.pub.ie", "http://pub.ie", True), ("contact@hitsona.com", "https://soulofbeauty.ie", False),
                       ("x@y.ie", "", False), ("info@pub.ie", "https://www.pub.com", False)]:
    check(f"same domain: {to} / {site or '(no site)'} -> {want}", f({"_to": to, "Website": site}) == want)

# eligible_leads with fakes for Drive, the sent log and the PDFs
home = tempfile.mkdtemp()
os.makedirs(os.path.join(home, "reports"))
os.chdir(home)
rows = []
for i, (email, site) in enumerate([("info@a.ie", "https://a.ie"), ("contact@webdesign.com", "https://b.ie"),
                                   ("bookings@c.ie", "www.c.ie")]):
    open(os.path.join(home, "reports", f"r{i}.pdf"), "w").write("pdf")
    rows.append({"place_id": f"p{i}", "Best_Email": email, "Website": site, "Send_Ready": "True", "Funnel": "email",
                 "Status_Outreach": "pending", "Email_Approved": "True", "Report_File": f"r{i}.pdf",
                 "Report_Date": pd.Timestamp.today().strftime("%Y-%m-%d"), "Lead_Score": str(10 - i)})
df = pd.DataFrame(rows)
ns["load_sent_log"] = lambda: pd.DataFrame(columns=["place_id", "email"])
ns["load_dnc"] = lambda: set()
ns["REPORTS_DIR"] = os.path.join(home, "reports")
check("normal: all 3 eligible, best score first when no tiers",
      list(ns["eligible_leads"](df.copy())["place_id"]) == ["p0", "p1", "p2"])
tiered = df.copy()
tiered["Target_Tier"] = ["2", "1", ""]
check("small places first: tier 2 (hotel) goes last even with the best score",
      list(ns["eligible_leads"](tiered)["place_id"]) == ["p1", "p2", "p0"])
ns["SAFE_ONLY"] = True
safe = ns["eligible_leads"](df.copy())
check("slow mode: only the 2 on their own website domain", sorted(safe["place_id"]) == ["p0", "p2"])
print("\nALL SENDER V2.6 TESTS PASSED")
