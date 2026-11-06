"""Dead-domain check before sending: catches addresses that would bounce because the business's
email domain no longer exists or cannot receive mail.

For every pending email lead in LEADS_MASTER.csv whose address is on the business's own domain
(not Gmail, Hotmail...), it looks up the domain's mail servers (MX) once, and the website address (A)
when there is no MX. A domain is "dead" only when the answer is certain:
  - the domain does not exist (NXDOMAIN), or
  - it has no MX and no A/AAAA record, or
  - it publishes a "null MX" (says it accepts no mail).
Timeouts and server errors are NOT treated as dead: that lead stays and is checked again next time.

Dead addresses are added to 0_do_not_contact.csv, which the sender already skips.
Results are kept in 0_domain_check.csv so each domain is looked up at most once every 30 days.
"""
import datetime as dt
import os

import pandas as pd

from replies import FREE_MAIL, clean_address

RECHECK_DAYS = 30
CANARIES = ("google.com", "gmail.com", "outlook.com")   # must always look alive, or DNS is broken
MAX_DEAD_SHARE = 0.3        # more than 30% dead in one run = something is wrong: block nobody
COLS = ["domain", "checked_on", "result", "detail"]


def _read(path):
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()


def lookup(domain):
    """Returns ("ok" | "dead" | "unknown", detail). Uses dnspython."""
    import dns.exception
    import dns.resolver

    r = dns.resolver.Resolver()
    r.lifetime = 8
    try:
        mx = r.resolve(domain, "MX")
        hosts = [str(x.exchange).rstrip(".") for x in mx]
        if hosts and all(h == "" for h in hosts):
            return "dead", "null MX (accepts no mail)"
        return "ok", "MX " + ", ".join(sorted(hosts)[:2])
    except dns.resolver.NXDOMAIN:
        return "dead", "domain does not exist"
    except dns.resolver.NoAnswer:
        pass                                    # no MX: mail goes to the A record, if there is one
    except (dns.resolver.NoNameservers, dns.exception.Timeout, dns.resolver.LifetimeTimeout) as e:
        return "unknown", type(e).__name__
    except Exception as e:
        return "unknown", type(e).__name__
    for rtype in ("A", "AAAA"):
        try:
            r.resolve(domain, rtype)
            return "ok", f"no MX, has {rtype}"
        except dns.resolver.NXDOMAIN:
            return "dead", "domain does not exist"
        except dns.resolver.NoAnswer:
            continue
        except Exception as e:
            return "unknown", type(e).__name__
    return "dead", "no MX and no A record"


def pending_addresses(home):
    m = _read(os.path.join(home, "LEADS_MASTER.csv"))
    if m.empty or "Best_Email" not in m:
        return []
    for c in ("Funnel", "Status_Outreach"):
        if c not in m:
            m[c] = ""
    rows = m[(m["Funnel"] == "email") & (m["Status_Outreach"].str.lower() == "pending")]
    return sorted({clean_address(e) for e in rows["Best_Email"] if "@" in str(e)})


def run(home, today=None, resolve=None, log=print):
    today = today or dt.date.today()
    resolve = resolve or lookup
    counts = {"checked": 0, "dead_domains": 0, "added_to_do_not_contact": 0, "unknown": 0, "skipped": ""}
    if any(resolve(c)[0] != "ok" for c in CANARIES):
        counts["skipped"] = "DNS not answering normally (google.com/gmail.com/outlook.com failed)"
        log(f"[domain check] skipped: {counts['skipped']}")
        return counts
    addresses = [a for a in pending_addresses(home) if a.split("@")[-1] not in FREE_MAIL]
    path = os.path.join(home, "0_domain_check.csv")
    cache = _read(path)
    fresh = {}
    if len(cache):
        recent = cache[pd.to_datetime(cache["checked_on"], errors="coerce")
                       >= pd.Timestamp(today - dt.timedelta(days=RECHECK_DAYS))]
        recent = recent[recent["result"] != "unknown"]
        fresh = dict(zip(recent["domain"], recent["result"]))
    new_rows = []
    for dom in sorted({a.split("@")[-1] for a in addresses} - set(fresh)):
        result, detail = resolve(dom)
        fresh[dom] = result
        counts["checked"] += 1
        counts["unknown"] += result == "unknown"
        new_rows.append({"domain": dom, "checked_on": today.isoformat(), "result": result, "detail": detail})
    n_dead = sum(r["result"] == "dead" for r in new_rows)
    if len(new_rows) >= 10 and n_dead / len(new_rows) > MAX_DEAD_SHARE:
        counts["skipped"] = f"{n_dead} of {len(new_rows)} domains dead looks wrong — nothing blocked, nothing saved"
        log(f"[domain check] skipped: {counts['skipped']}")
        return counts
    if new_rows:
        pd.DataFrame(new_rows)[COLS].to_csv(path, mode="a", header=not os.path.exists(path), index=False)

    dead = [a for a in addresses if fresh.get(a.split("@")[-1]) == "dead"]
    counts["dead_domains"] = len({a.split("@")[-1] for a in dead})
    dnc_path = os.path.join(home, "0_do_not_contact.csv")
    have = set()
    if os.path.exists(dnc_path):
        have = {l.strip().lower() for l in open(dnc_path, encoding="utf-8") if "@" in l}
    else:
        open(dnc_path, "w").write("email_or_domain\n")
    add = sorted(set(dead) - have)
    if add:
        with open(dnc_path, "a", encoding="utf-8") as f:
            for a in add:
                f.write(a + "\n")
        for a in add:
            log(f"[domain check] dead: {a}")
    counts["added_to_do_not_contact"] = len(add)
    return counts
