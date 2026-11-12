"""Make 'Frontage Sender v2.5 LIVE.ipynb' from 'Frontage Sender v2.4 LIVE.ipynb'.

    python tools/upgrade_sender_v25.py OLD.ipynb NEW.ipynb

Changes (Anzhel's decision, 12 Nov 2026):
1. Split test long vs short: SHORT_SHARE of the businesses get the short email (Email_Subject_S / Email_Body_S,
   written by runner/shorttext.py); the rest get the long one. Fixed per business. A business without a short
   text gets the long one.
2. Two reply buttons in every no-PDF email: "Yes, send me the report" / "No thanks". Each opens the reader's
   own email app with a ready reply to hello@ (subject YES … / NO THANKS …, with a short reference code),
   which the reply checker sorts by itself. The plain-text part of the email is unchanged.
Limits, pacing, logging, do-not-contact: untouched. Stops if v2.4 isn't exactly as expected.
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from upgrade_sender_v24 import NEW_BUILD as V24_BUILD, NEW_TEST as V24_TEST  # noqa: E402

V25_BUILD = '''PDF_LINE = "I've put everything in a short report for you, attached, including how we'd fix it."
NO_PDF_LINE = ("I've put everything in a short report, including how we'd fix it. "
               "Just reply \\"yes\\" and I'll send it over.")


def _share(row, salt, share):
    pid = safe_str(row.get("place_id")) or safe_str(row.get("Best_Email")).lower()
    if share <= 0 or not pid:
        return False
    return int(hashlib.md5((salt + pid).encode("utf-8")).hexdigest(), 16) % 1000 < share * 1000


def ab_variant(row):
    """'A' (with PDF) or 'B' (no PDF). Fixed per business, so it always gets the same version."""
    return "B" if _share(row, "", SPLIT_B_SHARE) else "A"


def text_variant(row):
    """'S' (short email) or 'L' (long email). Fixed per business. No short text written = long."""
    has_short = safe_str(row.get("Email_Subject_S")) and safe_str(row.get("Email_Body_S"))
    return "S" if has_short and _share(row, "short:", SHORT_SHARE) else "L"


def ref_code(row):
    """Short code in the button replies, so an answer is matched to the business whatever address it comes from."""
    pid = safe_str(row.get("place_id")) or safe_str(row.get("Best_Email")).lower()
    return hashlib.md5(pid.encode("utf-8")).hexdigest()[:6].upper()


def buttons_html(body, reply_to, ref):
    """The same text as HTML, with two reply buttons placed before the signature."""
    from html import escape
    from urllib.parse import quote

    def link(label, subject, text, dark):
        href = f"mailto:{reply_to}?subject={quote(subject)}&body={quote(text)}"
        style = ("display:inline-block;padding:9px 16px;border:1px solid #1C2D35;border-radius:6px;"
                 "text-decoration:none;font-weight:bold;"
                 + ("background:#1C2D35;color:#ffffff;" if dark else "background:#ffffff;color:#1C2D35;"))
        return f'<a href="{escape(href, quote=True)}" style="{style}">{escape(label)}</a>'

    buttons = ("<p>" + link("Yes, send me the report", f"YES - send the report (ref {ref})",
                            "Yes, please send me the report.", True)
               + " &nbsp; " + link("No thanks", f"NO THANKS (ref {ref})", "No thanks.", False) + "</p>")
    paras = [p for p in body.split("\\n\\n")]
    out, placed = [], False
    for p in paras:
        first = p.strip().split("\\n")[0].strip()
        if not placed and first in ("Kind regards,", "Anzhel"):
            out.append(buttons)
            placed = True
        out.append("<p>" + "<br>".join(escape(l) for l in p.split("\\n")) + "</p>")
    if not placed:
        out.append(buttons)
    return ('<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.5;color:#222222">'
            + "".join(out) + "</div>")


def build_message(row, from_addr, variant=None, text=None):
    """Version A: the pipeline's email with the PDF attached (the old way).
    Version B: no attachment, personal sender name, no List-Unsubscribe header; the long text ('L') or the
    short one ('S'), and two reply buttons when BUTTONS is on."""
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
    label = "outbox_v1"
    if variant == "B":
        text = text or text_variant(row)
        if text == "S" and safe_str(row.get("Email_Subject_S")) and safe_str(row.get("Email_Body_S")):
            subject, body = safe_str(row.get("Email_Subject_S")), safe_str(row.get("Email_Body_S"))
            label = "outbox_v2_short"
        elif PDF_LINE in body:
            body = body.replace(PDF_LINE, NO_PDF_LINE)
            label = "outbox_v1_nopdf"
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
    if variant == "B" and BUTTONS:
        msg.add_alternative(buttons_html(body, REPLY_TO or from_addr, ref_code(row)), subtype="html")
        label += "_btn"
    if variant == "A":
        with open(pdf, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf",
                               filename=safe_str(row.get("Attachment_Name")) or os.path.basename(pdf))
    return msg, label
'''

V25_TEST = '''    for address, pw in creds.items():
        for v in (TEST_VARIANTS or ["L"]):
            try:
                msg, _ = build_message(row, address, variant="A" if v == "A" else "B",
                                       text=v if v in ("L", "S") else None)
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
    ('TEST_VARIANTS = ["A"]              # test mode: versions each mailbox sends, e.g. ["A", "B"]\n',
     'TEST_VARIANTS = ["L", "S"]         # test mode: versions each mailbox sends: "L" long, "S" short, "A" old\n'
     '\n'
     '# SPLIT TEST long vs short (from 12 Nov 2026): this share of businesses gets the short email.\n'
     'SHORT_SHARE = 0.5\n'
     '# Two reply buttons ("Yes, send me the report" / "No thanks") in every no-PDF email.\n'
     'BUTTONS = True\n'),
    (V24_BUILD, V25_BUILD),
    (V24_TEST, V25_TEST),
    ('FRONTAGE SENDER v2.4 (one domain, split test)', 'FRONTAGE SENDER v2.5 (one domain, long/short test, buttons)'),
]


def upgrade(src):
    for old, new in CHANGES:
        if src.count(old) != 1:
            raise SystemExit(f"v2.4 is not as expected; nothing changed. Missing: {old[:60]!r}")
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
            c["source"] = src.replace("v2.4", "v2.5").splitlines(keepends=True)
    json.dump(nb, open(new_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("Sender v2.5 made: long/short split and reply buttons added; everything else unchanged.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
