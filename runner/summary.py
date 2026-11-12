"""Sunday summary: one email to you (TEST_EMAIL) and a copy in My Drive/Frontage/runs."""
import datetime as dt
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate

import pandas as pd


def _read(path):
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()


def _list_rows(path):
    try:
        d = pd.read_excel(path, sheet_name=0, dtype=str).fillna("")
        return int((d.iloc[:, 0].str.strip() == "").sum())
    except Exception:
        return 0


VERSIONS = (("outbox_v2_short", "short email"), ("outbox_v1_nopdf", "long email"), ("outbox_v1", "old (PDF attached)"))


def version_of(template):
    t = str(template)
    return next((label for prefix, label in VERSIONS if t.startswith(prefix)), None)


def split_test(home, sent, rep):
    """Since the newest test began: emails, replies from people and no-thanks per email version."""
    ar = _read(os.path.join(home, "0_sent_leads.csv"))
    m = _read(os.path.join(home, "LEADS_MASTER.csv"))
    if not len(sent) or "place_id" not in sent.columns:
        return {}
    tmpl = dict(zip(ar.get("place_id", pd.Series(dtype=str)), ar.get("Template", pd.Series(dtype=str))))
    if len(m) and "Template" in m.columns:
        tmpl.update({p: t for p, t in zip(m["place_id"], m["Template"]) if t})
    s = sent.assign(v=sent["place_id"].map(lambda p: version_of(tmpl.get(p, ""))))
    newest = next((label for _, label in VERSIONS[:2] if (s["v"] == label).any()), None)
    if not newest:
        return {}
    start = str(s.loc[s["v"] == newest, "sent_at"].min())[:10]          # the day this test began
    s = s[(s["sent_at"].str[:10] >= start) & s["v"].notna()]
    by_email = dict(zip(s["email"].str.lower(), s["v"]))
    people = rep[rep.get("kind", pd.Series(dtype=str)).isin(["reply", "optout"])] if len(rep) else rep
    out = {"since": start}
    for _, v in VERSIONS:
        if not (s["v"] == v).any():
            continue
        r = people[people["matched_email"].str.lower().map(by_email) == v] if len(people) else people
        out[v] = {"sent": int((s["v"] == v).sum()), "replies": int((r["kind"] == "reply").sum()) if len(r) else 0,
                  "no_thanks": int((r["kind"] == "optout").sum()) if len(r) else 0}
    return out


def week_numbers(home, today, ready_leads):
    start = (today - dt.timedelta(days=6)).isoformat()
    sent = _read(os.path.join(home, "0_sent_log.csv"))
    fu = _read(os.path.join(home, "0_followup_log.csv"))
    rep = _read(os.path.join(home, "0_replies.csv"))
    rv = _read(os.path.join(home, "2B_suspect_review.csv"))
    first = sent[sent.get("sent_at", pd.Series(dtype=str)).str[:10] >= start] if len(sent) else sent
    fups = fu[fu.get("sent_at", pd.Series(dtype=str)).str[:10] >= start] if len(fu) else fu
    wk = rep[rep.get("seen_at", pd.Series(dtype=str)) >= start] if len(rep) else rep

    def kind(k):
        return int((wk.get("kind", pd.Series(dtype=str)) == k).sum()) if len(wk) else 0

    real_replies = wk[wk["kind"] == "reply"] if len(wk) else wk
    n = {
        "split": split_test(home, sent, rep),
        "first_emails": len(first),
        "follow_ups": len(fups),
        "bounces": kind("bounce"),
        "no_thanks": kind("optout"),
        "replies": kind("reply"),
        "auto_replies": kind("auto"),
        "ready_leads": ready_leads,
        "weekly_check": int(((rv.get("Approve", pd.Series(dtype=str)) == "")
                             & rv.get("Hint", pd.Series(dtype=str)).str.startswith("weekly check")).sum()) if len(rv) else 0,
        "paused": os.path.exists(os.path.join(home, "0_PAUSE.txt")),
        "forms_sent": int((_read(os.path.join(home, "0_contact_forms_sent.csv")).get("done_on", pd.Series(dtype=str))
                           >= start).sum()),
        "forms_waiting": _list_rows(os.path.join(home, "Contact_forms_to_send.xlsx")),
        "reply_from": sorted(set(real_replies.get("matched_email", pd.Series(dtype=str)))) if len(real_replies) else [],
    }
    if len(fups) and "variant" in fups.columns:
        n["follow_ups_by_text"] = fups["variant"].value_counts().to_dict()
    total = len(first)
    n["bounce_rate"] = f"{n['bounces'] / total:.1%}" if total else "–"
    return n


def text(n, today):
    lines = [f"Frontage — week to {today.strftime('%A %d %B %Y')}", ""]
    if n["paused"]:
        lines += ["⛔ SENDING IS PAUSED: too many bounces. See 0_PAUSE.txt in My Drive/Frontage.", ""]
    lines += [
        f"First emails sent:      {n['first_emails']}",
        f"Follow-ups sent:        {n['follow_ups']}" + (f"   (by text: {n['follow_ups_by_text']})" if n.get("follow_ups_by_text") else ""),
        f"Replies from people:    {n['replies']}",
    ] + ([f"Test since {n['split']['since']}:"] + [
        f"   {v}: {d['sent']} sent, {d['replies']} replies, {d['no_thanks']} no thanks"
        for v, d in n["split"].items() if v != "since"] if n.get("split") else []) + [
        f"'No thanks' / remove:   {n['no_thanks']}   (on do-not-contact, never emailed again)",
        f"Bounces:                {n['bounces']}   ({n['bounce_rate']} of first emails)",
        f"Automatic replies:      {n['auto_replies']}",
        "",
        f"Ready email leads in stock: {n['ready_leads']}",
        f"Suspect addresses waiting for the weekly check: {n['weekly_check']}",
        "",
        f"Contact forms you sent this week: {n.get('forms_sent', 0)}",
        f"Waiting in Contact_forms_to_send.xlsx: {n.get('forms_waiting', 0)}",
    ]
    if n["reply_from"]:
        lines += ["", "Replies to read (in your Gmail):"] + [f"  - {a}" for a in n["reply_from"]]
    lines += ["", "Details: My Drive/Frontage/runs. Ask Claude for the weekly check."]
    return "\n".join(lines)


def run(home, today, ready_leads, password, to, log=print, smtp=smtplib.SMTP_SSL):
    """Once per Sunday. Returns True if sent (or already sent today)."""
    runs = os.path.join(home, "runs")
    os.makedirs(runs, exist_ok=True)
    copy = os.path.join(runs, f"weekly_summary_{today.isoformat()}.txt")
    if os.path.exists(copy):
        return True
    body = text(week_numbers(home, today, ready_leads), today)
    if to and password:
        msg = EmailMessage()
        msg["Subject"] = f"Frontage weekly summary — {today.strftime('%d %b')}"
        msg["From"] = formataddr(("Frontage machine", "hello@frontage.agency"))
        msg["To"] = to
        msg["Date"] = formatdate(localtime=True)
        msg.set_content(body)
        try:
            s = smtp("smtp.hostinger.com", 465, timeout=30)
            s.login("hello@frontage.agency", password)
            s.send_message(msg, to_addrs=[to])
            s.quit()
        except Exception as e:
            log(f"[summary] email not sent ({type(e).__name__}); copy saved on Drive")
    open(copy, "w", encoding="utf-8").write(body)
    return True
