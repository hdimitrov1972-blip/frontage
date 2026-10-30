"""Offline test of the runner with the real notebooks, a fake Drive, fake Google and a fake mail server.

    FRONTAGE_TEST_NOTEBOOKS=/path/to/notebooks python tests/test_runner.py

Needs write access to /content (the notebooks use that path, as in Colab).
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runner"))
NB_SRC = os.environ["FRONTAGE_TEST_NOTEBOOKS"]
CONTENT = "/content"

FAKES = r'''
import json, os, smtplib, time
time.sleep = lambda s: None
SENT = os.environ["FAKE_SENT_FILE"]
class FakeSMTP:
    def __init__(self, *a, **k): self.user = None
    def login(self, user, pw):
        if not pw: raise smtplib.SMTPAuthenticationError(535, b"no password")
        self.user = user
    def noop(self): return (250, b"ok")
    def ehlo(self, *a): return (250, b"ok")
    def send_message(self, msg, from_addr=None, to_addrs=None):
        to = to_addrs[0] if to_addrs else msg["To"]
        with open(SENT, "a") as f: f.write(json.dumps([self.user, to]) + "\n")
    def quit(self): pass
    def close(self): pass
smtplib.SMTP_SSL = FakeSMTP
smtplib.SMTP = FakeSMTP
try:
    import requests
    class R:
        def __init__(self, d): self.status_code, self._d, self.text = 200, d, json.dumps(d)
        def json(self): return self._d
    def fake_post(url, json=None, headers=None, timeout=30):
        q, page = json["textQuery"], int(json.get("pageToken") or 0)
        base = abs(hash(q)) % 100000
        places = [{"id": f"P{base}-{page}-{i}", "displayName": {"text": f"{q} #{page}-{i}"},
                   "websiteUri": f"https://b{base}{page}{i}.ie", "nationalPhoneNumber": "091 1",
                   "formattedAddress": "1 Main St, Ireland"} for i in range(20 if page < 2 else 5)]
        d = {"places": places}
        if page < 2: d["nextPageToken"] = str(page + 1)
        return R(d)
    requests.post = fake_post
except ImportError:
    pass
'''


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


def fresh_drive(n_leads=120):
    shutil.rmtree(CONTENT, ignore_errors=True)
    home = os.path.join(CONTENT, "drive", "MyDrive", "Frontage")
    os.makedirs(home + "/latest")
    os.makedirs(home + "/towns")
    os.makedirs(CONTENT + "/notebooks")
    for f in os.listdir(NB_SRC):
        if f.endswith(".ipynb"):
            shutil.copy(os.path.join(NB_SRC, f), CONTENT + "/notebooks/" + f)
    rows, tmp = [], tempfile.mkdtemp()
    with zipfile.ZipFile(home + "/latest/4A_reports.zip", "w") as z:
        for i in range(n_leads):
            p = os.path.join(tmp, f"r{i}.pdf")
            open(p, "wb").write(b"%PDF-1.4 fake")
            z.write(p, f"r{i}.pdf")
            rows.append({"place_id": f"p{i}", "Name": f"Biz {i}", "Clean_Name": f"Biz {i}",
                         "Best_Email": f"info@biz{i}.ie", "Send_Ready": True, "Funnel": "email",
                         "Status_Outreach": "pending", "Email_Approved": True, "Report_Status": "issues",
                         "Report_Date": date.today().isoformat(), "Report_File": f"r{i}.pdf",
                         "Email_Subject": f"Biz {i} website on a phone", "Email_Body": "Hello",
                         "Lead_Score": i % 10})
    pd.DataFrame(rows).to_csv(home + "/LEADS_MASTER.csv", index=False)
    pd.DataFrame(columns=["sent_at", "place_id", "email", "name", "subject", "mailbox"]).to_csv(
        home + "/0_sent_log.csv", index=False)
    open(home + "/0_do_not_contact.csv", "w").write("email_or_domain\n")
    for t in ("Limerick_2026-10-27", "Ennis_2026-10-28", "Waterford_2026-10-29", "Kilkenny_2026-10-30"):
        pd.DataFrame([{"place_id": "x", "name": "x"}]).to_csv(f"{home}/towns/{t}.csv", index=False)
    pd.DataFrame([{"file": f"{t}.csv", "done_on": "2026-10-30", "leads": 1} for t in
                  ("Limerick_2026-10-27", "Ennis_2026-10-28", "Waterford_2026-10-29", "Kilkenny_2026-10-30")]
                 ).to_csv(home + "/0_pipeline_done.csv", index=False)
    return home


def sent_lines():
    p = os.environ["FAKE_SENT_FILE"]
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


# ---- setup: fakes are loaded into every notebook process via sitecustomize
fakes_dir = tempfile.mkdtemp()
open(os.path.join(fakes_dir, "sitecustomize.py"), "w").write(FAKES)
os.environ["PYTHONPATH"] = fakes_dir
os.environ["FAKE_SENT_FILE"] = os.path.join(fakes_dir, "sent.jsonl")
for i in range(1, 6):
    os.environ[f"SMTP_PASSWORD_{i}"] = "x"
os.environ["PLACES_API_KEY"] = "KEY"
os.environ["TEST_EMAIL"] = "me@example.com"

import run_notebook  # noqa: E402
import daily  # noqa: E402

# 1. settings replacement and shell lines
cells = run_notebook.apply_settings(['A = 1\nTOWN = "Ennis"   # town\nB = 2'], {"TOWN": '"Drogheda"'})
check("setting replaced, comment kept", 'TOWN = "Drogheda"  # town' in cells[0] and "B = 2" in cells[0])
check("shell line skipped", "pass" in run_notebook.strip_shell_lines("  !pip install x") and "!" not in
      run_notebook.strip_shell_lines("  !pip install x"))
try:
    run_notebook.apply_settings(["X = [\n 1]\n"], {"X": "[]"})
    check("multi-line setting refused", False)
except SystemExit:
    check("multi-line setting refused", True)

# 2. live day with plenty of leads: no search, no pipeline, sender sends the warm-up amount
home = fresh_drive(120)
daily.in_send_window = lambda: (True, "test")
code = daily.run("live")
sent = sent_lines()
log = pd.read_csv(home + "/0_sent_log.csv", dtype=str)
check("live run finished OK", code == 0)
check("sender sent today's amount from the real notebook", 20 <= len(sent) <= 50 and len(log) == len(sent))
check("nobody emailed twice", len({t for _, t in sent}) == len(sent))
check("no search when leads are plenty", not any(f.startswith("Drogheda") for f in os.listdir(home + "/towns")))
check("private log written to Drive/runs", len(os.listdir(home + "/runs")) == 1)

# 3. same day again: nothing more is sent
os.remove(os.environ["FAKE_SENT_FILE"])
daily.run("live")
check("second run the same day sends nothing", sent_lines() == [])

# 4. test mode: only to TEST_EMAIL, master not changed
home = fresh_drive(120)
before = open(home + "/LEADS_MASTER.csv").read()
os.remove(os.environ["FAKE_SENT_FILE"]) if os.path.exists(os.environ["FAKE_SENT_FILE"]) else None
daily.run("test")
sent = sent_lines()
check("test: emails only to TEST_EMAIL", sent and {t for _, t in sent} == {"me@example.com"})
check("test: LEADS_MASTER unchanged", open(home + "/LEADS_MASTER.csv").read() == before)

# 5. outside the window: nothing sent
home = fresh_drive(120)
os.remove(os.environ["FAKE_SENT_FILE"]) if os.path.exists(os.environ["FAKE_SENT_FILE"]) else None
daily.in_send_window = lambda: (False, "Sat 10:00")
daily.run("live")
check("outside the window nothing is sent", sent_lines() == [])
daily.in_send_window = lambda: (True, "test")

# 6. leads low: searches the NEXT town in the queue (not Ennis again), then the pipeline gets it
home = fresh_drive(5)
check("next town skips towns already searched", daily.next_town(date.today()) == "Drogheda")
os.remove(os.environ["FAKE_SENT_FILE"]) if os.path.exists(os.environ["FAKE_SENT_FILE"]) else None
pipe_nb = os.path.join(CONTENT, "notebooks", daily.CONFIG["notebooks"]["pipeline"])
real_pipeline = open(pipe_nb).read()
# stand-in pipeline that breaks half way, to prove Drive is put back as it was
json.dump({"cells": [{"cell_type": "code", "source":
           "open('/content/drive/MyDrive/Frontage/LEADS_MASTER.csv','w').write('broken')\n"
           "raise RuntimeError('website visit failed')"}]}, open(pipe_nb, "w"))
master_before = open(home + "/LEADS_MASTER.csv").read()
code = daily.run("live")
towns = os.listdir(home + "/towns")
check("search made the Drogheda town file", any(t.startswith("Drogheda_") for t in towns))
check("search did not repeat Ennis", sum(t.startswith("Ennis_") for t in towns) == 1)
check("failed pipeline: run reported as failed", code == 1)
m_after = pd.read_csv(home + "/LEADS_MASTER.csv", dtype=str)
check("failed pipeline: LEADS_MASTER put back (then the sender marked its 5 as sent)",
      len(m_after) == 5 and (m_after["Status_Outreach"] == "sent").sum() == 5)
check("failed pipeline: town kept waiting for tomorrow", daily.waiting_town_files() == [t for t in towns if t.startswith("Drogheda_")])
check("failed pipeline: search results kept", os.path.exists(home + "/0_all_businesses.csv"))
check("failed pipeline: sender still ran with the old leads", len(sent_lines()) == 5)
check("failed pipeline: log kept", len(os.listdir(home + "/runs")) == 1)

# 7. job stopped in the middle of the pipeline: finalize puts Drive back
master_before = open(home + "/LEADS_MASTER.csv").read()
daily.snapshot()
open(home + "/LEADS_MASTER.csv", "w").write("half written")
daily.finalize()
check("stopped job: finalize restores Drive", open(home + "/LEADS_MASTER.csv").read() == master_before
      and not os.path.exists(daily.MARKER))

shutil.rmtree(CONTENT, ignore_errors=True)
print("\nALL RUNNER TESTS PASSED")
