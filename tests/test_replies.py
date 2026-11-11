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
home2 = tempfile.mkdtemp()
pd.DataFrame([{"sent_at": "2026-10-07T08:00:00", "email": e} for e in
              ["u003emtfgalway@gmail.com", "euchariahannon@gmail.com"]]).to_csv(home2 + "/0_sent_log.csv", index=False)
BOX2 = {"hello@frontage.agency": [
    mail("MAILER-DAEMON <mailer-daemon@relay.net>", "Undelivered Mail Returned to Sender",
         "<u003emtfgalway@gmail.com>: host said: 550 no such user", "j1"),
    mail("E <euchariahannon@gmail.com>", "unsubscribe", "", "j2", headers="Auto-Submitted: auto-generated\n")]}
replies.run(home2, pw, today=TODAY, fetch=lambda a, p, s: iter(BOX2.get(a, [])), log=lambda m: None)
d2 = open(home2 + "/0_do_not_contact.csv").read().split()
check("junk-spelled bounce: the clean address is blocked too", "mtfgalway@gmail.com" in d2)
check("'unsubscribe' from an automatic sender still counts as opt-out", "euchariahannon@gmail.com" in d2)
home3 = tempfile.mkdtemp()
pd.DataFrame([{"sent_at": "2026-11-01T08:00:00", "email": "info@shop.ie"}]).to_csv(home3 + "/0_sent_log.csv", index=False)
BOX3 = {"hello@frontage.agency": [mail("Shop <info@shop.ie>", "Re: Shop website", "STOP\n\n> Reply stop and I won't", "s1")]}
replies.run(home3, pw, today=TODAY, fetch=lambda a, p, s: iter(BOX3.get(a, [])), log=lambda m: None)
check("a one-word 'STOP' reply = opt-out", "info@shop.ie" in open(home3 + "/0_do_not_contact.csv").read())

# "No. Thanks" (with a full stop) is a no, and an older row filed as "reply" is fixed on the next run
home4 = tempfile.mkdtemp()
pd.DataFrame([{"sent_at": "2026-10-31T15:36:34", "email": "saborbraziil@gmail.com"}]).to_csv(
    home4 + "/0_sent_log.csv", index=False)
pd.DataFrame([{"seen_at": "2026-11-04", "received": "2026-11-04", "mailbox": "hello@frontage.agency",
               "message_id": "<old>", "kind": "reply", "from": "saborbraziil@gmail.com",
               "matched_email": "saborbraziil@gmail.com", "subject": "Re: Sabor Braziil website",
               "first_lines": "No. Thanks Leonardo Lemos CEO Sabor Braziil"}]).to_csv(home4 + "/0_replies.csv", index=False)
BOX4 = {"hello@frontage.agency": [mail("X <info@nothanks.ie>", "Re: X website", "No. Thanks\n\n> Hi X team", "nt1")]}
pd.DataFrame([{"sent_at": "2026-10-31T15:36:34", "email": e} for e in
              ["saborbraziil@gmail.com", "info@nothanks.ie"]]).to_csv(home4 + "/0_sent_log.csv", index=False)
c4 = replies.run(home4, pw, today=TODAY, fetch=lambda a, p, s: iter(BOX4.get(a, [])), log=lambda m: None)
d4 = open(home4 + "/0_do_not_contact.csv").read().split()
check("'No. Thanks' = opt-out", c4["optout"] == 1 and "info@nothanks.ie" in d4)
check("older 'No. Thanks' filed as reply is put on do-not-contact", "saborbraziil@gmail.com" in d4)
check("interested reply still never blocked (re-check)", "info@cafeblue.ie" not in open(home + "/0_do_not_contact.csv").read())

# Brake: after a pause is lifted it starts fresh; follow-ups count as sends
home5 = tempfile.mkdtemp()
D = dt.date(2026, 11, 6)
sent = [{"sent_at": "2026-10-30T09:00:00", "email": f"a{i}@a.ie"} for i in range(30)] + \
       [{"sent_at": "2026-11-02T09:00:00", "email": f"b{i}@b.ie"} for i in range(27)]
pd.DataFrame(sent).to_csv(home5 + "/0_sent_log.csv", index=False)
pd.DataFrame([{"seen_at": r, "received": r, "kind": "bounce", "matched_email": f"z{i}@z.ie", "message_id": f"<{i}>"}
              for i, r in enumerate(["2026-10-30", "2026-11-02", "2026-11-02"])]).to_csv(home5 + "/0_replies.csv", index=False)
open(home5 + "/0_PAUSE.txt", "w").write("Sending paused on 2026-11-02: 4 bounces from 117 emails\n")
check("pause file present: still paused, pause day remembered",
      replies.check_bounce_brake(home5, D) and "2026-11-02" in open(home5 + "/0_pause_history.csv").read())
os.remove(home5 + "/0_PAUSE.txt")
check("pause lifted: old bounces (3 of 57) not counted again -> sending allowed",
      not replies.check_bounce_brake(home5, D) and not os.path.exists(home5 + "/0_PAUSE.txt"))
pd.DataFrame([{"sent_at": "2026-11-09T09:00:00", "email": f"c{i}@c.ie"} for i in range(20)]).to_csv(
    home5 + "/0_sent_log.csv", mode="a", header=False, index=False)
pd.DataFrame([{"seen_at": "2026-11-09", "received": "2026-11-09", "kind": "bounce", "matched_email": "c1@c.ie",
               "message_id": "<n1>"}]).to_csv(home5 + "/0_replies.csv", mode="a", header=False, index=False)
check("after resume: 1 new bounce of 20 -> no pause (under 3 bounces)", not replies.check_bounce_brake(home5, dt.date(2026, 11, 9)))
pd.DataFrame([{"seen_at": "2026-11-10", "received": "2026-11-10", "kind": "bounce", "matched_email": f"c{i}@c.ie",
               "message_id": f"<n{i}>"} for i in (2, 3)]).to_csv(home5 + "/0_replies.csv", mode="a", header=False, index=False)
pd.DataFrame([{"sent_at": "2026-11-10T09:00:00", "email": f"d{i}@d.ie"} for i in range(30)]).to_csv(
    home5 + "/0_followup_log.csv", index=False)
check("after resume: 3 new bounces of 50 (20 first + 30 follow-ups) = 6% -> paused again",
      replies.check_bounce_brake(home5, dt.date(2026, 11, 10)) and "from 50 emails" in open(home5 + "/0_PAUSE.txt").read())

# Reviewer's cases (11 Nov): a yes that mentions opening days is not an opt-out; "off your list" is not a yes
import fixreply  # noqa: E402
check("'Yes please, we are closed Mondays' is not an opt-out", not replies.OPT_OUT.search("Yes please, we are closed Mondays but call me")
      and fixreply.is_yes("Yes please, we are closed Mondays but call me"))
check("'Please take my email off your list' is an opt-out, not a yes",
      replies.OPT_OUT.search("Please take my email off your list") and not fixreply.is_yes("Please take my email off your list"))
check("'We have closed down' is still an opt-out", replies.OPT_OUT.search("We have closed down"))
print("\nALL REPLY TESTS PASSED")
