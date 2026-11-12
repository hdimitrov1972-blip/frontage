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
from urllib.parse import unquote

import pandas as pd

HOST = "imap.hostinger.com"
DOMAIN = "frontage.agency"
BOXES = ["hello", "performance", "proposals", "audit", "contact"]      # SMTP_PASSWORD_1..5
LOOK_BACK_DAYS = 60
FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.ie", "yahoo.co.uk", "hotmail.com",
             "hotmail.co.uk", "outlook.com", "outlook.ie", "live.com", "live.ie", "icloud.com",
             "me.com", "aol.com", "eircom.net", "gmx.com", "protonmail.com", "msn.com", "hotmail.ie",
             "live.co.uk", "rocketmail.com", "ymail.com", "mail.com", "proton.me", "icloud.ie"}
OPT_OUT = re.compile(r"\b(unsubscribe|remove (me|us)|take (me|us) off|stop (emailing|contacting|sending)"
                     r"|do not (contact|email)|don'?t (contact|email)|not interested|no[,.!]?\s*thanks?|no thank you"
                     r"|permanently closed|closed (down|for good|permanently)|(we'?ve|we have|we are|we're) (now )?closed(?=\s*([.!,]|$|now\b|down\b|for good\b|permanently\b))"
                     r"|ceased trading|no longer (trading|in business)"
                     r"|(take|remove|delete) (my|our|this) (e-?mail|address|details)( address)? (off|from)"
                     r"|(off|from) (your|the) (mailing |e-?mail )?list)\b", re.I)
AUTO_SUBJECT = re.compile(r"(auto(matic)?[ -]?(reply|response)|out of (the )?office|away from|"
                          r"thank(s| you) for (your (email|message|enquiry)|contacting)|we (have )?received)", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
REPLY_COLS = ["seen_at", "received", "mailbox", "message_id", "kind", "from", "matched_email", "subject", "first_lines"]
BOUNCE_LIMIT = 0.03
BOUNCE_MIN = 3
BOUNCE_WINDOW_DAYS = 7


def clean_address(raw):
    """Same cleaning as the sender: 'mailto%20info@x.ie' or 'u003einfo@x.ie' -> 'info@x.ie'."""
    a = unquote(str(raw or "")).strip().strip("<>\"' ").lower()
    for junk in ("mailto:", "mailto"):
        if a.startswith(junk):
            a = a[len(junk):].strip()
    return re.sub(r"^(u003e|u003c|\\u003e|\\u003c)+", "", a).strip()


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


REF = re.compile(r"\(ref ([0-9A-F]{6})\)")


def ref_of(place_id):
    """The code the sender puts in the button replies (same formula as the sender notebook)."""
    import hashlib
    return hashlib.md5(str(place_id).encode("utf-8")).hexdigest()[:6].upper()


def owner_addresses():
    """Anzhel's own addresses (TEST_EMAIL secret, comma separated). His test button presses and anything
    else he sends to the mailboxes are never counted as a business's reply."""
    return {a.strip().lower() for a in os.environ.get("TEST_EMAIL", "").split(",") if "@" in a}


def classify(msg, sent_emails, sent_domains, thread=None, refs=None, ignore=()):
    """Returns (kind, matched_email) or (None, None) for mail that has nothing to do with our sends.
    kind: bounce | optout | reply | auto"""
    sender = email.utils.parseaddr(str(msg.get("From", "")))[1].lower()
    if sender in ignore:
        return None, None                      # Anzhel's own test or note, not a business
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
    elif refs and REF.search(subject) and REF.search(subject).group(1) in refs:
        matched = refs[REF.search(subject).group(1)]          # a button reply sent from another address
    elif thread and any(t in thread for t in re.findall(r"<[^>]+>", f"{msg.get('In-Reply-To', '')} {msg.get('References', '')}")):
        # an answer to one of our emails, sent from another address (e.g. the owner's own Gmail)
        matched = next(thread[t] for t in re.findall(r"<[^>]+>", f"{msg.get('In-Reply-To', '')} "
                                                                  f"{msg.get('References', '')}") if t in thread)
    else:
        return None, None
    first = _first_lines(text)
    if (OPT_OUT.search(subject) or OPT_OUT.search(first)
            or re.fullmatch(r"\W*(stop|remove|unsubscribe|no)\W*", first.split(" ")[0] if len(first.split()) <= 2 else "", re.I)):
        return "optout", matched              # a refusal counts even when a machine sent it
    auto = (str(msg.get("Auto-Submitted", "no")).lower() not in ("", "no")
            or msg.get("X-Autoreply") or msg.get("X-Autorespond")
            or str(msg.get("Precedence", "")).lower() in ("auto_reply", "bulk", "junk")
            or AUTO_SUBJECT.search(subject))
    if auto:
        return "auto", matched
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


def purge_own(home, owners, log=print):
    """Removes Anzhel's own test presses recorded before 12 Nov 2026 (when they still counted as a business's
    answer), and undoes what they caused: the do-not-contact entry and the 'already answered' mark.
    A business stays on do-not-contact if it really said no or bounced. Does nothing once clean."""
    if not owners:
        return 0
    rpath = os.path.join(home, "0_replies.csv")
    rep = _read(rpath)
    if rep.empty or "from" not in rep.columns:
        return 0
    own = rep["from"].str.lower().isin(owners)
    if not own.any():
        return 0
    touched = set(rep.loc[own, "matched_email"].str.lower()) - {""}
    rest = rep[~own]
    rest.to_csv(rpath, index=False)
    still = set()
    for _, r in rest.iterrows():
        if r.get("kind") in ("bounce", "optout") or (r.get("kind") == "reply" and OPT_OUT.search(str(r.get("first_lines", "")))):
            still |= {str(r["matched_email"]).lower(), clean_address(r["matched_email"])}
    dnc_path = os.path.join(home, "0_do_not_contact.csv")
    freed = touched - still
    if freed and os.path.exists(dnc_path):
        lines = [l.rstrip("\n") for l in open(dnc_path, encoding="utf-8")]
        keep = [l for l in lines if l.strip().lower() not in freed]
        if len(keep) != len(lines):
            open(dnc_path, "w", encoding="utf-8").write("\n".join(keep) + "\n")
    fpath = os.path.join(home, "0_fix_replies.csv")
    fx = _read(fpath)
    if len(fx) and "to" in fx.columns:
        fx[~fx["to"].str.lower().isin(owners)].to_csv(fpath, index=False)
    log(f"[replies] removed {int(own.sum())} of your own test presses from the records "
        f"(do-not-contact freed: {len(freed)})")
    return int(own.sum())


def run(home, passwords, today=None, fetch=None, log=print, ignore=None):
    """passwords: {"hello@frontage.agency": "...", ...}. Returns a dict of counts."""
    today = today or dt.date.today()
    ignore = owner_addresses() if ignore is None else {a.lower() for a in ignore}
    try:
        purge_own(home, ignore, log=log)
    except Exception as e:
        log(f"[replies] clean-up of own test presses skipped ({type(e).__name__})")
    fetch = fetch or fetch_messages
    sent = _read(os.path.join(home, "0_sent_log.csv"))
    sent_emails = set(sent.get("email", pd.Series(dtype=str)).str.strip().str.lower()) - {""}
    sent_domains = {}
    for e in sorted(sent_emails):
        d = e.split("@")[-1]
        if d not in FREE_MAIL:
            sent_domains.setdefault(d, e)
    forms = _read(os.path.join(home, "0_contact_forms_sent.csv"))          # contacted through their contact form:
    for d in forms.get("domain", pd.Series(dtype=str)).str.strip().str.lower():  # their replies match by domain
        if d and d not in FREE_MAIL:
            sent_domains.setdefault(d, "@" + d)

    thread = {}                                   # our Message-IDs -> the address we wrote to
    for name in ("0_sent_log.csv", "0_followup_log.csv"):
        log_ = _read(os.path.join(home, name))
        if len(log_) and "message_id" in log_.columns and "email" in log_.columns:
            for mid_, e in zip(log_["message_id"].str.strip(), log_["email"].str.strip().str.lower()):
                if mid_.startswith("<") and e:
                    thread[mid_] = e

    refs = {}                                     # button reference code -> the address we wrote to
    sl = _read(os.path.join(home, "0_sent_log.csv"))
    if len(sl) and "place_id" in sl.columns:
        for pid, e in zip(sl["place_id"], sl["email"].str.strip().str.lower()):
            if pid and e:
                refs[ref_of(pid)] = e

    rpath = os.path.join(home, "0_replies.csv")
    old = _read(rpath)
    if len(old) and any(c not in old.columns for c in REPLY_COLS):     # older file: add the new columns once
        for c in REPLY_COLS:
            if c not in old.columns:
                old[c] = ""
        old[REPLY_COLS].to_csv(rpath, index=False)
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
                kind, matched = classify(msg, sent_emails, sent_domains, thread, refs, ignore)
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
                                 "matched_email": matched, "subject": str(msg.get("Subject", ""))[:150],
                                 "first_lines": _first_lines(_text(msg))[:300] if kind != "bounce" else ""})
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
    every = pd.concat([_read(rpath), pd.DataFrame(new_rows)], ignore_index=True) if new_rows else _read(rpath)
    stop = set()
    for _, r in every.iterrows():
        if str(r.get("from", "")).lower() in ignore:
            continue                                                   # Anzhel's own test presses
        refusal = r.get("kind") in ("bounce", "optout") or (               # also older replies the
            r.get("kind") == "reply" and OPT_OUT.search(str(r.get("first_lines", ""))))  # first version missed
        if refusal and "@" in str(r.get("matched_email", "")):
            stop |= {str(r["matched_email"]).lower(), clean_address(r["matched_email"])}
    add = sorted({a for a in stop if "@" in a} - have)
    if add:
        with open(dnc_path, "a", encoding="utf-8") as f:
            for a in add:
                f.write(a + "\n")
    counts["added_to_do_not_contact"] = len(add)
    counts["paused"] = check_bounce_brake(home, today)
    return counts


def _pause_days(home):
    """Every day the brake stopped sending (0_pause_history.csv, plus the open 0_PAUSE.txt)."""
    days = set(_read(os.path.join(home, "0_pause_history.csv")).get("paused_on", pd.Series(dtype=str)))
    try:
        m = re.search(r"paused on (\d{4}-\d{2}-\d{2})", open(os.path.join(home, "0_PAUSE.txt"), encoding="utf-8").read())
        if m:
            days.add(m.group(1))
    except OSError:
        pass
    return sorted(d for d in days if d)


def _remember_pause(home, day):
    path = os.path.join(home, "0_pause_history.csv")
    have = set(_read(path).get("paused_on", pd.Series(dtype=str)))
    if day not in have:
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(("paused_on\n" if new else "") + day + "\n")


def check_bounce_brake(home, today):
    """Pause all sending when bounces pass 3% (and at least 3 bounces) over the last 7 days.
    First emails and follow-ups both count. After a pause is lifted the brake starts fresh: sends and
    bounces up to the pause day are not counted again (those addresses are already on do-not-contact)."""
    pause = os.path.join(home, "0_PAUSE.txt")
    if os.path.exists(pause):
        for d in _pause_days(home):
            _remember_pause(home, d)
        return True
    start = (today - dt.timedelta(days=BOUNCE_WINDOW_DAYS)).isoformat()
    paused = _pause_days(home)
    if paused:
        after_pause = (dt.date.fromisoformat(paused[-1]) + dt.timedelta(days=1)).isoformat()
        start = max(start, after_pause)
    n_sent = 0
    for name in ("0_sent_log.csv", "0_followup_log.csv"):
        log = _read(os.path.join(home, name))
        if len(log) and "sent_at" in log:
            n_sent += int((log["sent_at"].str[:10] >= start).sum())
    rep = _read(os.path.join(home, "0_replies.csv"))
    n_bounce = int(((rep.get("kind", pd.Series(dtype=str)) == "bounce")
                    & (rep.get("received", pd.Series(dtype=str)) >= start)).sum()) if len(rep) else 0
    if n_sent and n_bounce >= BOUNCE_MIN and n_bounce / n_sent > BOUNCE_LIMIT:
        with open(pause, "w", encoding="utf-8") as f:
            f.write(f"Sending paused on {today.isoformat()}: {n_bounce} bounces from {n_sent} emails in "
                    f"the last {BOUNCE_WINDOW_DAYS} days ({n_bounce / n_sent:.1%}, limit {BOUNCE_LIMIT:.0%}).\n"
                    f"Check the bounced addresses in 0_replies.csv, then delete this file to send again.\n")
        _remember_pause(home, today.isoformat())
        return True
    return False
