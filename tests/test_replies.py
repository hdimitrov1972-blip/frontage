"""Reply and bounce stopper with fake mailboxes.   python tests/test_replies.py"""
import datetime as dt
import email
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import replies  # noqa: E402

TODAY = dt.date(2026, 11, 2)


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


def mail(frm, subject, body, mid, headers="", ctype="text/plain"):
    return email.message_from_string(
        f"From: {frm}\nTo: hello@frontage.agency\nSubject: {subject}\nMessage-ID: <{mid}>\n"
        f"Date: Mon, 02 Nov 2026 10:00:00 +0000\n{headers}Content-Type: {ctype}\n\n{body}\n")


DSN = ('Content-Type: multipart/report; report-type=delivery-status; boundary="b"\n\n--b\nContent-Type: text/plain\n\n'
       'Delivery failed.\n--b\nContent-Type: message/delivery-status\n\nReporting-MTA: dns; mx.hostinger.com\n\n'
       'Final-Recipient: rfc822; gone@deadbiz.ie\nAction: failed\nStatus: 5.1.1\n--b--\n')

BOXES = {
    "hello@frontage.agency": [
        mail("Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "Delivery Status Notification (Failure)",
             "Your message wasn't delivered to booking@holeinthewallbar.ie because the address couldn't be found. "
             "From hello@frontage.agency", "b1"),
        mail("Fernroyd House <fernroydhousebandb@gmail.com>", "Re: Fernroyd House website on a phone",
             "No thanks.\n\nOn Fri 9 Oct 2026, Frontage Agency wrote:\n> Hi Fernroyd House team, interested?", "r1"),
        mail("The Hair Space <info@thehairspace.ie>", "Thank you for contacting us!", "We aim to respond within a week.",
             "a1"),
        mail("Dela <letseat@dela.ie>", "Re: Dela website", "We're away", "a2", headers="Auto-Submitted: auto-replied\n"),
        mail("Mary <mary@cafeblue.ie>", "Re: Cafe Blue website on a phone",
             "Hi, yes this sounds interesting, can you call me tomorrow?\n> not interested quoted text", "r2"),
        mail("Newsletter <news@randomshop.com>", "Big sale", "unsubscribe here", "n1"),
        mail("Someone <someone@gmail.com>", "Hello", "no thanks", "n2"),
    ],
    "proposals@frontage.agency": [
        email.message_from_string("From: MAILER-DAEMON@mx.hostinger.com\nSubject: Undelivered Mail Returned to Sender\n"
                                  "Message-ID: <b2>\nDate: Sun, 01 Nov 2026 09:00:00 +0000\nMIME-Version: 1.0\n" + DSN),
        mail("Boss <owner@salonx.ie>", "Re: Salon X", "Please remove me from your list.", "r3"),
    ],
}


def fake_fetch(address, pw, since):
    yield from BOXES.get(address, [])


home = tempfile.mkdtemp()
pd.DataFrame([{"sent_at": "2026-10-28T08:00:00", "email": e, "mailbox": "hello@frontage.agency"} for e in
              ["booking@holeinthewallbar.ie", "fernroydhousebandb@gmail.com", "info@thehairspace.ie",
               "letseat@dela.ie", "info@cafeblue.ie", "gone@deadbiz.ie", "info@salonx.ie"]]
             ).to_csv(home + "/0_sent_log.csv", index=False)
open(home + "/0_do_not_contact.csv", "w").write("email_or_domain\nfernroydhousebandb@gmail.com\n")
pw = {f"{b}@frontage.agency": "x" for b in replies.BOXES}

c = replies.run(home, pw, today=TODAY, fetch=fake_fetch, log=lambda m: None)
rep = pd.read_csv(home + "/0_replies.csv", dtype=str).fillna("")
kind = dict(zip(rep.message_id, rep.kind))
check("Gmail bounce found, matched to the address we sent to",
      kind.get("<b1>") == "bounce" and "booking@holeinthewallbar.ie" in set(rep.matched_email))
check("Hostinger bounce report (Final-Recipient) found", kind.get("<b2>") == "bounce"
      and "gone@deadbiz.ie" in set(rep.matched_email))
check("'No thanks' is an opt-out (quoted original ignored)", kind.get("<r1>") == "optout")
check("'Please remove me' from another address at the same business = opt-out", kind.get("<r3>") == "optout"
      and rep.loc[rep.message_id == "<r3>", "matched_email"].iloc[0] == "info@salonx.ie")
check("auto-replies recognised (subject and header)", kind.get("<a1>") == "auto" and kind.get("<a2>") == "auto")
check("interested reply = reply, quoted 'not interested' ignored, same domain matched",
      kind.get("<r2>") == "reply")
check("unrelated mail and unknown gmail ignored", "<n1>" not in kind and "<n2>" not in kind)
dnc = open(home + "/0_do_not_contact.csv").read().split()
check("bounces + opt-outs added to do-not-contact, no duplicates",
      {"booking@holeinthewallbar.ie", "gone@deadbiz.ie", "info@salonx.ie"} <= set(dnc)
      and dnc.count("fernroydhousebandb@gmail.com") == 1)
check("interested reply NOT put on do-not-contact", "info@cafeblue.ie" not in dnc)
check("counts", c["bounce"] == 2 and c["optout"] == 2 and c["reply"] == 1 and c["auto"] == 2 and c["mailboxes_read"] == 5)

c2 = replies.run(home, pw, today=TODAY, fetch=fake_fetch, log=lambda m: None)
check("second run: nothing counted twice", sum(c2[k] for k in ("bounce", "optout", "reply", "auto")) == 0
      and len(pd.read_csv(home + "/0_replies.csv")) == len(rep))

check("2 bounces of 7 sent but under 3 bounces: no pause", not c["paused"] and not os.path.exists(home + "/0_PAUSE.txt"))
log = pd.read_csv(home + "/0_sent_log.csv", dtype=str)
extra = pd.DataFrame([{"sent_at": "2026-11-01T08:00:00", "email": f"x{i}@b{i}.ie"} for i in range(40)])
pd.concat([log, extra]).to_csv(home + "/0_sent_log.csv", index=False)
pd.DataFrame([{"seen_at": "2026-11-02", "received": "2026-11-01", "mailbox": "hello@frontage.agency",
               "message_id": f"<z{i}>", "kind": "bounce", "from": "mailer-daemon@x", "matched_email": f"x{i}@b{i}.ie",
               "subject": "x"} for i in range(2)]).to_csv(home + "/0_replies.csv", mode="a", header=False, index=False)
check("4 bounces of 47 (8.5%) in 7 days: sending paused", replies.check_bounce_brake(home, TODAY)
      and "delete this file" in open(home + "/0_PAUSE.txt").read())

def broken_fetch(address, pw, since):
    raise ConnectionError("down")
    yield
c3 = replies.run(home, pw, today=TODAY, fetch=broken_fetch, log=lambda m: None)
check("mailbox down: reported, nothing breaks", c3["mailboxes_read"] == 0)
print("\nALL REPLY TESTS PASSED")
