"""Make 'Frontage Sender v2.4 LIVE.ipynb' from 'Frontage Sender v2.3 LIVE.ipynb'.

    python tools/upgrade_sender_v24.py OLD.ipynb NEW.ipynb

The only change: a split test (Anzhel's OK, 10 Nov 2026).
- Version A (half the businesses): exactly the email as before, with the PDF report attached.
- Version B (the other half): the same text, but NO attachment — the report is offered on reply
  ("Just reply "yes" and I'll send it over") — no bulk-mail List-Unsubscribe header (the opt-out line in
  the text stays), and a personal sender name. These are the things that make Gmail file an email under
  "Updates" instead of the main inbox.
Which half a business is in is fixed by its place_id, so it always gets the same version.
Test mode can send both versions (TEST_VARIANTS = ["A", "B"]) to see where each one lands.
Limits, pacing, logging, do-not-contact: untouched. Stops if v2.3 isn't exactly as expected.
"""
import json
import sys

OLD_BUILD = '''def build_message(row, from_addr):
    """Exactly the subject and body the pipeline wrote, and always the PDF report."""
    subject = safe_str(row.get("Email_Subject"))
    body = safe_str(row.get("Email_Body"))
    pdf = os.path.join(REPORTS_DIR, safe_str(row.get("Report_File")))
    if not subject or not body:
        raise ValueError("no email text — re-run the pipeline (outbox stage)")
    if not clean_address(row.get("Best_Email")):
        raise ValueError(f"broken address: {safe_str(row.get('Best_Email'))}")
    if not safe_str(row.get("Report_File")) or not os.path.exists(pdf):
        raise ValueError(f"report PDF not found ({pdf}) — upload 4A_reports.zip")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((FROM_NAME, from_addr))
    msg["To"] = clean_address(row.get("Best_Email"))
    msg["Reply-To"] = REPLY_TO or from_addr
    msg["List-Unsubscribe"] = f"<mailto:{REPLY_TO or from_addr}?subject=unsubscribe>"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1])
    msg.set_content(body)
    with open(pdf, "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="pdf",
                           filename=safe_str(row.get("Attachment_Name")) or os.path.basename(pdf))
    return msg, "outbox_v1"
'''

NEW_BUILD = '''PDF_LINE = "I've put everything in a short report for you, attached, including how we'd fix it."
NO_PDF_LINE = ("I've put everything in a short report, including how we'd fix it. "
               "Just reply \\"yes\\" and I'll send it over.")


def ab_variant(row):
    """'A' (with PDF) or 'B' (no PDF). Fixed per business, so it always gets the same version."""
    pid = safe_str(row.get("place_id")) or safe_str(row.get("Best_Email")).lower()
    if SPLIT_B_SHARE <= 0 or not pid:
        return "A"
    return "B" if int(hashlib.md5(pid.encode("utf-8")).hexdigest(), 16) % 1000 < SPLIT_B_SHARE * 1000 else "A"


def build_message(row, from_addr, variant=None):
    """Exactly the subject and body the pipeline wrote.
    Version A: with the PDF report attached (as always). Version B (split test): no attachment —
    the report is offered on reply — no List-Unsubscribe header, and a personal sender name."""
    variant = variant or ab_variant(row)
    subject = safe_str(row.get("Email_Subject"))
    body = safe_str(row.get("Email_Body"))
    pdf = os.path.join(REPORTS_DIR, safe_str(row.get("Report_File")))
    if not subject or not body:
        raise ValueError("no email text — re-run the pipeline (outbox stage)")
    if not clean_address(row.get("Best_Email")):
        raise ValueError(f"broken address: {safe_str(row.get('Best_Email'))}")
    if not safe_str(row.get("Report_File")) or not os.path.exists(pdf):
        raise ValueError(f"report PDF not found ({pdf}) — upload 4A_reports.zip")
    if variant == "B":
        if PDF_LINE in body:
            body = body.replace(PDF_LINE, NO_PDF_LINE)
        else:
            variant = "A"                      # unknown wording: send the original email instead

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((B_FROM_NAME if variant == "B" else FROM_NAME, from_addr))
    msg["To"] = clean_address(row.get("Best_Email"))
    msg["Reply-To"] = REPLY_TO or from_addr
    if variant == "A":
        msg["List-Unsubscribe"] = f"<mailto:{REPLY_TO or from_addr}?subject=unsubscribe>"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1])
    msg.set_content(body)
    if variant == "A":
        with open(pdf, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf",
                               filename=safe_str(row.get("Attachment_Name")) or os.path.basename(pdf))
    return msg, ("outbox_v1" if variant == "A" else "outbox_v1_nopdf")
'''

OLD_TEST = '''    for address, pw in creds.items():
        try:
            msg, _ = build_message(row, address)
            server = connect_smtp(address, pw)
            for addr in test_to:
                del msg["To"]
                del msg["Message-ID"]
                msg["To"] = addr
                msg["Message-ID"] = make_msgid(domain=address.split("@")[-1])
                server.send_message(msg, to_addrs=[addr])
            server.quit()
            print(f"  ✅ {address} → test sent")
        except Exception as e:
            print(f"  ❌ {address} → {str(e)[:100]}")
'''

NEW_TEST = '''    for address, pw in creds.items():
        for v in (TEST_VARIANTS or ["A"]):
            try:
                msg, _ = build_message(row, address, variant=v)
                server = connect_smtp(address, pw)
                for addr in test_to:
                    del msg["To"]
                    del msg["Message-ID"]
                    msg["To"] = addr
                    msg["Message-ID"] = make_msgid(domain=address.split("@")[-1])
                    server.send_message(msg, to_addrs=[addr])
                server.quit()
                print(f"  ✅ {address} → test sent (version {v})")
            except Exception as e:
                print(f"  ❌ {address} → version {v}: {str(e)[:100]}")
'''

CHANGES = [
    ('import zipfile\n', 'import zipfile\nimport hashlib\n'),
    ('FROM_NAME = "Frontage Agency"      # what the inbox shows as the sender\n',
     'FROM_NAME = "Frontage Agency"      # what the inbox shows as the sender\n'
     '\n'
     '# SPLIT TEST (from 10 Nov 2026): this share of businesses gets version B — the same text but NO PDF\n'
     '# attached (the report is offered on reply), no bulk-mail header, and a personal sender name.\n'
     '# Fixed per business. 0 = everyone gets version A, exactly as before.\n'
     'SPLIT_B_SHARE = 0.5\n'
     'B_FROM_NAME = "Anzhel at Frontage"\n'
     'TEST_VARIANTS = ["A"]              # test mode: versions each mailbox sends, e.g. ["A", "B"]\n'),
    (OLD_BUILD, NEW_BUILD),
    (OLD_TEST, NEW_TEST),
    ('FRONTAGE SENDER v2.3 (one domain)', 'FRONTAGE SENDER v2.4 (one domain, split test)'),
]


def upgrade(src):
    for old, new in CHANGES:
        if src.count(old) != 1:
            raise SystemExit(f"v2.3 is not as expected; nothing changed. Missing: {old[:60]!r}")
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
            c["source"] = src.replace("v2.3", "v2.4").splitlines(keepends=True)
    json.dump(nb, open(new_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("Sender v2.4 made: split test (version B = no PDF) added; everything else unchanged.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
