"""Weekend follow-up with a fake mail server.   python tests/test_followup.py"""
import datetime as dt
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import followup  # noqa: E402
import summary  # noqa: E402

TODAY = dt.date(2026, 11, 14)          # a Saturday
SENT = []


class FakeSMTP:
    def __init__(self, *a, **k): self.user = None
    def login(self, u, p): self.user = u
    def send_message(self, msg, to_addrs=None): SENT.append((self.user, to_addrs[0], msg))
    def quit(self): pass


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


def setup():
    SENT.clear()
    home = tempfile.mkdtemp()
    rows = []
    for i in range(60):                       # 60 first emails, from 80 to 21 days ago
        day = TODAY - dt.timedelta(days=80 - i)
        rows.append({"sent_at": f"{day.isoformat()}T09:00:00", "place_id": f"p{i}", "email": f"info@biz{i}.ie",
                     "name": f"Biz {i}", "subject": f"Biz {i} website on a phone",
                     "mailbox": "hello@frontage.agency" if i % 2 == 0 else ["performance", "proposals", "audit", "contact"][i % 4] + "@frontage.agency",
                     "message_id": f"<m{i}@frontage.agency>" if i >= 30 else ""})
    pd.DataFrame(rows).to_csv(home + "/0_sent_log.csv", index=False)
    open(home + "/0_do_not_contact.csv", "w").write("email_or_domain\ninfo@biz35.ie\n@biz36.ie\n")
    pd.DataFrame([{"seen_at": "2026-11-10", "received": "2026-11-10", "mailbox": "hello@frontage.agency",
                   "message_id": f"<r{k}>", "kind": kind, "from": who, "matched_email": em, "subject": "Re"}
                  for k, (kind, who, em) in enumerate([("reply", "mary@biz34.ie", "info@biz34.ie"),
                                                      ("auto", "info@biz33.ie", "info@biz33.ie"),
                                                      ("bounce", "mailer-daemon@x", "info@biz32.ie"),
                                                      ("reply", "boss@biz31.ie", "info@biz31.ie")])]
                 ).to_csv(home + "/0_replies.csv", index=False)
    open(home + "/followup_text_A.txt", "w").write("Subject: ignored\nHi {name} team,\nJust checking you got my note.\nAnzhel")
    open(home + "/followup_text_B.txt", "w").write("Hi {name} team,\nA quick question about your website.\nAnzhel")
    return home


pw = {f"{b}@frontage.agency": "x" for b in followup.BOXES}
home = setup()
cand = followup.candidates(home, TODAY)
days = (pd.Timestamp(TODAY) - pd.to_datetime(cand["sent_at"].str[:10])).dt.days
check("only first emails 14+ days old", (days >= 14).all() and len(cand) > 0)
check("newest first", list(cand["sent_at"]) == sorted(cand["sent_at"], reverse=True))
skip = {"info@biz35.ie", "info@biz36.ie", "info@biz34.ie", "info@biz32.ie", "info@biz31.ie"}
check("never: do-not-contact, its domain, replied, bounced", not (set(cand["email"]) & skip))
check("auto-reply does not stop the follow-up", "info@biz33.ie" in set(cand["email"]))

c = followup.run(home, pw, today=TODAY, sleep=lambda s: None, smtp=FakeSMTP, log=lambda m: None)
check("daily limit for the domain", c["sent"] == followup.DAILY_MAX == len(SENT))
boxes = pd.Series([u for u, _, _ in SENT]).value_counts()
check("each follow-up from the mailbox that sent the first email",
      all(u == cand.set_index("email").at[to, "mailbox"] for u, to, _ in SENT))
check("no mailbox over its per-day limit", boxes.max() <= followup.PER_MAILBOX_MAX)
msg = next(m for _, to, m in SENT if to == "info@biz44.ie")
check("subject is Re: first subject, in the same conversation",
      msg["Subject"] == "Re: Biz 44 website on a phone" and msg["In-Reply-To"] == "<m44@frontage.agency>")
check("no PDF attached, name filled in", not list(msg.iter_attachments()) and "Hi Biz 44 team" in msg.get_content())
check("unsubscribe header and replies to hello@", "unsubscribe" in msg["List-Unsubscribe"] and msg["Reply-To"] == "hello@frontage.agency")
check("texts A and B take turns", set(c["per_variant"]) == {"A", "B"} and abs(c["per_variant"]["A"] - c["per_variant"]["B"]) <= 1)
log = pd.read_csv(home + "/0_followup_log.csv", dtype=str)
check("every follow-up logged with its text", len(log) == 30 and set(log["variant"]) == {"A", "B"})

SENT.clear()
c2 = followup.run(home, pw, today=TODAY, sleep=lambda s: None, smtp=FakeSMTP, log=lambda m: None)
check("second run the same day sends nothing more", c2["sent"] == 0)
c3 = followup.run(home, pw, today=TODAY + dt.timedelta(days=1), sleep=lambda s: None, smtp=FakeSMTP, log=lambda m: None)
check("next day: only businesses not followed up yet", not (set(to for _, to, _ in SENT) & set(log["email"])) and c3["sent"] > 0)

SENT.clear()
home2 = setup()
c4 = followup.run(home2, pw, today=TODAY, test_to="me@example.com", sleep=lambda s: None, smtp=FakeSMTP, log=lambda m: None)
check("test mode: one per mailbox, only to me, nothing logged", c4["sent"] == 5 and {t for _, t, _ in SENT} == {"me@example.com"}
      and not os.path.exists(home2 + "/0_followup_log.csv"))

SENT.clear()
open(home2 + "/0_PAUSE.txt", "w").write("paused")
check("paused: nothing sent", followup.run(home2, pw, today=TODAY, smtp=FakeSMTP, log=lambda m: None)["sent"] == 0)
os.remove(home2 + "/0_PAUSE.txt")
for f in ("followup_text_A.txt", "followup_text_B.txt"):
    os.remove(os.path.join(home2, f))
check("no text on Drive: nothing sent", followup.run(home2, pw, today=TODAY, smtp=FakeSMTP, log=lambda m: None)["sent"] == 0)

SENT.clear()
summary.run(home, TODAY + dt.timedelta(days=1), 123, "x", "me@example.com", smtp=FakeSMTP)
body = SENT[0][2].get_content()
check("Sunday summary emailed to me with the week's numbers",
      SENT[0][1] == "me@example.com" and "Follow-ups sent:" in body and "123" in body and "info@biz34.ie" in body)
check("summary copy saved on Drive, sent once", os.path.exists(home + "/runs/weekly_summary_2026-11-15.txt")
      and summary.run(home, TODAY + dt.timedelta(days=1), 1, "x", "me", smtp=FakeSMTP) and len(SENT) == 1)
print("\nALL FOLLOW-UP TESTS PASSED")
