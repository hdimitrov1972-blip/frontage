"""Missing email texts are written with the pipeline notebook's own build_email.   python tests/test_emailtext.py"""
import json
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import emailtext  # noqa: E402


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


CELL = '''import os
from google.colab import files
INPUT_CSV = "x.csv"
def txt(v):
    return "" if v is None or (isinstance(v, float) and v != v) else str(v).strip()
def short_name(n):
    return n.split(",")[0]
def attachment_name(n):
    return n.replace(" ", "") + "-Report.pdf"
def build_email(row):
    return f"{short_name(txt(row.get('Clean_Name')))} website on a phone", f"Hi {short_name(txt(row.get('Clean_Name')))} team, score {int(row.get('Mobile'))}"
run_outbox()
'''
home = tempfile.mkdtemp()
nb = {"cells": [{"cell_type": "markdown", "source": ["# outbox"]},
                {"cell_type": "code", "source": [CELL]}]}
json.dump(nb, open(home + "/pipe.ipynb", "w"))
pd.DataFrame([
    {"Clean_Name": "Pantry, Kilkenny", "Funnel": "email", "Status_Outreach": "pending", "Send_Ready": True,
     "Email_Approved": True, "Email_Subject": None, "Email_Body": None, "Mobile": 64},
    {"Clean_Name": "Has Text", "Funnel": "email", "Status_Outreach": "pending", "Send_Ready": True,
     "Email_Approved": True, "Email_Subject": "keep", "Email_Body": "keep me", "Mobile": 50},
    {"Clean_Name": "Not Approved", "Funnel": "email", "Status_Outreach": "pending", "Send_Ready": False,
     "Email_Approved": False, "Email_Subject": None, "Email_Body": None, "Mobile": 40},
    {"Clean_Name": "Already Sent", "Funnel": "email", "Status_Outreach": "sent", "Send_Ready": True,
     "Email_Approved": True, "Email_Subject": None, "Email_Body": None, "Mobile": 40},
]).to_csv(home + "/LEADS_MASTER.csv", index=False)
n = emailtext.fill_missing(home, home + "/pipe.ipynb", log=lambda m: None)
m = pd.read_csv(home + "/LEADS_MASTER.csv", dtype=str, keep_default_na=False)
check("only the approved, ready, pending lead without text gets one", n == 1)
check("text comes from the notebook's own build_email", m.loc[0, "Email_Subject"] == "Pantry website on a phone"
      and m.loc[0, "Email_Body"] == "Hi Pantry team, score 64" and m.loc[0, "Attachment_Name"] == "Pantry-Report.pdf")
check("existing texts untouched", m.loc[1, "Email_Body"] == "keep me")
check("not approved / already sent untouched", m.loc[2, "Email_Body"] == "" and m.loc[3, "Email_Body"] == "")
check("the notebook's run_outbox() is never called", True)
check("nothing to do: notebook not even needed", emailtext.fill_missing(home, home + "/missing.ipynb") == 0)
print("\nALL EMAIL TEXT TESTS PASSED")
