"""Weekend follow-up: one short email, no PDF, to businesses that got the first email 14+ days ago
and never answered. Sent as a reply in the same conversation, from the same mailbox.

Never to: anyone who replied (any human reply), bounced, said no / unsubscribe, is on do-not-contact,
or already had a follow-up. One follow-up per business, ever.

The text lives on Drive (private): followup_text_A.txt, followup_text_B.txt, ... (first line
"Subject: ..." is ignored: the subject is always "Re: <first email's subject>"). With several
texts, businesses take turns, so the replies show which text works. Placeholders: {name}.
"""
import datetime as dt
import glob
import os
import random
import smtplib
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import pandas as pd

SMTP_HOST, SMTP_PORT = "smtp.hostinger.com", 465
FROM_NAME = "Frontage Agency"
REPLY_TO = "hello@frontage.agency"
BOXES = ["hello", "performance", "proposals", "audit", "contact"]       # SMTP_PASSWORD_1..5
WAIT_DAYS = 14
DAILY_MAX = 30            # follow-ups per day for the whole domain
PER_MAILBOX_MAX = 20      # per mailbox per day (old contacts were all sent from hello@)
MIN_DELAY, MAX_DELAY = 60, 180
LOG_COLS = ["sent_at", "place_id", "email", "name", "mailbox", "first_sent_at", "variant", "message_id"]
FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.ie", "hotmail.com", "outlook.com", "outlook.ie",
             "live.com", "live.ie", "icloud.com", "me.com", "aol.com", "eircom.net"}


def _read(path):
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()


def load_texts(home):
    texts = {}
    for p in sorted(glob.glob(os.path.join(home, "followup_text_*.txt"))):
        variant = os.path.basename(p)[len("followup_text_"):-4]
        body = open(p, encoding="utf-8").read().strip()
        lines = body.splitlines()
        if lines and lines[0].lower().startswith("subject:"):
            body = "\n".join(lines[1:]).strip()
        if body:
            texts[variant] = body
    return texts


def blocked_addresses(home):
    dnc = set()
    p = os.path.join(home, "0_do_not_contact.csv")
    if os.path.exists(p):
        dnc = {l.strip().lower() for l in open(p, encoding="utf-8") if "@" in l}
    rep = _read(os.path.join(home, "0_replies.csv"))
    answered = set()
    if len(rep):
        answered = set(rep.loc[rep["kind"].isin(["reply", "optout", "bounce"]), "matched_email"].str.lower())
    return dnc, answered


def candidates(home, today):
    """First emails sent WAIT_DAYS+ days ago, still waiting for a follow-up. Newest first."""
    sent = _read(os.path.join(home, "0_sent_log.csv"))
    if sent.empty:
        return sent
    sent["email"] = sent["email"].str.strip().str.lower()
    sent = sent[sent["email"].str.contains("@")]
    sent["day"] = sent["sent_at"].str[:10]
    sent = sent[sent["day"] <= (today - dt.timedelta(days=WAIT_DAYS)).isoformat()]
    sent = sent.sort_values("sent_at").drop_duplicates("email", keep="first")     # the first email only
    dnc, answered = blocked_addresses(home)
    done = set(_read(os.path.join(home, "0_followup_log.csv")).get("email", pd.Series(dtype=str)).str.lower())
    dom = "@" + sent["email"].str.split("@").str[-1]
    ok = (~sent["email"].isin(dnc) & ~dom.isin(dnc) & ~sent["email"].isin(answered) & ~sent["email"].isin(done))
    # a reply from another address at the same business also counts as answered
    answered_domains = {"@" + a.split("@")[-1] for a in answered if a.split("@")[-1] not in FREE_MAIL}
    ok &= ~dom.isin(answered_domains)
    return sent[ok].sort_values("sent_at", ascending=False)


def build(row, body, mailbox):
    msg = EmailMessage()
    subject = str(row.get("subject", "")).strip()
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg["From"] = formataddr((FROM_NAME, mailbox))
    msg["To"] = row["email"]
    msg["Reply-To"] = REPLY_TO
    msg["List-Unsubscribe"] = f"<mailto:{REPLY_TO}?subject=unsubscribe>"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=mailbox.split("@")[-1])
    first_id = str(row.get("message_id", "")).strip()
    if first_id:
        msg["In-Reply-To"] = first_id
        msg["References"] = first_id
    name = str(row.get("name", "")).strip()
    msg.set_content(body.replace("{name}", name or "there"))
    return msg


def run(home, passwords, today=None, test_to=None, log=print, sleep=time.sleep, smtp=smtplib.SMTP_SSL):
    """passwords: {"hello@frontage.agency": "..."}. test_to: send one per mailbox ONLY to this address."""
    today = today or dt.date.today()
    counts = {"candidates": 0, "sent": 0, "failed": 0, "per_variant": {}}
    if os.path.exists(os.path.join(home, "0_PAUSE.txt")) and not test_to:
        log("[follow-up] paused (0_PAUSE.txt on Drive)")
        return counts
    texts = load_texts(home)
    if not texts:
        log("[follow-up] no followup_text_*.txt on Drive yet — nothing sent")
        return counts
    cand = candidates(home, today)
    counts["candidates"] = len(cand)
    plan, per_box = [], {}
    already = _read(os.path.join(home, "0_followup_log.csv"))
    today_rows = already[already["sent_at"].str[:10] == today.isoformat()] if len(already) else already
    if not test_to and len(today_rows):          # a later run on the same day only tops up to the limits
        per_box = today_rows["mailbox"].value_counts().to_dict()
    room = len(passwords) if test_to else max(DAILY_MAX - len(today_rows), 0)
    variants = sorted(texts)
    if test_to:                                 # test: every mailbox sends one, with a real business's details
        plan = [(cand.iloc[0], box) for box, pw in passwords.items() if pw] if len(cand) else []
        cand = cand.iloc[0:0]
    for _, r in cand.iterrows():
        box = r.get("mailbox") or "hello@frontage.agency"
        if box not in passwords or not passwords[box]:
            continue
        if test_to:
            if box in per_box:
                continue
        elif per_box.get(box, 0) >= PER_MAILBOX_MAX:
            continue
        if len(plan) >= room:
            break
        per_box[box] = per_box.get(box, 0) + 1
        plan.append((r, box))
    logpath = os.path.join(home, "0_followup_log.csv")
    done_before = len(_read(logpath))
    servers = {}
    try:
        for i, (r, box) in enumerate(plan):
            variant = variants[(done_before + i) % len(variants)]
            msg = build(r, texts[variant], box)
            to = test_to or r["email"]
            if test_to:
                del msg["To"]
                msg["To"] = test_to
            try:
                if box not in servers:
                    servers[box] = smtp(SMTP_HOST, SMTP_PORT, timeout=30)
                    servers[box].login(box, passwords[box])
                servers[box].send_message(msg, to_addrs=[to])
            except Exception as e:
                counts["failed"] += 1
                log(f"[follow-up] {box.split('@')[0]}@ failed ({type(e).__name__})")
                servers.pop(box, None)
                continue
            counts["sent"] += 1
            counts["per_variant"][variant] = counts["per_variant"].get(variant, 0) + 1
            if not test_to:
                pd.DataFrame([{"sent_at": f"{today.isoformat()}T{dt.datetime.now().strftime('%H:%M:%S')}",
                               "place_id": r.get("place_id", ""), "email": r["email"], "name": r.get("name", ""),
                               "mailbox": box, "first_sent_at": r["sent_at"], "variant": variant,
                               "message_id": msg["Message-ID"]}])[LOG_COLS].to_csv(
                    logpath, mode="a", header=not os.path.exists(logpath), index=False)
            if i < len(plan) - 1 and not test_to:
                sleep(random.randint(MIN_DELAY, MAX_DELAY))
    finally:
        for s in servers.values():
            try:
                s.quit()
            except Exception:
                pass
    return counts
