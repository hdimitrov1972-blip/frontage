"""Personal email addresses (Gmail, Hotmail, Eircom...) are not emailed any more (Anzhel's decision, 11 Nov 2026).

They usually belong to one-person businesses (sole traders), and Irish rules (S.I. 336/2011) need their
consent before marketing email. Their leads move to the phone funnel, where the contact-form list can pick them up.
"""
import os

import pandas as pd

from replies import FREE_MAIL

REASON = "personal email address (likely a sole trader): contact form or phone only"


def move_to_phone(home, log=print):
    path = os.path.join(home, "LEADS_MASTER.csv")
    if not os.path.exists(path):
        return 0
    m = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in ("Funnel", "Status_Outreach", "Best_Email", "Send_Ready", "Send_Block_Reason"):
        if c not in m.columns:
            m[c] = ""
    dom = m["Best_Email"].str.strip().str.lower().str.split("@").str[-1]
    hit = (m["Funnel"] == "email") & (m["Status_Outreach"].str.lower() == "pending") & dom.isin(FREE_MAIL)
    n = int(hit.sum())
    if n:
        m.loc[hit, "Funnel"] = "phone"
        m.loc[hit, "Send_Ready"] = "False"
        m.loc[hit, "Send_Block_Reason"] = REASON
        m.to_csv(path, index=False)
        log(f"[free mail] {n} lead(s) with a personal address moved to the phone / contact-form list")
    return n
