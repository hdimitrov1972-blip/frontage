"""Read-only check of the 5 mailboxes: can we log in by IMAP, and do they keep a copy of
incoming mail after forwarding it to Gmail? Prints counts only (public log), never content."""
import imaplib
import os
import datetime as dt

HOST = "imap.hostinger.com"
BOXES = ["hello", "performance", "proposals", "audit", "contact"]
since = (dt.date.today() - dt.timedelta(days=45)).strftime("%d-%b-%Y")
for i, name in enumerate(BOXES, 1):
    pw = os.environ.get(f"SMTP_PASSWORD_{i}", "")
    try:
        m = imaplib.IMAP4_SSL(HOST, 993, timeout=30)
        m.login(f"{name}@frontage.agency", pw)
        typ, folders = m.list()
        names = [f.decode().split(' "/" ')[-1].strip('"') for f in folders or []]
        out = []
        for folder in ("INBOX",) + tuple(n for n in names if n.upper() in ("INBOX.SPAM", "INBOX.JUNK", "SPAM", "JUNK")):
            m.select(f'"{folder}"', readonly=True)
            typ, data = m.search(None, "SINCE", since)
            out.append(f"{folder}: {len(data[0].split()) if data and data[0] else 0}")
        typ, data = m.select('"INBOX"', readonly=True)
        typ, d2 = m.search(None, "SINCE", since, "FROM", "mailer-daemon")
        out.append(f"bounces: {len(d2[0].split()) if d2 and d2[0] else 0}")
        m.logout()
        print(f"{name}@: login OK — messages in the last 45 days — " + ", ".join(out))
    except Exception as e:
        print(f"{name}@: FAILED ({type(e).__name__})")
