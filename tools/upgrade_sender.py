"""Make 'Frontage Sender v2.3 LIVE.ipynb' from 'Frontage Sender v2.2 LIVE.ipynb'.

    python tools/upgrade_sender.py OLD.ipynb NEW.ipynb

The only change: each email's Message-ID is saved in 0_sent_log.csv (new column
'message_id'), so a later follow-up can be sent as a reply in the same conversation.
Email text, PDF, limits and pacing are untouched. Stops if v2.2 isn't exactly as expected.
"""
import json
import sys

CHANGES = [
    ('LOG_COLS = ["sent_at", "place_id", "email", "name", "subject", "mailbox"]',
     'LOG_COLS = ["sent_at", "place_id", "email", "name", "subject", "mailbox", "message_id"]'),
    ('''    log = pd.read_csv(p, dtype=str).fillna("")
    if "mailbox" in log.columns:
        return
''', '''    log = pd.read_csv(p, dtype=str).fillna("")
    if all(c in log.columns for c in LOG_COLS):
        return
    if "mailbox" in log.columns:            # v2.2 log: only the new message_id column is missing
        backup = p.replace(".csv", "_backup_before_v23.csv")
        if not os.path.exists(backup):
            log.to_csv(backup, index=False)
        log["message_id"] = ""
        tmp = p + ".tmp"
        log[LOG_COLS + [c for c in log.columns if c not in LOG_COLS]].to_csv(tmp, index=False)
        os.replace(tmp, p)
        print(f"🗂  Sent log: added the message_id column ({len(log)} old sends kept; "
              f"backup: {os.path.basename(backup)})")
        return
'''),
    ('def log_sent(row, when, subject, mailbox):', 'def log_sent(row, when, subject, mailbox, message_id=""):'),
    ('''                   "mailbox": mailbox}])[LOG_COLS].to_csv(p, mode="a", header=first, index=False)''',
     '''                   "mailbox": mailbox,
                   "message_id": message_id}])[LOG_COLS].to_csv(p, mode="a", header=first, index=False)'''),
    ('log_sent(row, when, msg["Subject"], address)', 'log_sent(row, when, msg["Subject"], address, msg["Message-ID"])'),
    ('FRONTAGE SENDER v2.2 (one domain)', 'FRONTAGE SENDER v2.3 (one domain)'),
]


def upgrade(src):
    for old, new in CHANGES:
        if src.count(old) != 1:
            raise SystemExit(f"v2.2 is not as expected; nothing changed. Missing: {old[:60]!r}")
        src = src.replace(old, new)
    return src


def main(old_path, new_path):
    nb = json.load(open(old_path, encoding="utf-8"))
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    if len(code) != 1:
        raise SystemExit("expected one code cell")
    for c in nb["cells"]:
        src = "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
        if c["cell_type"] == "code":
            c["source"] = upgrade(src).splitlines(keepends=True)
            c["outputs"], c["execution_count"] = [], None
        else:
            c["source"] = src.replace("v2.2", "v2.3").splitlines(keepends=True)
    json.dump(nb, open(new_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("Sender v2.3 made: only the message_id lines changed.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
