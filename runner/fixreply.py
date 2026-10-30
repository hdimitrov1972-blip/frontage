"""When a business answers "yes" to the follow-up offer, prepare its personal "3 fixes" reply.

- Their own speed test (lighthouse_json/<place_id>.json) gives their 3 biggest problems and numbers.
- Plain steps come from fix_guide.json on Drive (private).
- The reply is put in hello@'s Drafts, addressed and threaded, ready to send with one tap,
  and you get an email with the same text. Nothing is sent to the business by the machine.
"""
import datetime as dt
import email.utils
import imaplib
import json
import os
import re
import smtplib
import subprocess
import time
from collections import defaultdict
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import pandas as pd

HELLO = "hello@frontage.agency"
FROM_NAME = "Frontage Agency"
YES = re.compile(r"^\W*(yes|yeah|yep|yup|sure|please( do| send)?|ok(ay)?|go (ahead|for it)|sounds (good|great)|"
                 r"that would be (great|good|lovely|helpful)|i'?d (like|love) (that|them|it)|send (them|it|me)|"
                 r"interested|why not|absolutely|definitely|thanks?,? (yes|please))\b", re.I)
LOG_COLS = ["created_at", "reply_message_id", "place_id", "name", "to", "status"]


def _read(path):
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()


def safe_id(place_id):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(place_id).strip())[:80]


def load_audit(home, place_id):
    path = os.path.join(home, "lighthouse_json", f"{safe_id(place_id)}.json")
    if not os.path.exists(path) and os.environ.get("FRONTAGE_RCLONE"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.call(["rclone", "copyto", f"gdrive:Frontage/lighthouse_json/{os.path.basename(path)}", path,
                         "--quiet"], timeout=120)
    try:
        d = json.load(open(path, encoding="utf-8"))
        return d.get("lighthouseResult", d).get("audits", {})
    except Exception:
        return None


def _saving_ms(a):
    s = a.get("metricSavings") or {}
    det = a.get("details") or {}
    return max([v for v in (s.get("LCP"), s.get("FCP"), det.get("overallSavingsMs")) if isinstance(v, (int, float))] or [0])


def _items(a):
    return len((a.get("details") or {}).get("items") or [])


def numbers(audits):
    g = lambda k: audits.get(k) or {}          # noqa: E731
    v = {}
    if isinstance(g("largest-contentful-paint").get("numericValue"), (int, float)):
        v["lcp_s"] = f"{g('largest-contentful-paint')['numericValue'] / 1000:.1f}"
    if isinstance(g("total-byte-weight").get("numericValue"), (int, float)):
        v["page_mb"] = f"{g('total-byte-weight')['numericValue'] / 1e6:.1f}"
    m = re.search(r"([\d.,]+)\s*(KiB|MiB)", str(g("image-delivery-insight").get("displayValue", "")).replace("\xa0", " "))
    if m and float(m.group(1).replace(",", "")) > 0:
        kb = float(m.group(1).replace(",", "")) * (1024 if m.group(2) == "MiB" else 1)
        v["image_saving_sentence"] = (f", and the photos alone could be about {kb / 1024:.1f} MB lighter" if kb >= 1024
                                      else f", and the photos alone could be about {kb:.0f} KB lighter")
    blk = g("render-blocking-insight")
    if _items(blk):
        v["blocking_count"] = f"{_items(blk)} "
    if _saving_ms(blk) >= 300:
        v["blocking_saving_sentence"] = f", so the page could show about {_saving_ms(blk) / 1000:.1f} seconds sooner"
    kb = sum((g(k).get("details") or {}).get("overallSavingsBytes", 0) or 0 for k in ("unused-javascript", "unused-css-rules"))
    if kb:
        v["unused_kb"] = f"{kb / 1024:.0f}"
    for key, audit in (("contrast_count", "color-contrast"), ("tap_count", "target-size"), ("alt_count", "image-alt")):
        if _items(g(audit)):
            v[key] = f"{_items(g(audit))} "
    links = sum(_items(g(k)) for k in ("link-name", "button-name", "link-text"))
    if links:
        v["links_count"] = f"{links} "
    r = g("redirects")
    if isinstance(r.get("numericValue"), (int, float)) and r["numericValue"] > 0:
        hops = max(_items(r) - 1, 1)
        v["redirect_hops"] = f"{hops} extra step" + ("s" if hops > 1 else "")
        v["redirect_s"] = f"{r['numericValue'] / 1000:.1f}"
    if isinstance(g("cumulative-layout-shift").get("numericValue"), (int, float)):
        v["cls"] = f"{g('cumulative-layout-shift')['numericValue']:.2f}"
    if isinstance(g("total-blocking-time").get("numericValue"), (int, float)):
        v["tbt_s"] = f"{g('total-blocking-time')['numericValue'] / 1000:.1f}"
    return v


def top_problems(audits, guide, n=3):
    ranked = []
    for p in guide["problems"]:
        found = [audits[a] for a in p["audits"] if a in audits and isinstance(audits[a].get("score"), (int, float))
                 and audits[a]["score"] < 0.9]
        if not found:
            continue
        impact = max(_saving_ms(a) for a in found)
        ranked.append((-(impact if impact >= 300 else 0), p["priority"], p))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [p for _, _, p in ranked[:n]]


def compose(name, audits, guide):
    vals = numbers(audits)
    fill = defaultdict(str, vals)
    probs = top_problems(audits, guide)
    if not probs:
        return None
    out = [f"Hi {name} team,", "", guide["intro"]]
    if "lcp_s" in vals:
        out += ["", guide["headline"].format_map(fill)]
    for i, p in enumerate(probs, 1):
        number = p["number"].format_map(fill)
        if "{" in p["number"] and not any(k in vals for k in re.findall(r"{(\w+)}", p["number"])):
            number = ""                         # no number for this one: skip the sentence rather than guess
        out += ["", f"{i}. {p['title']}"]
        if number:
            out.append(number)
        out.append(p["why"])
        out += [f"   - {s}" for s in p["steps"]]
        out.append(f"   If someone looks after your website, you can forward them this line: \"{p['web_person']}\"")
    out += ["", guide["offer_title"]] + guide["offer"] + ["", guide["signoff"]]
    return "\n".join(out)


def is_yes(text):
    return bool(YES.search((text or "").strip()))


def drafts_folder(imap):
    typ, folders = imap.list()
    for f in folders or []:
        line = f.decode(errors="replace")
        hit = re.match(r'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$', line)
        if hit and ("\\Drafts" in hit.group("flags") or re.search(r"drafts?\"?$", hit.group("name"), re.I)):
            return hit.group("name").strip().strip('"')
    return "INBOX.Drafts"


def save_draft(msg, password, imap_cls=imaplib.IMAP4_SSL):
    m = imap_cls("imap.hostinger.com", 993, timeout=60)
    m.login(HELLO, password)
    try:
        folder = drafts_folder(m)
        typ, _ = m.append(f'"{folder}"', "\\Draft", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        return typ == "OK"
    finally:
        try:
            m.logout()
        except Exception:
            pass


def notify(text, subject, password, to, smtp=smtplib.SMTP_SSL):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Frontage machine", HELLO))
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(text)
    s = smtp("smtp.hostinger.com", 465, timeout=30)
    s.login(HELLO, password)
    s.send_message(msg, to_addrs=[to])
    s.quit()


def run(home, password, owner_email, today=None, log=print, imap_cls=imaplib.IMAP4_SSL, smtp=smtplib.SMTP_SSL):
    today = today or dt.date.today()
    counts = {"yes_replies": 0, "drafted": 0, "needs_you": 0}
    gpath = os.path.join(home, "fix_guide.json")
    if not os.path.exists(gpath):
        return counts
    guide = json.load(open(gpath, encoding="utf-8"))
    rep = _read(os.path.join(home, "0_replies.csv"))
    if rep.empty or "first_lines" not in rep.columns:
        return counts
    lpath = os.path.join(home, "0_fix_replies.csv")
    done = set(_read(lpath).get("reply_message_id", pd.Series(dtype=str)))
    sent = _read(os.path.join(home, "0_sent_log.csv"))
    todo = rep[(rep["kind"] == "reply") & rep["first_lines"].apply(is_yes) & ~rep["message_id"].isin(done)]
    for _, r in todo.iterrows():
        counts["yes_replies"] += 1
        row = sent[sent["email"].str.lower() == r["matched_email"]].head(1) if len(sent) else sent
        place_id = row["place_id"].iloc[0] if len(row) else ""
        name = (row["name"].iloc[0] if len(row) else "") or "there"
        audits = load_audit(home, place_id) if place_id else None
        text = compose(name, audits, guide) if audits else None
        status = "drafted"
        try:
            if text:
                msg = EmailMessage()
                subj = r["subject"] if str(r["subject"]).lower().startswith("re:") else f"Re: {r['subject']}"
                msg["Subject"] = subj
                msg["From"] = formataddr((FROM_NAME, HELLO))
                msg["To"] = r["from"]
                msg["Date"] = formatdate(localtime=True)
                msg["Message-ID"] = make_msgid(domain="frontage.agency")
                msg["In-Reply-To"] = r["message_id"]
                msg["References"] = r["message_id"]
                msg.set_content(text)
                ok = save_draft(msg, password, imap_cls)
                notify(f"{name} said yes ({r['from']}).\n\nThe reply below is ready in hello@ → Drafts: open it, "
                       f"check it, press Send. Or copy it from here.\n\n" + "-" * 40 + "\n\n" + text,
                       f"Ready reply for {name} — in hello@ Drafts" if ok else f"Reply for {name} — copy and send",
                       password, owner_email, smtp)
                counts["drafted"] += 1
            else:
                status = "needs_you"
                notify(f"{name} ({r['from']}) replied yes, but there's no saved speed test for them, so please "
                       f"answer by hand.\n\nTheir words: {r['first_lines']}", f"{name} said yes — please reply by hand",
                       password, owner_email, smtp)
                counts["needs_you"] += 1
        except Exception as e:
            log(f"[fix reply] could not prepare the reply ({type(e).__name__}); will try again next run")
            continue
        pd.DataFrame([{"created_at": today.isoformat(), "reply_message_id": r["message_id"], "place_id": place_id,
                       "name": name, "to": r["from"], "status": status}])[LOG_COLS].to_csv(
            lpath, mode="a", header=not os.path.exists(lpath), index=False)
    return counts
