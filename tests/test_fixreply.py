"""'Yes' reply -> personal 3-fixes draft.   FRONTAGE_TEST_GUIDE=... FRONTAGE_TEST_AUDIT=... python tests/test_fixreply.py"""
import json
import os
import shutil
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import fixreply  # noqa: E402

GUIDE, AUDIT = os.environ["FRONTAGE_TEST_GUIDE"], os.environ["FRONTAGE_TEST_AUDIT"]
DRAFTS, MAILS = [], []


class FakeIMAP:
    def __init__(self, *a, **k): pass
    def login(self, u, p): pass
    def list(self): return "OK", [b'(\\HasNoChildren) "." "INBOX"', b'(\\HasNoChildren \\Drafts) "." "INBOX.Drafts"']
    def append(self, folder, flags, when, raw): DRAFTS.append((folder, flags, raw)); return "OK", [b""]
    def logout(self): pass


class FakeSMTP:
    def __init__(self, *a, **k): pass
    def login(self, u, p): pass
    def send_message(self, msg, to_addrs=None): MAILS.append((to_addrs[0], msg))
    def quit(self): pass


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


for t, want in [("Yes please!", True), ("yes, send them over", True), ("Sure, that would help", True),
                ("That would be great thanks", True), ("Hi Anzhel, how much would that cost?", False),
                ("No thanks", False), ("Not at the moment", False), ("ok", True)]:
    check(f"'{t}' -> {'yes' if want else 'not yes'}", fixreply.is_yes(t) == want)

guide = json.load(open(GUIDE))
audits = json.load(open(AUDIT)).get("audits") or json.load(open(AUDIT))["lighthouseResult"]["audits"]
text = fixreply.compose("Hickey's Bakery", audits, guide)
print("\n" + text + "\n")
check("3 numbered fixes", all(f"\n{i}. " in text for i in (1, 2, 3)) and "\n4. " not in text)
check("their own numbers are in it", "5.6 seconds" in text)
check("no empty placeholders", "{" not in text and "  ." not in text)
check("offer section without a price", guide["offer_title"] in text and "€" not in text)

home = tempfile.mkdtemp()
os.makedirs(home + "/lighthouse_json")
shutil.copy(AUDIT, home + "/lighthouse_json/ChIJ_bakery.json")
shutil.copy(GUIDE, home + "/fix_guide.json")
pd.DataFrame([{"sent_at": "2026-11-01T09:00:00", "place_id": "ChIJ_bakery", "email": "brian@hickeysbakery.ie",
               "name": "Hickey's Bakery", "subject": "Hickey's Bakery website on a phone", "mailbox": "proposals@frontage.agency"},
              {"sent_at": "2026-11-01T09:00:00", "place_id": "ChIJ_none", "email": "info@noaudit.ie", "name": "No Audit",
               "subject": "x", "mailbox": "hello@frontage.agency"}]).to_csv(home + "/0_sent_log.csv", index=False)
pd.DataFrame([{"seen_at": "2026-11-16", "received": "2026-11-16", "mailbox": "hello@frontage.agency", "message_id": "<y1@x>",
               "kind": "reply", "from": "brian@hickeysbakery.ie", "matched_email": "brian@hickeysbakery.ie",
               "subject": "Re: Hickey's Bakery website on a phone", "first_lines": "Yes please, that would be great"},
              {"seen_at": "2026-11-16", "received": "2026-11-16", "mailbox": "hello@frontage.agency", "message_id": "<y2@x>",
               "kind": "reply", "from": "info@noaudit.ie", "matched_email": "info@noaudit.ie",
               "subject": "Re: x", "first_lines": "yes"},
              {"seen_at": "2026-11-16", "received": "2026-11-16", "mailbox": "hello@frontage.agency", "message_id": "<q1@x>",
               "kind": "reply", "from": "a@b.ie", "matched_email": "a@b.ie", "subject": "Re: y",
               "first_lines": "How much would it cost?"}]).to_csv(home + "/0_replies.csv", index=False)
c = fixreply.run(home, "pw", "me@example.com", imap_cls=FakeIMAP, smtp=FakeSMTP, log=print)
check("one draft for the clear 'yes' with a speed test", c["drafted"] == 1 and len(DRAFTS) == 1)
folder, flags, raw = DRAFTS[0]
draft = raw.decode()
check("draft saved in hello@ Drafts, marked as draft", folder == '"INBOX.Drafts"' and flags == "\\Draft")
check("draft addressed and threaded to their reply",
      "To: brian@hickeysbakery.ie" in draft and "In-Reply-To: <y1@x>" in draft and "Subject: Re: Hickey's Bakery" in draft)
check("you get an email with the same text", any(to == "me@example.com" and "Drafts" in m["Subject"] for to, m in MAILS))
check("'yes' without a speed test -> you are told to answer by hand", c["needs_you"] == 1
      and any("by hand" in m["Subject"] for _, m in MAILS))
check("a question is left for you, not drafted", c["yes_replies"] == 2)
DRAFTS.clear(); MAILS.clear()
c2 = fixreply.run(home, "pw", "me@example.com", imap_cls=FakeIMAP, smtp=FakeSMTP, log=print)
check("nothing prepared twice", c2["yes_replies"] == 0 and not DRAFTS and not MAILS)
print("\nALL FIX-REPLY TESTS PASSED")
