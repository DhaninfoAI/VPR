"""State-level research (Claude manual research, Nov 2026) -> research/00_states.json"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

CODES = {
    "AK": "https://www.akleg.gov/basis/statutes.asp", "AL": "https://alison.legislature.state.al.us/code-of-alabama",
    "AR": "https://www.arkleg.state.ar.us/", "AZ": "https://www.azleg.gov/arstitle/",
    "CA": "https://leginfo.legislature.ca.gov/faces/codes.xhtml", "CO": "https://leg.colorado.gov/colorado-revised-statutes",
    "DE": "https://delcode.delaware.gov/", "FL": "http://www.leg.state.fl.us/statutes/",
    "IL": "https://www.ilga.gov/legislation/ilcs/ilcs.asp", "KS": "https://www.ksrevisor.org/",
    "KY": "https://legislature.ky.gov/Law/Statutes/", "MA": "https://malegislature.gov/Laws/GeneralLaws",
    "MI": "https://www.legislature.mi.gov/", "MN": "https://www.revisor.mn.gov/statutes/",
    "NE": "https://nebraskalegislature.gov/laws/browse-statutes.php", "NM": "https://nmonesource.com/",
    "NV": "https://www.leg.state.nv.us/NRS/", "OH": "https://codes.ohio.gov/ohio-revised-code",
    "OR": "https://www.oregonlegislature.gov/bills_laws/Pages/ORS.aspx", "PA": "https://www.legis.state.pa.us/",
    "TN": "https://www.capitol.tn.gov/", "TX": "https://statutes.capitol.texas.gov/",
    "VA": "https://law.lis.virginia.gov/vacode/", "WA": "https://app.leg.wa.gov/rcw/",
    "WI": "https://docs.legis.wisconsin.gov/statutes/",
}
NAMES = {
    "AK": "Alaska", "AL": "Alabama", "AR": "Arkansas", "AZ": "Arizona", "CA": "California", "CO": "Colorado",
    "DE": "Delaware", "FL": "Florida", "IL": "Illinois", "KS": "Kansas", "KY": "Kentucky", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "NE": "Nebraska", "NM": "New Mexico", "NV": "Nevada", "OH": "Ohio",
    "OR": "Oregon", "PA": "Pennsylvania", "TN": "Tennessee", "TX": "Texas", "VA": "Virginia", "WA": "Washington",
    "WI": "Wisconsin",
}
EXTRA = {
    "CA": "California Civil Code 2929.3 lets cities and counties fine the legal owner of a vacant foreclosed property for failing to maintain it, but there is no statewide registration; registration is imposed by individual cities/counties.",
    "IL": "Illinois has no statewide registry; registration is imposed by municipal and county ordinances (e.g. Cook County, Chicago).",
    "MA": "Massachusetts has no statewide registry; several cities have local registration ordinances.",
    "FL": "Florida has no statewide registry; many Florida cities and counties have their own VPR/foreclosure registration ordinances, often administered through third-party platforms.",
    "MI": "Michigan has no statewide registry; registration is imposed locally.",
    "PA": "Pennsylvania has no statewide registry; registration is imposed locally.",
    "OH": "Ohio has no statewide registry; many Ohio cities have local vacant/foreclosed property registration ordinances.",
}
SURVEY = ["https://archive.cuyahogalandbank.org/?p=9018", "https://safeguardproperties.com/?p=9230"]

BLANK = {
    "applies_in_incorporated_areas": "Not applicable", "registration_trigger": None, "who_must_register": None,
    "registration_deadline": None, "registration_form_url": None, "registration_portal_url": None,
    "registration_method": "Not applicable", "third_party_platform": None, "registration_fee": None,
    "renewal_fee": None, "renewal_frequency": None, "additional_links": [], "documents_required": [],
    "other_requirements": [], "penalties": None, "contact_info": None,
}


def no_state(st: str) -> dict:
    n = NAMES[st]
    return {
        **BLANK,
        "jurisdiction_name": f"State of {n}",
        "vacant_registration_required": "No", "foreclosure_registration_required": "No",
        "ordinance_name": f"{n} statutes - no statewide vacant or foreclosed property registration statute identified",
        "ordinance_url": CODES[st],
        "summary": f"No statewide vacant property or foreclosure registration requirement was identified for {n}. "
                   + EXTRA.get(st, "Any registration obligation comes from the city/town or county ordinance.")
                   + " Check the city and county levels.",
        "confidence": "Medium",
        "confidence_reason": "Surveys of statewide registries list only NY, MD, CT, NJ and GA as having statewide frameworks; no statute for this state was found. Absence of a statute cannot be proven by search alone.",
        "source_urls": [CODES[st], *SURVEY],
    }


def entry(st: str, name: str, data: dict) -> dict:
    return {"level": "state", "state": st, "name": name, "display_name": f"State of {name}", "data": data}


entries = [entry(st, NAMES[st], no_state(st)) for st in NAMES]

entries.append(entry("CT", "Connecticut", {
    **BLANK,
    "jurisdiction_name": "State of Connecticut",
    "vacant_registration_required": "No", "foreclosure_registration_required": "Yes",
    "registration_trigger": "Commencement of a residential mortgage foreclosure (recording of the lis pendens), and again when absolute title vests in the foreclosing party/new owner.",
    "who_must_register": "Form 1: the foreclosing plaintiff. Form 2: the party in whom title vests through foreclosure (or the plaintiff updating Form 1).",
    "registration_deadline": "Form 1: filed with the town clerk at the same time the lis pendens is recorded. Form 2: received no later than 15 days after absolute title vests. Changes: within 30 days of the change.",
    "ordinance_name": "Conn. Gen. Stat. Sec. 7-148ii - Registration and maintenance of foreclosed residential properties (amended by Public Act 25-168, eff. 7/1/2025)",
    "ordinance_url": "https://law.justia.com/codes/connecticut/title-7/chapter-98/section-7-148ii",
    "registration_form_url": "https://www.newingtonct.gov/DocumentCenter/View/19603/Foreclosed-Property-Form_1_rev7-1-2025",
    "registration_method": "In person",
    "registration_fee": "$70 per Form 1 registration and per Form 2 / updated registration (forms rev. 7/1/2025; older town guidelines show $60). Paid to the town clerk where the property is located.",
    "renewal_fee": "None (no fee for filing a change in information)",
    "renewal_frequency": "No periodic renewal; update within 30 days of any change",
    "additional_links": [
        {"label": "Registration form 2 (title vested)", "url": "https://www.newingtonct.gov/DocumentCenter/View/19604/Foreclosed-Property-Form_2_rev7-1-2025"},
        {"label": "Foreclosure registration requirements (Waterbury, rev. 7/1/2025)", "url": "https://www.waterburyct.org/filestorage/103431/106404/106408/Foreclosure_Registration_Requirements_rev.7-1-2025.pdf"},
    ],
    "documents_required": [
        "Form 1 (plaintiff, at lis pendens) or Form 2 (when title vests) - the town's version of the state form",
        "Property location: street number, street name, unit",
        "Registrant / plaintiff name (entity or individual), mailing address, telephone and email",
        "Preferred contact method (first class mail or email) and address for communications",
        "If the registrant is out of state: name, address, phone and email of a direct Connecticut contact, if available",
        "Name and contact details of the person/company responsible for maintaining the property (Form 2)",
        "Registration fee ($70) payable to the town",
    ],
    "other_requirements": [
        "File changes in registration information within 30 days (no fee)",
        "The registration is filed with the town clerk and is NOT recorded on the land records",
        "Maintain the property in accordance with municipal ordinances after title vests",
    ],
    "penalties": "Towns may impose fines for failure to register under local ordinance; amounts vary by town (not verified statewide).",
    "contact_info": "Town clerk of the town where the property is located.",
    "summary": "Connecticut requires statewide foreclosure registration under CGS 7-148ii: the foreclosing plaintiff files Form 1 with the town clerk when recording the lis pendens, and the new owner files Form 2 within 15 days after title vests. The fee is $70 per registration (forms revised July 1, 2025). Connecticut has no county government.",
    "confidence": "High",
    "confidence_reason": "Several town clerk guidelines and the 2025 state forms agree on the process; the $70 fee is on 2025 forms, older guides show $60.",
    "source_urls": [
        "https://law.justia.com/codes/connecticut/title-7/chapter-98/section-7-148ii",
        "https://www.waterburyct.org/filestorage/103431/106404/106408/Foreclosure_Registration_Requirements_rev.7-1-2025.pdf",
        "https://www.newingtonct.gov/DocumentCenter/View/19604/Foreclosed-Property-Form_2_rev7-1-2025",
        "https://glastonburyct.gov/home/showpublisheddocument/22474/636476371271200000",
    ],
}))

entries.append(entry("NY", "New York", {
    **BLANK,
    "jurisdiction_name": "State of New York",
    "vacant_registration_required": "Yes", "foreclosure_registration_required": "No",
    "registration_trigger": "A 1-4 family residential property subject to a mortgage is determined to be vacant and abandoned (three consecutive inspections 25-35 days apart showing no occupancy) after the loan becomes delinquent.",
    "who_must_register": "Mortgagee / mortgage servicer. Not REO, vacant lots, commercial property or property not subject to a mortgage.",
    "registration_deadline": "Report to the DFS registry once the property is determined vacant and abandoned; post a notice on the property within 7 business days of the determination; update the registry within 30 days of any material change.",
    "ordinance_name": "NY RPAPL Sec. 1308 (maintenance) and Sec. 1310 (DFS vacant and abandoned property registry); 3 NYCRR Part 422",
    "ordinance_url": "https://nysenate.gov/legislation/laws/RPA/1310",
    "registration_portal_url": "https://myportal.dfs.ny.gov",
    "registration_method": "Online portal",
    "registration_fee": "No fee identified for the DFS registry.",
    "renewal_frequency": "Quarterly compliance reporting; update within 30 days of a material change",
    "additional_links": [
        {"label": "DFS maintenance obligations guidance", "url": "https://www.dfs.ny.gov/apps_and_licensing/mortgage_companies/zombie_property_maintenance_obligations"},
        {"label": "RPAPL 1308", "url": "https://nysenate.gov/legislation/laws/RPA/1308"},
    ],
    "documents_required": [
        "DFS Portal account for the mortgagee/servicer",
        "Property address (1-4 family residential, subject to a mortgage)",
        "Loan and servicer identification and servicer contact information",
        "Dates and results of the vacancy inspections supporting the vacant-and-abandoned determination",
        "Quarterly compliance reports on securing and maintaining the property",
    ],
    "other_requirements": [
        "Inspect properties securing delinquent loans and determine occupancy",
        "Within 7 business days of a vacancy determination, post a notice on the property with the servicer's contact information",
        "Secure and maintain the property until foreclosure sale/REO",
        "Update the registry within 30 days of a material change (foreclosure completed, REO, demolition, lien release, servicing transfer)",
    ],
    "penalties": "Civil penalty of up to $500 per day per property (DFS enforcement; e.g. a $100,000 consent order against a servicer).",
    "contact_info": "NY Department of Financial Services - https://www.dfs.ny.gov/contact_us/main",
    "summary": "New York requires mortgagees/servicers of 1-4 family mortgaged properties that become vacant and abandoned to report them to the statewide DFS Vacant and Abandoned Property Registry (RPAPL 1308/1310), post a notice, maintain the property, and update the registry within 30 days of material changes. Many NY cities also have local registries.",
    "confidence": "High",
    "confidence_reason": "Confirmed on DFS official guidance; the exact data fields are not published on the public page.",
    "source_urls": [
        "https://www.dfs.ny.gov/apps_and_licensing/mortgage_companies/zombie_property_maintenance_obligations",
        "https://nysenate.gov/legislation/laws/RPA/1310", "https://riker.com/?p=3867",
    ],
}))

entries.append(entry("MD", "Maryland", {
    **BLANK,
    "jurisdiction_name": "State of Maryland",
    "vacant_registration_required": "No", "foreclosure_registration_required": "Yes",
    "registration_trigger": "Mailing a Notice of Intent to Foreclose (NOI); filing a foreclosure action; purchase of a residential property at a foreclosure sale.",
    "who_must_register": "Mortgage holders/servicers (NOI and Notice of Foreclosure Filing) and foreclosure purchasers (initial and final registration).",
    "registration_deadline": "NOI copy within 5 business days of mailing; Notice of Foreclosure Filing within 7 days of filing the order to docket/complaint; purchaser initial registration within 30 days after the sale; final registration within 30 days after the deed is recorded.",
    "ordinance_name": "Md. Code, Real Property Sec. 14-126.1 (Foreclosed Property Registry) and Sec. 7-105.1",
    "ordinance_url": "https://law.justia.com/codes/maryland/2013/article-grp/section-14-126",
    "registration_portal_url": "https://dllr.state.md.us/ForeclosureSystems",
    "registration_method": "Online portal",
    "registration_fee": "Foreclosure purchaser initial registration $50 if timely, $100 if late; final registration no fee. No fee identified for the NOI submission.",
    "renewal_frequency": "No periodic renewal",
    "additional_links": [
        {"label": "FRS user guide", "url": "https://www.dllr.state.md.us/ForeclosureSystems/Documents/FRS_User_Guide.pdf"},
        {"label": "Company administrator guide", "url": "https://www.dllr.state.md.us/ForeclosureSystems/Documents/Company_Administrator_Guide.pdf"},
    ],
    "documents_required": [
        "Approved Foreclosure Registration System (FRS) company and user account",
        "Copy of the Notice of Intent to Foreclose as mailed (NOI submission)",
        "Notice of Foreclosure Filing details (case/docket information)",
        "Property address and county",
        "Purchaser/registrant name, address and contact details (purchaser registration)",
        "Foreclosure sale date and, for final registration, deed recording information",
        "Registration fee ($50, or $100 if late) for the purchaser initial registration",
    ],
    "other_requirements": ["Local jurisdictions (e.g. Baltimore City, Prince George's County) may have additional vacant-property rules; check the county/city level."],
    "penalties": "Late purchaser registration fee $100; other statutory penalties not verified.",
    "contact_info": "Maryland Office of Financial Regulation (Department of Labor) - https://dllr.state.md.us/ForeclosureSystems",
    "summary": "Maryland requires statewide foreclosure registration through the Department of Labor's Foreclosure Registration System: NOIs within 5 business days of mailing, Notices of Foreclosure Filing within 7 days, and foreclosure purchaser registrations within 30 days of sale ($50, $100 if late) and of deed recording (no fee).",
    "confidence": "High",
    "confidence_reason": "Confirmed on Maryland Department of Labor advisories; confirm current fees in the FRS.",
    "source_urls": [
        "https://dllr.state.md.us/ForeclosureSystems",
        "https://www.dllr.state.md.us/finance/advisories/advisory-frsystemreq.pdf",
        "https://dllr.state.md.us/finance/industry/forereghandout.pdf",
    ],
}))

for st, n, extra, url in [
    ("NJ", "New Jersey",
     "New Jersey law (P.L.2014, c.35, N.J.S.A. 40:48-2.12s et seq.) lets municipalities adopt ordinances requiring creditors to register vacant and abandoned residential properties in foreclosure and sets what those ordinances must contain; the registration itself is filed with the municipality. Typical municipal fees are $500 initial, $1,000 first renewal, $1,500 later renewals.",
     "https://ecode360.com/36247701"),
    ("GA", "Georgia",
     "Georgia law (O.C.G.A. 44-14-14) sets the framework for local vacant/foreclosed real property registries and limits what counties and cities may require; registration is filed with the county or city that adopted a registry (fees are commonly $100).",
     "https://law.justia.com/codes/georgia/2014/title-44/chapter-14/article-1/section-44-14-14"),
]:
    entries.append(entry(st, n, {
        **BLANK,
        "jurisdiction_name": f"State of {n}",
        "vacant_registration_required": "No", "foreclosure_registration_required": "No",
        "ordinance_name": "State enabling statute for local registration (not a state-level registration)",
        "ordinance_url": url,
        "summary": f"No registration is filed with the State of {n} itself. {extra} Check the city and county levels.",
        "confidence": "Medium",
        "confidence_reason": "State law frames local registries; the state does not run its own registry.",
        "source_urls": [url, *SURVEY],
    }))

(HERE / "research" / "00_states.json").write_text(json.dumps(entries, indent=1), encoding="utf-8")
print(len(entries), "state entries")
