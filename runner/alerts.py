"""Short alert emails to Anzhel's own Gmail when something needs him — at most once per day per kind.

Kinds: a run failed; no first emails went out on a weekday after the sending window closed.
"""
import datetime as dt
import os

import pandas as pd

NAME = "0_alerts.csv"


def _read(path):
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()


def already_sent(home, kind, day):
    a = _read(os.path.join(home, NAME))
    return bool(len(a) and ((a["kind"] == kind) & (a["day"] == day)).any())


def send(home, kind, text, password, to, day, notify, log=print):
    """notify(text, subject, password, to) sends the email (fixreply.notify)."""
    if not to or not password or already_sent(home, kind, day):
        return False
    subject = {"failed": "⚠️ Frontage: a run failed today",
               "zero_sent": "⚠️ Frontage: no emails went out today"}.get(kind, "⚠️ Frontage alert")
    notify(text, subject, password, to)
    path = os.path.join(home, NAME)
    pd.DataFrame([{"day": day, "kind": kind, "text": text[:200]}]).to_csv(
        path, mode="a", header=not os.path.exists(path), index=False)
    log(f"[alert] sent to you: {subject}")
    return True


def sent_today(home, day):
    s = _read(os.path.join(home, "0_sent_log.csv"))
    return int((s.get("sent_at", pd.Series(dtype=str)).str[:10] == day).sum()) if len(s) else 0


def check(home, ok, local_now, window, password, to, notify, log=print):
    """Called at the end of each live run. local_now: datetime in the sending window's time zone."""
    day = local_now.date().isoformat()
    out = []
    if not ok:
        out.append(send(home, "failed", "A Frontage run reported SOMETHING FAILED.\n\nThe log is in My Drive/Frontage/"
                        "runs (newest file). Ask Claude to check it.", password, to, day, notify, log))
    if local_now.weekday() in window["weekdays"] and local_now.strftime("%H:%M") >= window["end"]:
        if sent_today(home, day) == 0:
            why = ("Sending is PAUSED (0_PAUSE.txt is on Drive: too many bounces)."
                   if os.path.exists(os.path.join(home, "0_PAUSE.txt")) else
                   "The reason isn't clear — maybe no ready leads, or the sender failed.")
            out.append(send(home, "zero_sent", f"No first emails went out today ({day}).\n\n{why}\n\n"
                            "Ask Claude to check the newest log in My Drive/Frontage/runs.",
                            password, to, day, notify, log))
    return any(out)
