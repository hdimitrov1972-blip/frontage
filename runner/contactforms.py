"""Contact-form list: businesses with a contact form on their website (no email address found), each with a
ready personal message, for Anzhel to send BY HAND from his phone. Nothing is ever sent by the machine.

Drive files (My Drive/Frontage):
- Contact_forms_to_send.xlsx    the list: tap the link, paste the message, send on their site, type x in "Done"
- 0_contact_forms_sent.csv      every business marked Done (permanent; never listed again)
- 0_contact_forms_checked.csv   every business looked at: form link, robot check, problem found, message
- lighthouse_json/<place_id>.json   the speed test, also used to prepare the free fix note if they say yes

A business is only listed when a REAL problem was found (slow on a phone, no call button, "Not secure",
low phone score, or a very old © year). No problem found = not listed.
"""
import datetime as dt
import json
import os
import re
import sys
from urllib.parse import urljoin, urlparse

import pandas as pd

LIST_NAME = "Contact_forms_to_send.xlsx"
SENT_NAME = "0_contact_forms_sent.csv"
CHECKED_NAME = "0_contact_forms_checked.csv"
MAX_NEW_PER_RUN = 25          # websites checked per run (PageSpeed is free up to 25,000 a day)
RETRY_AFTER_DAYS = 14         # a site that was down / timed out is tried again after this
MY_NAME, MY_EMAIL = "Anzhel", "hello@frontage.agency"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
CHECKED_COLS = ["place_id", "checked_on", "result", "name", "city", "website", "domain", "form_url", "form_kind",
                "robot_check", "problem", "message"]
SENT_COLS = ["place_id", "done_on", "mark", "name", "city", "domain", "form_url"]
CATEGORY = {"cafes": "cafés", "restaurants": "restaurants", "pubs": "pubs", "bars": "bars", "hotels": "hotels",
            "salons": "hair and beauty salons", "gyms": "gyms", "spas": "spas", "bakeries": "bakeries"}
CONTACT_LINK = re.compile(r"contact|get-?in-?touch|enquir|inquir|reach-?us|talk-?to-?us|write-?to-?us", re.I)
FORM_BUILDERS = re.compile(r"wpforms|wpcf7|gform_|elementor-form|formspree|jotform|typeform|hsforms|hs-form|"
                           r"wixui-form|wix-forms|sqs-block-form|ninja-forms|forminator|fluentform|caldera|"
                           r"formidable|weebly-form|form-builder|mc4wp-form", re.I)
PUBLIC_BODY = re.compile(r"Office of Public Works|Government of Ireland|Heritage Ireland|(County|City) Council", re.I)
CAPTCHA = re.compile(r"recaptcha|hcaptcha|cf-turnstile|challenges\.cloudflare|friendlycaptcha|captcha", re.I)


def _read(path):
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()


def domain_of(url):
    host = urlparse(url if "//" in str(url) else f"http://{url}").netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


# ---------- looking at the website ----------

def _get(url, get):
    r = get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True)
    ctype = r.headers.get("Content-Type", "")
    if r.status_code >= 400 or ("html" not in ctype and ctype):
        raise ValueError(f"HTTP {r.status_code}")
    return r.url, r.text[:800000]


def _links(base, html):
    out = []
    for m in re.finditer(r"<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", html, re.I | re.S):
        href, text = m.group(1).strip(), re.sub(r"<[^>]+>", " ", m.group(2))
        if href.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        if CONTACT_LINK.search(href) or CONTACT_LINK.search(text):
            out.append(urljoin(base, href))
    return out


def _has_form(html):
    has_message_form = re.search(r"<form\b", html, re.I) and re.search(r"<textarea\b", html, re.I)
    return bool(has_message_form or FORM_BUILDERS.search(html))


def look_at_site(website, get, this_year):
    """Returns facts about the site: form page, robot check, call button, https, newest © year."""
    home_url, home = _get(website, get)
    facts = {"home_url": home_url, "https": home_url.lower().startswith("https://"),
             "tel": bool(re.search(r"href=[\"']tel:", home, re.I)), "year": None,
             "form_url": "", "form_kind": "", "robot_check": "",
             "public_body": bool(PUBLIC_BODY.search(home))}
    years = [int(y) for y in re.findall(r"(?:©|&copy;|&#169;|copyright)\s*(?:\d{4}\s*(?:-|–|&ndash;)\s*)?(\d{4})",
                                        home, re.I) if 1995 <= int(y) <= this_year]
    facts["year"] = max(years) if years else None
    pages = [(home_url, home)]
    host = domain_of(home_url)
    tried = {home_url.rstrip("/")}
    for link in _links(home_url, home):
        if domain_of(link) != host or link.rstrip("/") in tried or len(tried) > 4:
            continue
        tried.add(link.rstrip("/"))
        try:
            pages.append(_get(link, get))
        except Exception:
            continue
    contact_page = next((u for u, _ in pages[1:]), "")
    for url, html in pages[1:] + pages[:1]:          # a contact page first, the home page last
        if _has_form(html):
            facts.update(form_url=url, form_kind="form", robot_check="yes" if CAPTCHA.search(html) else "no")
            break
    if not facts["form_url"] and contact_page:
        facts.update(form_url=contact_page, form_kind="contact page", robot_check="?")
    return facts


def pagespeed(url, key, get):
    """Google's phone speed test (free). Returns the full answer (saved for the fix note)."""
    params = [("url", url), ("strategy", "mobile"), ("key", key)] + [
        ("category", c) for c in ("performance", "accessibility", "best-practices", "seo")]
    r = get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed", params=params, timeout=150)
    if r.status_code != 200:
        raise ValueError(f"PageSpeed HTTP {r.status_code}")
    return r.json()


def speed_numbers(result):
    lh = (result or {}).get("lighthouseResult", result or {})
    score = (lh.get("categories", {}).get("performance") or {}).get("score")
    lcp = (lh.get("audits", {}).get("largest-contentful-paint") or {}).get("numericValue")
    return (round(score * 100) if isinstance(score, (int, float)) else None,
            lcp / 1000 if isinstance(lcp, (int, float)) else None)


# ---------- the message ----------

def choose_problem(score, lcp_s, facts, this_year):
    """The single clearest REAL problem, said in plain words, or None."""
    if lcp_s is not None and lcp_s >= 4:
        return "it takes over 10 seconds to open" if lcp_s >= 10 else f"it takes about {round(lcp_s)} seconds to open"
    if facts.get("tel") is False:
        return "there's no button to call you straight from the phone"
    if facts.get("https") is False:
        return "the browser shows it as \"Not secure\""
    if score is not None and score < 50:
        return f"Google's own phone test scores it {score} out of 100"
    if facts.get("year") and facts["year"] <= this_year - 3:
        return f"the footer still says © {facts['year']}, which can make people wonder if you're still open"
    return None


def message(name, category, city, rating, reviews, problem):
    """The text Anzhel approved on 7 Nov 2026. Only the {parts} change per business."""
    where = CATEGORY.get(str(category).strip().lower(), "local businesses")
    lines = [f"Hi {name} team,", ""]
    first = f"I came across {name} while looking at {where} in {city}." if city else \
        f"I came across {name} while looking at {where}."
    try:
        r, n = float(rating), int(float(reviews))
        if n >= 20 and r >= 4.3:
            first += f" {n:,} Google reviews at {r:.1f}★ is a great reputation."
    except (TypeError, ValueError):
        pass
    lines += [first, "",
              f"I had a quick look at your website on a phone and noticed {problem}. That's usually the moment "
              f"people on their phone give up and go to the next place.", "",
              "I run Frontage, a small web studio that fixes exactly this for local businesses. If it's useful, "
              "I'm happy to send you a short free note on what to fix. Just reply to hello@frontage.agency.", "",
              "If not, no problem at all. I won't contact you again.", "",
              "Anzhel", "Frontage · frontage.agency"]
    return "\n".join(lines)


# ---------- the list on Drive ----------

def read_done(xlsx_path):
    """{place_id: what was typed} for rows marked in the Done column of the phone list (x, skip, ...)."""
    if not os.path.exists(xlsx_path):
        return {}
    try:
        d = pd.read_excel(xlsx_path, sheet_name=0, dtype=str).fillna("")
    except Exception:
        return {}
    if "place_id" not in d.columns or d.empty:
        return {}
    done_col = d.columns[0]
    marked = d[d[done_col].str.strip() != ""]
    return dict(zip(marked["place_id"], marked[done_col].str.strip().str.lower()))


def write_list(path, rows):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "To send"
    # phone order: what you tap first is on the left; one short line per business (tap a cell to see it all)
    head = ["Done (type x)", "Business", "Open the form", "Message (copy all)", "Robot check", "Town",
            "Problem found", "Your name", "Your email", "place_id"]
    ws.append(head)
    for r in rows:
        ws.append(["", r["name"], r["form_url"], r["message"],
                   {"yes": "yes – tick 'I'm not a robot'", "no": "no", "?": "check the page"}.get(r["robot_check"], ""),
                   r["city"], r["problem"], MY_NAME, MY_EMAIL, r["place_id"]])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
    widths = [12, 26, 34, 50, 22, 11, 40, 10, 24, 30]
    for i, w in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=False, vertical="top")
        if row[2].value:
            row[2].hyperlink = row[2].value
            row[2].font = Font(color="1155CC", underline="single")
    ws.freeze_panes = "B2"
    how = wb.create_sheet("How to use")
    for line in [
        "How to use this list (about 1 minute per business):",
        "1. Tap the link in 'Open the form' — their contact page opens.",
        "2. Copy the 'Message' cell and paste it into their message box.",
        f"3. Name: {MY_NAME}   Email: {MY_EMAIL}   (phone: leave empty if you can).",
        "4. If there's an 'I'm not a robot' box, tick it. Press Send on their site.",
        "5. Back here, type x in 'Done'. The machine moves it to the sent list and never lists it again.",
        "",
        "Replies come to hello@frontage.agency. 'No thanks' goes on do-not-contact by itself.",
        "If a form doesn't work or the site looks closed, type 'skip' in Done.",
        "Please keep editing this file as it is (don't convert it to a Google Sheet), so the machine can read it.",
    ]:
        how.append([line])
    how.column_dimensions["A"].width = 100
    wb.save(path)


def merge_done(latest_path, local_path):
    """Before saving to Drive: keep any Done ticks made on the phone while this run was busy."""
    newer = read_done(latest_path)
    if not newer or not os.path.exists(local_path):
        return 0
    from openpyxl import load_workbook
    wb = load_workbook(local_path)
    ws = wb.worksheets[0]
    pid_col = [c.value for c in ws[1]].index("place_id")
    n = 0
    for row in ws.iter_rows(min_row=2):
        if row[pid_col].value in newer and not (row[0].value or "").strip():
            row[0].value = newer[row[pid_col].value]
            n += 1
    wb.save(local_path)
    return n


# ---------- the run ----------

def run(home, key, today=None, get=None, speed=None, log=print, max_new=MAX_NEW_PER_RUN):
    today = today or dt.date.today()
    if get is None:
        import requests
        get = requests.get
    speed = speed or (lambda url: pagespeed(url, key, get))
    counts = {"moved_to_sent": 0, "checked": 0, "listed_new": 0, "no_problem": 0, "no_form": 0, "site_down": 0,
              "in_list": 0, "left_to_check": 0}
    list_path = os.path.join(home, LIST_NAME)
    sent_path = os.path.join(home, SENT_NAME)
    checked_path = os.path.join(home, CHECKED_NAME)

    # 1. Ticks from the phone -> permanent sent list
    checked = _read(checked_path)
    for c in CHECKED_COLS:
        if c not in checked.columns:
            checked[c] = ""
    sent = _read(sent_path)
    already = set(sent.get("place_id", pd.Series(dtype=str)))
    done = {k: v for k, v in read_done(list_path).items() if k not in already}
    if done:
        rows = checked[checked["place_id"].isin(set(done))].drop_duplicates("place_id", keep="last")
        new = pd.DataFrame({"place_id": rows["place_id"], "done_on": today.isoformat(),
                            "mark": rows["place_id"].map(done), "name": rows["name"],
                            "city": rows["city"], "domain": rows["domain"], "form_url": rows["form_url"]})
        new[SENT_COLS].to_csv(sent_path, mode="a", header=not os.path.exists(sent_path), index=False)
        counts["moved_to_sent"] = len(new)
        already |= set(new["place_id"])

    # 2. Who may be contacted
    m = _read(os.path.join(home, "LEADS_MASTER.csv"))
    if m.empty:
        return counts
    for c in ("Funnel", "Has_Form", "Has_Social_Only", "website", "Website", "Clean_Name", "name", "city",
              "search_category", "rating", "user_ratings_total", "Lead_Score", "Do_Not_Contact"):
        if c not in m.columns:
            m[c] = ""
    m["site"] = m["website"].where(m["website"] != "", m["Website"])
    m["domain"] = m["site"].apply(domain_of)
    dnc = set()
    p = os.path.join(home, "0_do_not_contact.csv")
    if os.path.exists(p):
        dnc = {l.strip().lower() for l in open(p, encoding="utf-8") if "@" in l}
    blocked_domains = {d[1:] for d in dnc if d.startswith("@")} | {d.split("@")[-1] for d in dnc}
    emailed = set(_read(os.path.join(home, "0_sent_log.csv")).get("place_id", pd.Series(dtype=str)))
    pool = m[(m["Funnel"] == "phone") & (m["Has_Form"].str.lower() == "yes")
             & (m["Has_Social_Only"].str.lower() != "true") & (m["site"] != "")
             & ~m["place_id"].isin(already | emailed) & ~m["domain"].isin(blocked_domains)
             & (m["Do_Not_Contact"].str.lower().isin(["", "false", "0", "no"]))]
    pool = pool.assign(_score=pd.to_numeric(pool["Lead_Score"], errors="coerce").fillna(0),
                       _rev=pd.to_numeric(pool["user_ratings_total"], errors="coerce").fillna(0))
    pool = pool.sort_values(["_score", "_rev"], ascending=False)

    # 3. Look at new websites (a few per run)
    retry_before = (today - dt.timedelta(days=RETRY_AFTER_DAYS)).isoformat()
    final = checked[(checked["result"] != "site down") | (checked["checked_on"] > retry_before)]
    seen = set(final["place_id"])
    todo = pool[~pool["place_id"].isin(seen)]
    new_rows = []
    for _, r in todo.head(max_new).iterrows():
        name = r["Clean_Name"] or r["name"]
        row = {"place_id": r["place_id"], "checked_on": today.isoformat(), "name": name, "city": r["city"],
               "website": r["site"], "domain": r["domain"], "form_url": "", "form_kind": "", "robot_check": "",
               "problem": "", "message": "", "result": ""}
        try:
            facts = look_at_site(r["site"], get, today.year)
        except Exception as e:
            row["result"] = "site down"
            counts["site_down"] += 1
            log(f"[contact forms] {name}: site not reachable ({type(e).__name__})")
            new_rows.append(row)
            continue
        row.update(form_url=facts["form_url"], form_kind=facts["form_kind"], robot_check=facts["robot_check"])
        if facts["public_body"]:                     # run by the state or a council: not a customer
            row["result"] = "public body"
            new_rows.append(row)
            continue
        if not facts["form_url"]:
            row["result"] = "no form found"
            counts["no_form"] += 1
            new_rows.append(row)
            continue
        score = lcp = None
        try:
            result = speed(facts["home_url"])
            score, lcp = speed_numbers(result)
            os.makedirs(os.path.join(home, "lighthouse_json"), exist_ok=True)
            safe = re.sub(r"[^a-zA-Z0-9_-]", "_", str(r["place_id"]).strip())[:80]
            with open(os.path.join(home, "lighthouse_json", f"{safe}.json"), "w", encoding="utf-8") as f:
                json.dump(result, f, separators=(",", ":"))
        except Exception as e:
            log(f"[contact forms] {name}: speed test failed ({type(e).__name__}) — using the page checks only")
        problem = choose_problem(score, lcp, facts, today.year)
        if not problem:
            row["result"] = "no clear problem"
            counts["no_problem"] += 1
            new_rows.append(row)
            continue
        row.update(problem=problem, result="listed",
                   message=message(name, r["search_category"], r["city"], r["rating"], r["user_ratings_total"],
                                   problem))
        counts["listed_new"] += 1
        new_rows.append(row)
    counts["checked"] = len(new_rows)
    if new_rows:
        pd.DataFrame(new_rows)[CHECKED_COLS].to_csv(checked_path, mode="a", header=not os.path.exists(checked_path),
                                                     index=False)
        checked = _read(checked_path)

    # 4. Write the phone list: everything listed, not done, still allowed
    latest = checked.drop_duplicates("place_id", keep="last")
    allowed = set(pool["place_id"])
    show = latest[(latest["result"] == "listed") & latest["place_id"].isin(allowed)]
    show = show.set_index("place_id").reindex([p for p in pool["place_id"] if p in set(show["place_id"])]).reset_index()
    write_list(list_path, show.to_dict("records"))
    counts["in_list"] = len(show)
    settled = latest[(latest["result"] != "site down") | (latest["checked_on"] > retry_before)]
    counts["left_to_check"] = int((~pool["place_id"].isin(set(settled["place_id"]))).sum())
    return counts


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "merge":
        print(f"[contact forms] ticks kept from the phone during this run: {merge_done(sys.argv[2], sys.argv[3])}")
