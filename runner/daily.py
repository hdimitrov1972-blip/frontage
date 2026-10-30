"""One day of Frontage on the server: search (when needed) -> pipeline (when a town waits) -> sender.

    python runner/daily.py run --mode live|test
    python runner/daily.py finalize

The notebooks are downloaded from Google Drive before this runs, and the Frontage folder
is synced to /content/drive/MyDrive/Frontage, so they run exactly as in Colab.

Public repository: the GitHub log shows only counts. Everything the notebooks print goes
to a log file in My Drive/Frontage/runs/, which only you can see.
"""
import datetime as dt
import glob
import json
import os
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

import pandas as pd

import replies
import suspects

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONTENT = os.environ.get("FRONTAGE_CONTENT", "/content")
CONFIG = json.load(open(os.path.join(ROOT, "config", "frontage.json")))
DRIVE = os.path.join(CONTENT, "drive", "MyDrive", CONFIG["drive_folder"])
NB_DIR = os.path.join(CONTENT, "notebooks")
RUN_DIR = os.path.join(CONTENT, "run")
SNAP = os.path.join(CONTENT, "snapshot_before_pipeline")
MARKER = os.path.join(CONTENT, ".pipeline_running")
LOG_DIR = os.path.join(DRIVE, "runs")


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def say(msg, log=None, note=False):
    """Public line: GitHub log (counts only) and the private log. note=True also shows it on the run page."""
    print(("::notice::" if note and os.environ.get("GITHUB_ACTIONS") else "") + msg, flush=True)
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def read_csv(path):
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------- what is waiting

def towns_list():
    with open(os.path.join(ROOT, "config", "towns.txt"), encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]


def town_files():
    return sorted(glob.glob(os.path.join(DRIVE, "towns", "*.csv")))


def waiting_town_files():
    done = set(read_csv(os.path.join(DRIVE, "0_pipeline_done.csv")).get("file", pd.Series(dtype=str)))
    return [os.path.basename(p) for p in town_files() if os.path.basename(p) not in done]


def searched_recently(town, today):
    days = CONFIG["search_again_after_days"]
    for p in town_files():
        name = os.path.basename(p)[:-4]
        if "_" not in name:
            continue
        t, d = name.rsplit("_", 1)
        try:
            if t.lower() == town.lower() and (today - dt.date.fromisoformat(d)).days < days:
                return True
        except ValueError:
            continue
    return False


def next_town(today):
    for town in towns_list():
        if not searched_recently(town, today):
            return town
    return None


def ready_leads():
    """Email leads the sender could use: approved, pending, with a fresh report."""
    m = read_csv(os.path.join(DRIVE, "LEADS_MASTER.csv"))
    if m.empty:
        return 0
    for c in ("Funnel", "Status_Outreach", "Send_Ready", "Email_Approved", "Report_File", "Report_Date"):
        if c not in m.columns:
            m[c] = ""
    age = (pd.Timestamp.today().normalize() - pd.to_datetime(m["Report_Date"].str[:10], errors="coerce")).dt.days
    ok = ((m["Funnel"] == "email") & (m["Status_Outreach"].str.lower() == "pending")
          & m["Send_Ready"].str.lower().isin(["true", "1"]) & m["Email_Approved"].str.lower().isin(["true", "1"])
          & (m["Report_File"] != "") & (age <= 21))
    return int(ok.sum())


def sent_today():
    log = read_csv(os.path.join(DRIVE, "0_sent_log.csv"))
    if log.empty:
        return 0, {}
    today = log[log["sent_at"].str.startswith(now_utc().date().isoformat())]
    return len(today), today.get("mailbox", pd.Series(dtype=str)).str.split("@").str[0].value_counts().to_dict()


def in_send_window():
    w = CONFIG["send_window"]
    t = dt.datetime.now(ZoneInfo(w["timezone"]))
    hm = t.strftime("%H:%M")
    return t.weekday() in w["weekdays"] and w["start"] <= hm < w["end"], t.strftime("%a %H:%M Irish time")


# ---------------------------------------------------------------- running a notebook

def run_step(step, log, settings=None):
    nb = os.path.join(NB_DIR, CONFIG["notebooks"][step])
    if not os.path.exists(nb):
        say(f"[{step}] FAILED: notebook not found on Drive ({CONFIG['notebooks'][step]})", log)
        return False
    work = os.path.join(RUN_DIR, step)
    shutil.rmtree(work, ignore_errors=True)        # fresh working folder, like a new Colab runtime
    os.makedirs(work)
    cmd = [sys.executable, "-u", os.path.join(HERE, "run_notebook.py"), nb]
    for k, v in (settings or {}).items():
        cmd += ["--set", f"{k}={v}"]
    start = now_utc()
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n\n==================== {step.upper()} — {CONFIG['notebooks'][step]} ====================\n")
        f.flush()
        code = subprocess.call(cmd, cwd=work, stdout=f, stderr=subprocess.STDOUT)
    mins = (now_utc() - start).total_seconds() / 60
    say(f"[{step}] {'finished' if code == 0 else 'FAILED (details in the Drive log)'} in {mins:.0f} min", log)
    return code == 0


def snapshot():
    shutil.rmtree(SNAP, ignore_errors=True)
    shutil.copytree(DRIVE, SNAP, ignore=shutil.ignore_patterns("runs"))
    open(MARKER, "w").write(now_utc().isoformat())


def restore_snapshot():
    """Pipeline did not finish: put Drive back exactly as before it started (logs kept)."""
    keep_logs = os.path.join(CONTENT, "runs_keep")
    shutil.rmtree(keep_logs, ignore_errors=True)
    if os.path.isdir(LOG_DIR):
        shutil.copytree(LOG_DIR, keep_logs)
    shutil.rmtree(DRIVE)
    shutil.copytree(SNAP, DRIVE)
    if os.path.isdir(keep_logs):
        shutil.copytree(keep_logs, LOG_DIR, dirs_exist_ok=True)
    os.remove(MARKER)


# ---------------------------------------------------------------- the day

def run(mode):
    if not os.path.isdir(DRIVE):
        raise SystemExit(f"Drive folder not synced: {DRIVE}")
    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = now_utc().strftime("%Y-%m-%d_%H%M")
    log = os.path.join(LOG_DIR, f"{stamp}_{mode}.log")
    today = now_utc().date()
    ok = True
    say(f"FRONTAGE DAILY RUN — {stamp} UTC — mode: {mode}", log)
    # 0. Replies and bounces first, so today's sending already skips them
    if mode in ("live", "replies"):
        ok &= check_replies(log)
        if mode == "replies":
            say("RESULT: " + ("OK" if ok else "SOMETHING FAILED"), log, note=True)
            return 0 if ok else 1

    ready = ready_leads()
    waiting = waiting_town_files()
    say(f"ready email leads: {ready}   town files waiting for the pipeline: {len(waiting)}", log)

    # 1. Search, only when leads run low and no town is already waiting
    if mode == "live" and not waiting and ready < CONFIG["ready_leads_min"]:
        town = next_town(today)
        if town:
            say(f"[search] leads below {CONFIG['ready_leads_min']} — searching {town}", log)
            ok &= run_step("search", log, {"TOWN": json.dumps(town)})
            waiting = waiting_town_files()
        else:
            say("[search] every town in config/towns.txt was searched in the last 90 days", log)
    elif mode == "live":
        say("[search] not needed today", log)

    # 2. Pipeline, when a town file waits. On failure Drive goes back to how it was.
    if mode == "live" and waiting:
        say(f"[pipeline] processing {waiting[0][:-4]}", log)
        snapshot()
        if run_step("pipeline", log):
            os.remove(MARKER)
        else:
            ok = False
            restore_snapshot()
            say("[pipeline] Drive put back as before the pipeline; it runs again on the next day", log)
    elif mode == "live":
        say("[pipeline] no town waiting", log)

    # 3. Sender
    inside, when = in_send_window()
    if mode == "test":
        to = os.environ.get("TEST_EMAIL", "").strip()
        if not to:
            say("[sender] TEST_EMAIL secret missing — test not run", log)
            return 1
        ok &= run_step("sender", log, {"TEST_SEND_TO": json.dumps([to])})
    elif os.path.exists(os.path.join(DRIVE, "0_PAUSE.txt")):
        say("[sender] PAUSED — 0_PAUSE.txt is on Drive (too many bounces); nothing sent", log, note=True)
    elif not inside:
        say(f"[sender] outside the sending window ({when}) — nothing sent", log)
    else:
        before, _ = sent_today()
        ok &= run_step("sender", log, {"TEST_SEND_TO": "[]"})
        after, per_box = sent_today()
        say(f"[sender] sent now: {after - before}   today in total: {after}   per mailbox: {per_box}", log, note=True)

    # 4. Suspect addresses: clear cases decided, answers applied (after the sender, as agreed)
    if mode == "live":
        try:
            c = suspects.run(DRIVE, log=lambda m: say(m, log))
            say(f"[suspects] held back: {c['suspects']}   approved: {c['yes']}   to phone list: {c['no']}   "
                f"left for the weekly check: {c['unclear']}", log, note=True)
        except Exception as e:
            ok = False
            say(f"[suspects] FAILED ({type(e).__name__}) — nothing changed by it", log)

    say(f"ready email leads left: {ready_leads()}", log, note=True)
    say("RESULT: " + ("OK" if ok else "SOMETHING FAILED — see the log in My Drive/Frontage/runs"), log, note=True)
    return 0 if ok else 1


def check_replies(log):
    passwords = {f"{b}@{replies.DOMAIN}": os.environ.get(f"SMTP_PASSWORD_{i}", "")
                 for i, b in enumerate(replies.BOXES, 1)}
    try:
        c = replies.run(DRIVE, passwords, log=lambda m: say(m, log))
    except Exception as e:
        say(f"[replies] FAILED ({type(e).__name__}) — sending goes on; checked again next run", log)
        with open(log, "a", encoding="utf-8") as f:
            import traceback
            traceback.print_exc(file=f)
        return False
    say(f"[replies] mailboxes read: {c['mailboxes_read']}/5   new: {c['reply']} replies, {c['optout']} no-thanks, "
        f"{c['bounce']} bounces, {c['auto']} auto-replies   added to do-not-contact: "
        f"{c['added_to_do_not_contact']}" + ("   ⛔ SENDING PAUSED (bounces over 3%)" if c["paused"] else ""),
        log, note=True)
    return c["mailboxes_read"] == 5


def finalize():
    """Runs even if the job was stopped: never upload a half-finished pipeline."""
    if os.path.exists(MARKER) and os.path.isdir(SNAP):
        print("pipeline did not finish — restoring Drive to how it was before it", flush=True)
        restore_snapshot()
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "finalize":
        sys.exit(finalize())
    if len(sys.argv) == 4 and sys.argv[1] == "run" and sys.argv[2] == "--mode" and sys.argv[3] in ("live", "test", "replies"):
        sys.exit(run(sys.argv[3]))
    raise SystemExit(__doc__)
