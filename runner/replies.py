"""Reply and bounce stopper: reads the 5 mailboxes (read-only) and keeps three lists on Drive.

- 0_replies.csv          every reply, bounce and auto-reply from a business we emailed (append-only)
- 0_do_not_contact.csv   bounced addresses and "no thanks / unsubscribe / closed" replies are added
- 0_PAUSE.txt            written when bounces pass 3% over 7 days: sending stops until it is deleted

Nothing is ever deleted or marked as read in the mailboxes. Public log: counts only.
"""
import datetime as dt
import email
import email.policy
import imaplib
import os
import re

import pandas as pd

HOST = "imap.hostinger.com"
DOMAIN = "frontage.agency"
BOXES = ["hello", "performance", "proposals", "audit", "contact"]      # SMTP_PASSWORD_1..5
LOOK_BACK_DAYS = 60
FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.ie", "yahoo.co.uk", "hotmail.com",
             "hotmail.co.uk", "outlook.com", "outlook.ie", "live.com", "live.ie", "icloud.com",
             "me.com", "aol.com", "eircom.net", "gmx.com", "protonmail.com", "msn.com"}
OPT_OUT = re.compile(r"\b(unsubscribe|remove (me|us)|take (me|us) off|stop (emailing|contacting|sending)"
                     r"|do not (contact|email)|don'?t (contact|email)|not interested|no,? thanks?|no thank you"
                     r"|(permanently )?closed( down)?|ceased trading|no longer (trading|in business))\b", re.I)
AUTO_SUBJECT = re.compile(r"(auto(matic)?[ -]?(reply|response)|out of (the )?office|away from|"
                          r"thank(s| you) for (your (email|message|enquiry)|contacting)|we (have )?received)", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
REPLY_COLS = ["seen_at", "received", "mailbox", "message_id", "kind", "from", "matched_email", "subject"]
BOUNCE_LIMIT = 0.03
BOUNCE_MIN = 3
BOUNCE_WINDOW_DAYS = 7


def _read(path):
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()


def _text(msg, limit=20000):
    out = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        ctype = part.get_content_type()
        if ctype == "message/delivery-status":           # parsed as header blocks, not bytes
            payload = part.get_payload()
            out.append("\n".join(str(p) for p in payload) if isinstance(payload, list) else str(payload))
        elif ctype in ("text/plain", "text/html", "text/rfc822-headers"):
            try:
                payload = part.get_payload(decode=True) or b""
                out.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
            except Exception:
                pass
        elif ctype == "message/rfc822":
            out.append(str(part))
    return "\n".join(out)[:limit]


def _first_lines(text, n=6):
    """The reply itself, not the quoted original email underneath."""
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(">") or re.match(r"^On .{5,80} wrote:?$", s) or s.startswith("-----Original"):
            break
        if s:
            lines.append(s)
        if len(lines) >= n:
            break
    return " ".join(lines)


def classify(msg, sent_emails, sent_domains):
    """Returns (kind, matched_email) or (None, None) for mail that has nothing to do with our sends.
    kind: bounce | optout | reply | auto"""
    sender = email.utils.parseaddr(str(msg.get("From", "")))[1].lower()
    subject = str(msg.get("Subject", ""))
    text = _text(msg)
    is_bounce = (sender.split("@")[0] in ("mailer-daemon", "postmaster")
                 or msg.get_content_type() == "multipart/report"
                 or re.search(r"(undeliver|delivery (status|failure)|returned mail|failure notice)", subject, re.I))
    if is_bounce:
        found = [m.group(1).lower() for m in re.finditer(r"(?:Final|Original)-Recipient:\s*rfc822;\s*<?([^\s>]+)", text, re.I)]
        found += [e.lower() for e in EMAIL_RE.findall(text)]
        hit = next((e for e in found if e in sent_emails), None)
        return ("bounce", hit) if hit else (None, None)
    if sender.endswith("@" + DOMAIN):
        return None, None
    dom = sender.split("@")[-1]
    if sender in sent_emails:
        matched = sender
    elif dom not in FREE_MAIL and dom in sent_domains:
        matched = sent_domains[dom]
    else:
        return None, None
    auto = (str(msg.get("Auto-Submitted", "no")).lower() not in ("", "no")
            or msg.get("X-Autoreply") or msg.get("X-Autorespond")
            or str(msg.get("Precedence", "")).lower() in ("auto_reply", "bulk", "junk")
            or AUTO_SUBJECT.search(subject))
    if auto:
        return "auto", matched
    if OPT_OUT.search(subject) or OPT_OUT.search(_first_lines(text)):
        return "optout", matched
    return "reply", matched


def fetch_messages(address, password, since):
    """Yields parsed messages from INBOX (and Spam, if any), read-only."""
    m = imaplib.IMAP4_SSL(HOST, 993, timeout=60)
    m.login(address, password)
    try:
        typ, folders = m.list()
        names = []
        for f in folders or []:            # e.g. (\HasNoChildren) "." "INBOX.Spam"
            hit = re.match(r'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$', f.decode(errors="replace"))
            if hit:
                names.append(hit.group("name").strip().strip('"'))
        wanted = ["INBOX"] + [n for n in names if re.search(r"spam|junk", n, re.I)]
        for folder in wanted:
            try:
                if m.select(f'"{folder}"', readonly=True)[0] != "OK":
                    continue
                typ, data = m.search(None, "SINCE", since.strftime("%d-%b-%Y"))
            except imaplib.IMAP4.error:
                continue                   # a folder that can't be opened is skipped, not fatal
            for num in (data[0].split() if data and data[0] else []):
                typ, parts = m.fetch(num, "(BODY.PEEK[])")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                if raw:
                    yield email.message_from_bytes(raw, policy=email.policy.compat32)
    finally:
        try:
            m.logout()
        except Exception:
            pass


def run(home, passwords, today=None, fetch=None, log=print):
    """passwords: {"hello@frontage.agency": "...", ...}. Returns a dict of counts."""
    today = today or dt.date.today()
    fetch = fetch or fetch_messages
    sent = _read(os.path.join(home, "0_sent_log.csv"))
    sent_emails = set(sent.get("email", pd.Series(dtype=str)).str.strip().str.lower()) - {""}
    sent_domains = {}
    for e in sorted(sent_emails):
        d = e.split("@")[-1]
        if d not in FREE_MAIL:
            sent_domains.setdefault(d, e)

    rpath = os.path.join(home, "0_replies.csv")
    old = _read(rpath)
    seen = set(old.get("message_id", pd.Series(dtype=str)))
    new_rows, counts = [], {"bounce": 0, "optout": 0, "reply": 0, "auto": 0, "mailboxes_read": 0}
    since = today - dt.timedelta(days=LOOK_BACK_DAYS)
    for address, pw in passwords.items():
        if not pw:
            continue
        try:
            for msg in fetch(address, pw, since):
                mid = str(msg.get("Message-ID", "")).strip() or f"{address}|{msg.get('Date')}|{msg.get('From')}"
                if mid in seen:
                    continue
                kind, matched = classify(msg, sent_emails, sent_domains)
                if not kind:
                    continue
                seen.add(mid)
                counts[kind] += 1
                try:
                    received = email.utils.parsedate_to_datetime(msg.get("Date")).date().isoformat()
                except Exception:
                    received = today.isoformat()
                new_rows.append({"seen_at": today.isoformat(), "received": received, "mailbox": address,
                                 "message_id": mid, "kind": kind,
                                 "from": email.utils.parseaddr(str(msg.get("From", "")))[1].lower(),
                                 "matched_email": matched, "subject": str(msg.get("Subject", ""))[:150]})
            counts["mailboxes_read"] += 1
        except Exception as e:
            log(f"[replies] {address.split('@')[0]}@ could not be read ({type(e).__name__}: {str(e)[:150]})")

    if new_rows:
        pd.DataFrame(new_rows)[REPLY_COLS].to_csv(rpath, mode="a", header=not os.path.exists(rpath), index=False)

    # bounced and "no thanks" addresses go on the permanent do-not-contact list
    dnc_path = os.path.join(home, "0_do_not_contact.csv")
    have = set()
    if os.path.exists(dnc_path):
        have = {l.strip().lower() for l in open(dnc_path, encoding="utf-8") if "@" in l}
    else:
        open(dnc_path, "w").write("email_or_domain\n")
    add = sorted({r["matched_email"] for r in new_rows if r["kind"] in ("bounce", "optout")} - have)
    if add:
        with open(dnc_path, "a", encoding="utf-8") as f:
            for a in add:
                f.write(a + "\n")
    counts["added_to_do_not_contact"] = len(add)
    counts["paused"] = check_bounce_brake(home, today)
    return counts


def check_bounce_brake(home, today):
    """Pause all sending when bounces over the last 7 days pass 3% (and at least 3 bounces)."""
    pause = os.path.join(home, "0_PAUSE.txt")
    if os.path.exists(pause):
        return True
    start = (today - dt.timedelta(days=BOUNCE_WINDOW_DAYS)).isoformat()
    sent = _read(os.path.join(home, "0_sent_log.csv"))
    rep = _read(os.path.join(home, "0_replies.csv"))
    n_sent = int((sent.get("sent_at", pd.Series(dtype=str)).str[:10] >= start).sum()) if len(sent) else 0
    n_bounce = int(((rep.get("kind", pd.Series(dtype=str)) == "bounce")
                    & (rep.get("received", pd.Series(dtype=str)) >= start)).sum()) if len(rep) else 0
    if n_sent and n_bounce >= BOUNCE_MIN and n_bounce / n_sent > BOUNCE_LIMIT:
        with open(pause, "w", encoding="utf-8") as f:
            f.write(f"Sending paused on {today.isoformat()}: {n_bounce} bounces from {n_sent} emails in "
                    f"the last {BOUNCE_WINDOW_DAYS} days ({n_bounce / n_sent:.1%}, limit {BOUNCE_LIMIT:.0%}).\n"
                    f"Check the bounced addresses in 0_replies.csv, then delete this file to send again.\n")
        return True
    return False
