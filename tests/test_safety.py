"""Archive of emailed leads + PDFs, replies matched by thread, alerts, and keeping phone edits made during a run.
    python tests/test_safety.py"""
import datetime as dt
import email
import json
import os
import sys
import tempfile
import zipfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import alerts  # noqa: E402
import archive  # noqa: E402
import fixreply  # noqa: E402
import protect  # noqa: E402
import replies  # noqa: E402


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


# ---------- archive ----------
home = tempfile.mkdtemp()
os.makedirs(home + "/latest")
with zipfile.ZipFile(home + "/latest/4A_reports.zip", "w") as z:
    z.writestr("reports/b.pdf", b"%PDF b")
pd.DataFrame([{"place_id": "pb", "Clean_Name": "Bee Cafe", "city": "Ennis", "Template": "outbox_v1_nopdf",
               "Report_File": "b.pdf", "Attachment_Name": "Bee-Report.pdf", "Email_Subject": "Bee website"},
              {"place_id": "pa", "Clean_Name": "Ay Pub", "Template": "outbox_v1", "Report_File": "gone.pdf"}]
             ).to_csv(home + "/LEADS_MASTER.csv", index=False)
pd.DataFrame([{"sent_at": "2026-11-11T09:00:00", "place_id": "pb", "email": "b@bee.ie", "name": "Bee Cafe",
               "subject": "s", "mailbox": "hello@frontage.agency", "message_id": "<m1@frontage.agency>"},
              {"sent_at": "2026-11-11T09:02:00", "place_id": "pa", "email": "a@ay.ie", "name": "Ay Pub",
               "subject": "s", "mailbox": "audit@frontage.agency", "message_id": "<m2@frontage.agency>"}]
             ).to_csv(home + "/0_sent_log.csv", index=False)
n = archive.run(home, log=lambda m: None)
ar = pd.read_csv(home + "/0_sent_leads.csv", dtype=str, keep_default_na=False).set_index("place_id")
check("every emailed business archived once, with its version and PDF", n == 2 and ar.loc["pb", "Template"] == "outbox_v1_nopdf"
      and ar.loc["pb", "pdf_saved"] == "yes" and os.path.exists(home + "/sent_reports/b.pdf")
      and ar.loc["pa", "pdf_saved"] == "no")
check("second run adds nothing", archive.run(home, log=lambda m: None) == 0)

# the pipeline drops the lead and its PDF (new town) -> a yes still gets the promised report
pd.DataFrame([{"place_id": "new", "Clean_Name": "New", "Template": ""}]).to_csv(home + "/LEADS_MASTER.csv", index=False)
os.remove(home + "/latest/4A_reports.zip")
got = fixreply.report_for_no_pdf_email(home, "pb")
check("report found in the archive after the lead left LEADS_MASTER", got and got[0] == b"%PDF b"
      and got[1] == "Bee-Report.pdf")
check("version-A lead: no report attached", fixreply.report_for_no_pdf_email(home, "pa") is None)

# ---------- replies matched by thread ----------
msg = email.message_from_string("From: Owner <owner.bee@gmail.com>\nTo: hello@frontage.agency\nSubject: Re: Bee website\n"
                                "In-Reply-To: <m1@frontage.agency>\nMessage-ID: <r1>\n\nHow much would it cost?\n")
kind, matched = replies.classify(msg, {"b@bee.ie", "a@ay.ie"}, {"bee.ie": "b@bee.ie"},
                                 {"<m1@frontage.agency>": "b@bee.ie"})
check("owner answers from his own Gmail: matched to the business by thread", kind == "reply" and matched == "b@bee.ie")
stranger = email.message_from_string("From: x@gmail.com\nSubject: hi\nMessage-ID: <r2>\n\nhello\n")
check("unrelated mail still ignored", replies.classify(stranger, {"b@bee.ie"}, {}, {"<m1@frontage.agency>": "b@bee.ie"})
      == (None, None))

# ---------- alerts ----------
sent_alerts = []
note = (lambda text, subj, pw, to: sent_alerts.append(subj))
w = {"timezone": "Europe/Dublin", "weekdays": [0, 1, 2, 3, 4], "end": "17:00"}
h2 = tempfile.mkdtemp()
alerts.check(h2, False, dt.datetime(2026, 11, 11, 12, 0), w, "pw", "me@x", note, log=lambda m: None)
alerts.check(h2, False, dt.datetime(2026, 11, 11, 15, 0), w, "pw", "me@x", note, log=lambda m: None)
check("failed run: one alert per day, not one per run", sent_alerts == ["⚠️ Frontage: a run failed today"])
open(h2 + "/0_PAUSE.txt", "w").write("x")
alerts.check(h2, True, dt.datetime(2026, 11, 11, 18, 0), w, "pw", "me@x", note, log=lambda m: None)
check("weekday after 17:00 with 0 sent: alert", sent_alerts[-1] == "⚠️ Frontage: no emails went out today")
sent_alerts.clear()
alerts.check(h2, True, dt.datetime(2026, 11, 14, 18, 0), w, "pw", "me@x", note, log=lambda m: None)
check("Saturday: no 'zero sent' alert", sent_alerts == [])
pd.DataFrame([{"sent_at": "2026-11-12T10:00:00", "email": "x@y.ie"}]).to_csv(h2 + "/0_sent_log.csv", index=False)
alerts.check(h2, True, dt.datetime(2026, 11, 12, 18, 0), w, "pw", "me@x", note, log=lambda m: None)
check("emails went out: no alert", sent_alerts == [])

# ---------- keeping phone edits made during a run ----------
d = tempfile.mkdtemp()
open(d + "/0_do_not_contact.csv", "w").write("email_or_domain\n@a.ie\nnew@machine.ie\n")
pd.DataFrame([{"place_id": "s1", "Approve": ""}, {"place_id": "s2", "Approve": ""}, {"place_id": "s3", "Approve": ""}]
             ).to_csv(d + "/2B_suspect_review.csv", index=False)
open(d + "/0_PAUSE.txt", "w").write("paused")
open(d + "/before.json", "w").write(json.dumps([
    {"Path": "0_do_not_contact.csv", "ModTime": "t1"}, {"Path": "2B_suspect_review.csv", "ModTime": "t1"},
    {"Path": "0_PAUSE.txt", "ModTime": "t1"}, {"Path": "LEADS_MASTER.csv", "ModTime": "t1"}]))
open(d + "/after.json", "w").write(json.dumps([
    {"Path": "0_do_not_contact.csv", "ModTime": "t2"}, {"Path": "2B_suspect_review.csv", "ModTime": "t2"},
    {"Path": "LEADS_MASTER.csv", "ModTime": "t1"}]))
drive_now = {"0_do_not_contact.csv": "email_or_domain\n@a.ie\nmanual@owner.ie\n",
             "2B_suspect_review.csv": "place_id,Approve\ns1,yes\ns2,\ns4,\n"}


def fetch(name, dest):
    open(dest, "w").write(drive_now[name])
    return True


done = protect.reconcile(d + "/before.json", d + "/after.json", d, fetch=fetch, log=lambda m: None)
dnc = open(d + "/0_do_not_contact.csv").read().split()
sr = pd.read_csv(d + "/2B_suspect_review.csv", dtype=str, keep_default_na=False).set_index("place_id")
check("do-not-contact: machine's and your additions both kept", "manual@owner.ie" in dnc and "new@machine.ie" in dnc
      and dnc.count("@a.ie") == 1)
check("weekly-check answer typed during the run kept", sr.loc["s1", "Approve"] == "yes" and "s4" in sr.index
      and "s3" in sr.index)
check("0_PAUSE.txt you deleted during the run is not put back", not os.path.exists(d + "/0_PAUSE.txt"))
check("files you didn't touch are left alone", "LEADS_MASTER.csv" not in done)
check("listing missing: nothing merged, nothing broken", protect.reconcile(d + "/nope.json", d + "/after.json", d,
                                                                          fetch=fetch, log=lambda m: None) == {})

# ---------- archive heals itself, and the one-off recovery fills it from older Drive versions ----------
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import recover_archive  # noqa: E402
h3 = tempfile.mkdtemp()
os.makedirs(h3 + "/latest")
pd.DataFrame([{"sent_at": "2026-11-11T09:00:00", "place_id": "x1", "email": "a@x1.ie", "name": "X One"},
              {"sent_at": "2026-11-11T09:05:00", "place_id": "x2", "email": "a@x2.ie", "name": "X Two"},
              {"sent_at": "2026-10-09T09:05:00", "place_id": "x3", "email": "a@x3.ie", "name": "X Three"}]
             ).to_csv(h3 + "/0_sent_log.csv", index=False)
pd.DataFrame([{"place_id": "other"}]).to_csv(h3 + "/LEADS_MASTER.csv", index=False)       # rows already dropped
archive.run(h3, log=lambda m: None)
a3 = pd.read_csv(h3 + "/0_sent_leads.csv", dtype=str, keep_default_na=False).set_index("place_id")
check("dropped rows are archived without details (the gap found on 12 Nov)", a3.loc["x1", "Template"] == ""
      and a3.loc["x1", "pdf_saved"] == "no")
# the lead comes back into LEADS_MASTER / the zip (or was simply late): the next run completes the row
pd.DataFrame([{"place_id": "x1", "Template": "outbox_v1_nopdf", "Report_File": "x1.pdf", "Attachment_Name": "X1.pdf"}]
             ).to_csv(h3 + "/LEADS_MASTER.csv", index=False)
with zipfile.ZipFile(h3 + "/latest/4A_reports.zip", "w") as z:
    z.writestr("x1.pdf", b"%PDF x1")
archive.run(h3, log=lambda m: None)
a3 = pd.read_csv(h3 + "/0_sent_leads.csv", dtype=str, keep_default_na=False).set_index("place_id")
check("archive completes an earlier row when its details turn up", a3.loc["x1", "Template"] == "outbox_v1_nopdf"
      and a3.loc["x1", "pdf_saved"] == "yes" and os.path.exists(h3 + "/sent_reports/x1.pdf"))
n3 = recover_archive.fill(h3, {"x2": {"Report_File": "x2.pdf", "Clean_Name": "X Two", "city": "Ennis"},
                               "x3": {"Report_File": "x3.pdf", "Template": "outbox_v1"}},
                          {"x2.pdf": b"%PDF x2"}, log=lambda m: None)
a3 = pd.read_csv(h3 + "/0_sent_leads.csv", dtype=str, keep_default_na=False).set_index("place_id")
check("recovery: sent from 11 Nov without a version mark = version B, and its PDF is kept",
      a3.loc["x2", "Template"] == "outbox_v1_nopdf" and a3.loc["x2", "pdf_saved"] == "yes" and a3.loc["x2", "city"] == "Ennis")
check("recovery: older sends stay version A; a PDF that no longer exists is reported, not invented",
      a3.loc["x3", "Template"] == "outbox_v1" and a3.loc["x3", "pdf_saved"] == "no"
      and n3["version_b"] == 2 and n3["version_b_with_pdf"] == 2)
got3 = fixreply.report_for_no_pdf_email(h3, "x2")
check("a yes from a recovered business gets its report", got3 and got3[0] == b"%PDF x2")
print("\nALL SAFETY TESTS PASSED")
