"""Personal addresses move to the phone list and get no follow-ups.   python tests/test_freemail.py"""
import datetime as dt
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import followup  # noqa: E402
import freemail  # noqa: E402


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


home = tempfile.mkdtemp()
pd.DataFrame([
    {"place_id": "1", "Funnel": "email", "Status_Outreach": "pending", "Best_Email": "Joe@Gmail.com", "Send_Ready": "True"},
    {"place_id": "2", "Funnel": "email", "Status_Outreach": "pending", "Best_Email": "info@cafe.ie", "Send_Ready": "True"},
    {"place_id": "3", "Funnel": "email", "Status_Outreach": "sent", "Best_Email": "old@eircom.net", "Send_Ready": "True"},
    {"place_id": "4", "Funnel": "email", "Status_Outreach": "pending", "Best_Email": "x@rocketmail.com", "Send_Ready": "True"},
]).to_csv(home + "/LEADS_MASTER.csv", index=False)
n = freemail.move_to_phone(home, log=lambda m: None)
m = pd.read_csv(home + "/LEADS_MASTER.csv", dtype=str, keep_default_na=False).set_index("place_id")
check("pending personal addresses move to the phone list", n == 2 and m.loc["1", "Funnel"] == "phone"
      and m.loc["4", "Funnel"] == "phone" and m.loc["1", "Send_Ready"] == "False")
check("company addresses and already-sent rows untouched", m.loc["2", "Funnel"] == "email" and m.loc["3", "Funnel"] == "email")
check("second run: nothing more to move", freemail.move_to_phone(home, log=lambda m: None) == 0)

pd.DataFrame([{"sent_at": "2026-10-20T09:00:00", "place_id": "a", "email": "owner@gmail.com", "subject": "s"},
              {"sent_at": "2026-10-20T09:00:00", "place_id": "b", "email": "info@shop.ie", "subject": "s"}]).to_csv(
    home + "/0_sent_log.csv", index=False)
c = followup.candidates(home, dt.date(2026, 11, 14))
check("no follow-up to personal addresses, company ones still get it", list(c["email"]) == ["info@shop.ie"])
print("\nALL FREE MAIL TESTS PASSED")
