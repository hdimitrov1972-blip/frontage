"""Suspect-address rules on real cases from Limerick, Ennis, Waterford and Kilkenny.
Expected answers are what a person decided by checking the websites ('' = needs a person)."""
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import suspects  # noqa: E402

CASES = [  # name, website, email, city, expected
    ("Rive Gauche Kilkenny", "http://www.rivegauche.ie/", "reservations@rivegauchekk.com", "Kilkenny", "yes"),
    ("Lanigan's Bar", "https://www.lanigans.ie/", "your@email.com", "Kilkenny", "no"),
    ("Lyla's Kilkenny", "https://www.lylas.ie/", "info@cloverockdesign.ie", "Kilkenny", "no"),
    ("The Grapevine", "http://www.grapevinetapasbar.ie/", "Booking@grapevinetapsbar.ie", "Kilkenny", ""),
    ("Anatolia Cafe & Restaurant", "https://anatoliarestaurant.ie/", "info@enits.ie", "Kilkenny", ""),
    ("The Blackberry Cafe", "http://www.blackberrycafe.ie/", "info@vaughanprint.com", "Kilkenny", "no"),
    ("The Dylan Whisky Bar", "http://www.thedylanwhiskybar.com/", "tastings@thedylanwhiskybar.ie", "Kilkenny", "yes"),
    ("Butter Slip", "https://www.buildingsofireland.ie/x", "niah@housing.gov.ie", "Kilkenny", "no"),
    ("The Pantry MacDonagh Junction", "https://thepantryofficial.com/", "info@pantryireland.ie", "Kilkenny", "yes"),
    ("The Castle tea rooms", "http://kilkennycastle.ie/", "kilkennycastleinfo@opw.ie", "Kilkenny", "no"),
    ("Rustiq Salon Kilkenny", "https://rustiqsalon.com/", "igor@digitalsalongroup.com", "Kilkenny", "no"),
    ("Ailish Laser and Skincare", "http://ailishlaserskincare.ie/", "info@ailishbeauty.ie", "Kilkenny", "yes"),
    ("Sassy & Classy Aesthetic Studio", "https://sassynclassystudio.ie/", "nuage_beauty@mail.com", "Kilkenny", ""),
    ("Troysgate House", "https://troysgatehouse.com-ireland.com/", "info@alexiahotels.com", "Kilkenny", ""),
    ("Kilkenny Active Health & Fitness Club", "https://www.activeclub.ie/hotel-kilkenny",
     "ferrycarrigactive@ferrycarrighotel.com", "Kilkenny", ""),
    ("Henry's Bistro & Wine Bar", "https://henrysbistroandwinebar.ie/", "bookings@henrysofennis.ie", "Ennis", "yes"),
    ("Treacy's West County Hotel", "https://www.treacyswestcounty.com/", "info@twcennis.com", "Ennis", "yes"),
    ("Cruises Bar Ennis", "http://www.queenshotelennis.com/cruises_pub.html", "reception@queensennis.com", "Ennis", "yes"),
    ("Terrace bar", "https://www.strandhotellimerick.ie/terrace-bar-limerick.html", "info@strandlimerick.ie", "Limerick", "yes"),
    ("Sweet N Green", "http://www.sweetngreen.ie/", "info@sweetngreen.com", "Limerick", "yes"),
    ("John O'Sullivan Park", "http://www.activeennis.ie/", "tforde@clarecoco.ie", "Ennis", "no"),
    ("Planet Entertainment Centre Ennis", "https://theplanet.ie/ennis/", "info@planetathlone.ie", "Ennis", ""),
    ("Strasburgh Manor", "http://www.strasburghmanor.com/", "info@countryholidays.com", "Ennis", ""),
    ("Treacys Hotel Waterford", "", "res@thwaterford.com", "Waterford", "yes"),
    ("Changarro", "", "info@burritoheaven.ie", "Waterford", ""),
    ("Coach House Coffee", "", "info@mysite.com", "Waterford", "no"),
    ("Seagull Bakery", "", "info@seagullbakery.ie", "Waterford", "yes"),
    ("Shush Waterford", "", "info@digicolphotography.com", "Waterford", "no"),
    ("Exhale & Relax Skin + Body", "", "igor@digitalsalongroup.com", "Waterford", "no"),
    ("Ashleigh House B&B", "", "info@waterfordbandb.ie", "Waterford", ""),
    ("SETU Arena", "", "novushr.wd@setu.ie", "Waterford", "no"),
    ("Amber Springs Hotel and Health Spa", "", "info@ambersprings.ie", "Wexford", "yes"),
    ("Whitford House Hotel Wexford", "", "info@whitford.ie", "Wexford", "yes"),
    ("Signal Box Coffee", "", "signalboxcoffee@gmail.com", "Waterford", "yes"),
]


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    assert cond, name


wrong = []
for name, site, em, city, want in CASES:
    got, why = suspects.decide(name, site, em, city)
    if got != want:
        wrong.append(f"{name}: got {got or 'unclear'} ({why}), expected {want or 'unclear'}")
print("\n".join(wrong))
check(f"rules agree with the person on all {len(CASES)} real cases", not wrong)
risky = [c for c in CASES if c[4] != "yes" and suspects.decide(*c[:4])[0] == "yes"]
check("rules never say yes where a person did not", not risky)

# end to end on a LEADS_MASTER: answers applied, nothing overwritten, unclear left for the weekly check
home = tempfile.mkdtemp()
os.makedirs(home + "/latest")
rows = []
for i, (name, site, em, city, want) in enumerate(CASES):
    rows.append({"place_id": f"p{i}", "Clean_Name": name, "Website": site, "Best_Email": em, "city": city,
                 "Funnel": "email", "Email_Approved": "False", "Status_Outreach": "pending", "Send_Ready": "False",
                 "Send_Block_Reason": "email address not approved (suspect — needs review)", "Report_File": f"r{i}.pdf"})
rows.append({"place_id": "ok1", "Clean_Name": "Fine", "Best_Email": "info@fine.ie", "Funnel": "email",
             "Email_Approved": "True", "Status_Outreach": "pending", "Send_Ready": "True"})
pd.DataFrame(rows).to_csv(home + "/LEADS_MASTER.csv", index=False)
# a person already said NO to Rive Gauche (p0) and YES to Anatolia (p4)
pd.DataFrame([{"place_id": "p0", "Approve": "no", "Hint": ""}, {"place_id": "p4", "Approve": "yes", "Hint": ""}]
             ).to_csv(home + "/2B_suspect_review.csv", index=False)
c = suspects.run(home)
m = pd.read_csv(home + "/LEADS_MASTER.csv", dtype=str).fillna("").set_index("place_id")
check("a person's 'no' wins over the rules", m.at["p0", "Funnel"] == "phone" and "you rejected" in m.at["p0", "Review_Note"])
check("a person's 'yes' approves and makes the lead ready", m.at["p4", "Email_Approved"] == "True"
      and m.at["p4", "Send_Ready"] == "True")
check("rules 'yes' -> approved and ready", m.at["p6", "Email_Approved"] == "True" and m.at["p6", "Send_Ready"] == "True")
check("rules 'no' -> phone list", m.at["p1", "Funnel"] == "phone" and m.at["p1", "Call_Status"] == "pending")
check("unclear stays held back", m.at["p3", "Email_Approved"] == "False" and m.at["p3", "Funnel"] == "email")
check("approved leads untouched", m.at["ok1", "Send_Ready"] == "True")
rv = pd.read_csv(home + "/2B_suspect_review.csv", dtype=str).fillna("")
check("review file: old answers kept, new rows added once", len(rv) == len(CASES)
      and rv.loc[rv.place_id == "p0", "Approve"].iloc[0] == "no")
check("unclear rows marked for the weekly check", rv.loc[rv.place_id == "p3", "Hint"].iloc[0].startswith("weekly check"))
check("latest/ copy updated too", os.path.exists(home + "/latest/LEADS_MASTER.csv"))
# weekly answers file from the chat
pd.DataFrame([{"place_id": "p3", "Approve": "yes"}]).to_csv(home + "/2B_answers_2026-11-08.csv", index=False)
suspects.run(home)
m = pd.read_csv(home + "/LEADS_MASTER.csv", dtype=str).fillna("").set_index("place_id")
check("weekly answers file is applied", m.at["p3", "Email_Approved"] == "True")
# a person flips a rules answer inside the review file
rv = pd.read_csv(home + "/2B_suspect_review.csv", dtype=str).fillna("")
rv.loc[rv.place_id == "p11", "Approve"] = "no"
rv.to_csv(home + "/2B_suspect_review.csv", index=False)
m0 = pd.read_csv(home + "/LEADS_MASTER.csv", dtype=str).fillna("")
m0.loc[m0.place_id == "p11", ["Email_Approved", "Funnel"]] = ["False", "email"]
m0.to_csv(home + "/LEADS_MASTER.csv", index=False)
suspects.run(home)
m = pd.read_csv(home + "/LEADS_MASTER.csv", dtype=str).fillna("").set_index("place_id")
check("a person's change to a rules answer wins", m.at["p11", "Funnel"] == "phone")
print("\nALL SUSPECT TESTS PASSED")
