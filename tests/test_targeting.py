"""Small places first: hotels, chains and big venues go to the back of the email queue.   python tests/test_targeting.py"""
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import targeting  # noqa: E402


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


ROWS = [  # place_id, name, category, reviews, email, status
    ("p1", "Kealy's Cafe", "cafes", "120", "hello@kealyscafe.ie", "pending"),
    ("p2", "The Grand Hotel Malahide", "hotels", "3323", "info@thegrand.ie", "pending"),
    ("p3", "Heather View Guest House", "hotels", "80", "enquiries@heatherview.com", "pending"),
    ("p4", "Abbey Lodge", "hotels", "1500", "info@abbeylodge.ie", "pending"),
    ("p5", "FUSE Gym Bray", "gyms", "436", "bray@fusegym.ie", "pending"),
    ("p6", "FUSE Gym Waterford", "gyms", "488", "waterford@fusegym.ie", "sent"),
    ("p7", "Johnnie Fox's Pub", "bars", "13212", "info@johnniefoxs.com", "pending"),
    ("p8", "Swords Pavilions Shopping Centre", "cafes", "900", "desk@pavilions.ie", "pending"),
    ("p9", "Moldova Bakery", "bakeries", "200", "careers@moldova.ie", "pending"),
    ("p10", "The Ivy Asia", "restaurants", "800", "groupdining@theivy-collection.com", "pending"),
    ("p11", "Kettles Country House", "restaurants", "500", "weddings@kettleshotel.ie", "pending"),
    ("p12", "Old Mill Hotel", "hotels", "300", "info@oldmill.ie", "sent"),
]
home = tempfile.mkdtemp()
pd.DataFrame([{"place_id": p, "name": n, "search_category": c, "user_ratings_total": r, "Best_Email": e,
               "Funnel": "email", "Status_Outreach": s, "Send_Ready": "True", "Lead_Score": "5"}
              for p, n, c, r, e, s in ROWS]).to_csv(home + "/LEADS_MASTER.csv", index=False)

c = targeting.run(home, log=lambda m: None)
m = pd.read_csv(home + "/LEADS_MASTER.csv", dtype=str, keep_default_na=False).set_index("place_id")
tier = m["Target_Tier"].to_dict()
check("small café first", tier["p1"] == "1")
check("hotel by name -> back", tier["p2"] == "2" and m.at["p2", "Target_Reason"] == "hotel")
check("small guest house in the hotel search stays in front", tier["p3"] == "1")
check("'hotels' search with over 1,000 reviews -> back", tier["p4"] == "2")
check("chain: same email domain as another place -> back", tier["p5"] == "2" and "chain" in m.at["p5", "Target_Reason"])
check("big venue by reviews -> back", tier["p7"] == "2" and m.at["p7", "Target_Reason"] == "big venue")
check("shopping centre -> back", tier["p8"] == "2")
check("careers@ address -> back", tier["p9"] == "2")
check("group address -> back", tier["p10"] == "2")
check("'hotel' in the email domain -> back", tier["p11"] == "2")
check("already sent rows are not touched", tier["p6"] == "" and tier["p12"] == "")
check("nobody blocked: Send_Ready unchanged", (m["Send_Ready"] == "True").all())
check("counts", c["front"] == 2 and c["back"] == 8)
check("second run: nothing changes", targeting.run(home, log=lambda m: None)["changed"] == 0)
c = targeting.run(home, enabled=False, log=lambda m: None)
m = pd.read_csv(home + "/LEADS_MASTER.csv", dtype=str, keep_default_na=False)
check("switched off: one queue again (tiers cleared)", (m["Target_Tier"] == "").all() and c["back"] == 0)
print("\nALL TARGETING TESTS PASSED")
