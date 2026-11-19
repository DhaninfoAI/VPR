"""Batch 03 - AZ / CO / AL / AR cities and counties in the top 200 (Claude manual research, Nov 2026).

Statewide searches found registries only in: AZ - Phoenix (large/non-residential only), Bisbee, Bullhead City,
Huachuca City; CO - Aurora, Pueblo, Lakewood (commercial), Greeley (vacant building rules), Jefferson County
(unincorporated); AL - Anniston, plus 2026 enabling law for Class 1 cities (Birmingham); AR - Pine Bluff.
Cities below with no registry found are recorded as "No" (Medium), with the code-of-ordinances link the operators
used, so the answer can be verified.
"""
import json
from pathlib import Path

from helpers import rule, save

HINTS = {(c["state"], c["city"]): c for c in json.loads((Path(__file__).parent / "jurisdictions.json").read_text())["cities"]}

AZ_NOTE = ("Arizona surveys found registries only in Phoenix (large/non-residential properties), Bisbee, Bullhead City "
           "and Huachuca City; a 2026 bill (HB 2716) would expressly authorize city vacant-building registries.")
CO_NOTE = ("Colorado surveys found registries in Aurora, Pueblo, Lakewood (commercial), Greeley and unincorporated "
           "Jefferson County only.")
AL_NOTE = ("Alabama: a 2026 law (HB 315) authorizes Class 1 municipalities (Birmingham) to adopt registries; Anniston "
           "has one. No registry was found for this city.")
AR_NOTE = "Arkansas: Pine Bluff has a vacant building registration article; no registry was found for this city."
NOTE = {"AZ": AZ_NOTE, "CO": CO_NOTE, "AL": AL_NOTE, "AR": AR_NOTE}
SURVEY = {
    "AZ": "https://12news.com/article/news/local/valley/owners-vacant-phoenix-properties-must-register-city-face-penalties/75-49378a78-582b-45ca-9060-4cde394f6750",
    "CO": "https://blog.safeguardproperties.com/vpr-ordinance-colorado-new-jersey",
    "AL": "https://www.usfn.org/news/new-alabama-vacant-property-legislation-may-impact-reo-properties-in-birmingham",
    "AR": "https://www.cityofpinebluff-ar.gov/plugins/show_image.php?id=1501",
}

NO_CITIES = {
    "AZ": [("Buckeye", "City"), ("Surprise", "City"), ("Tucson", "City"), ("Mesa", "City"), ("Avondale", "City"),
           ("Maricopa", "City"), ("Goodyear", "City"), ("Gilbert", "Town"), ("Yuma", "City"), ("Glendale", "City"),
           ("Peoria", "City"), ("Chandler", "City"), ("El Mirage", "City"), ("Florence", "Town"), ("Casa Grande", "City"),
           ("Tolleson", "City"), ("Kingman", "City")],
    "CO": [("Colorado Springs", "City"), ("Commerce City", "City"), ("Fountain", "City"), ("Thornton", "City"),
           ("Brighton", "City"), ("Castle Rock", "Town"), ("Grand Junction", "City"), ("Parker", "Town"),
           ("Elizabeth", "Town"), ("Littleton", "City")],
    "AL": [("Mobile", "City"), ("Montgomery", "City"), ("Daphne", "City"), ("Tuscaloosa", "City"),
           ("Enterprise", "City"), ("Odenville", "City")],
    "AR": [("Little Rock", "City"), ("Hot Springs", "City"), ("Benton", "City")],
}
NO_COUNTIES = {
    "AZ": ["Maricopa", "Pima", "Pinal", "Yuma", "Mohave"],
    "CO": ["El Paso", "Adams", "Arapahoe", "Douglas", "Mesa", "Weld", "Pueblo", "Elbert", "Denver"],
    "AL": ["Mobile", "Montgomery", "Baldwin", "Jefferson", "Tuscaloosa", "Coffee", "St Clair"],
    "AR": ["Pulaski", "Garland", "Saline"],
}

entries = []
for st, cities in NO_CITIES.items():
    for name, label in cities:
        hint = HINTS.get((st, name), {})
        link = (hint.get("operator_links") or [None])[0]
        extra = ""
        if name == "Littleton":
            extra = " Jefferson County's Distressed Real Properties Ordinance applies only to unincorporated areas, not inside Littleton."
        entries.append(rule("city", st, name, f"{label} of {name}", "No", "No",
                            ordinance_name=f"{label} of {name} code of ordinances - no vacant/foreclosed property registration found",
                            ordinance_url=link,
                            summary=f"No vacant or foreclosed property registration requirement was found for the {label} of {name}. {NOTE[st]}{extra}",
                            confidence="Medium",
                            confidence_reason="Statewide surveys and targeted searches found no registry; matches operator records. Code text not directly readable.",
                            source_urls=[u for u in (SURVEY[st], link) if u]))

for st, counties in NO_COUNTIES.items():
    for name in counties:
        entries.append(rule("county", st, name, f"{name} County", "No", "No",
                            applies_in_incorporated_areas="Not applicable",
                            summary=f"No county-level vacant or foreclosed property registration requirement was found for {name} County. {NOTE[st]}",
                            confidence="Medium", confidence_reason="No county ordinance found in statewide surveys or targeted searches.",
                            source_urls=[SURVEY[st]]))

entries += [
    rule("city", "CO", "Denver", "City and County of Denver", "No", "No",
         ordinance_name="Denver Neglected and Derelict Buildings (NADB) ordinance - designation program, not a registration requirement",
         ordinance_url="https://denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/Community-Planning-and-Development/CPD-News-and-Events/CPD-News/2026/Updated-rules-for-neglected-and-abandoned-properties-in-Denver-aim-to-address-neighborhood-eyesores",
         other_requirements=["Properties the city designates as neglected and derelict (including vacant lots) must meet NADB maintenance rules; updated rules effective August 1, 2026",
                             "$5,000 fee per emergency response when 3+ calls for service occur within six months at a designated property"],
         summary="Denver has no general vacant or foreclosed property registration for servicers. Its Neglected and Derelict Buildings program (updated July 2025, rules effective August 1, 2026) applies to properties the city designates as derelict, with fines and response fees.",
         confidence="Medium", confidence_reason="City announcement and news coverage confirm NADB is a designation/enforcement program; matches operator records.",
         source_urls=["https://denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/Community-Planning-and-Development/CPD-News-and-Events/CPD-News/2026/Updated-rules-for-neglected-and-abandoned-properties-in-Denver-aim-to-address-neighborhood-eyesores",
                      "https://www.coloradopolitics.com/2025/07/14/denver-increases-fines-for-owners-of-derelict-properties-1f09e9b0-24e3-50b1-9b7c-c1b31b35199a"]),

    rule("city", "CO", "Greeley", "City of Greeley", "Unclear", "No",
         ordinance_name="Greeley Municipal Code Title 12, Ch. 7 - Vacant and abandoned buildings (amended by Ord. No. 8, 2023)",
         ordinance_url="https://mccmeetingspublic.blob.core.usgovcloudapi.net/greeley-meet-571d2fcafbe2464f9c4e4d0cdeab573d/ITEM-Attachment-003-db8240ef157d466989a16e944f72b40a.pdf",
         other_requirements=["Minimum property maintenance requirements for vacant or abandoned buildings, with consequences for violations"],
         summary="Greeley regulates vacant and abandoned buildings under Title 12, Ch. 7 (amended 2023) with minimum maintenance requirements. Operator records mark Greeley 'Yes', but a registration requirement and fee could not be confirmed - verify with Greeley Code Compliance.",
         confidence="Low", confidence_reason="Ordinance confirmed but its operative registration terms were not readable.",
         source_urls=["https://mccmeetingspublic.blob.core.usgovcloudapi.net/greeley-meet-571d2fcafbe2464f9c4e4d0cdeab573d/ITEM-Attachment-003-db8240ef157d466989a16e944f72b40a.pdf"]),

    rule("city", "CO", "Arvada", "City of Arvada", "No", "No",
         ordinance_name="City of Arvada code - no vacant/foreclosed property registration found",
         ordinance_url="https://www.jeffco.us/DocumentCenter/View/393/Distressed-Real-Properties-Ordinance-PDF",
         summary="No City of Arvada registration ordinance was found. Operator records mark Arvada 'Yes' citing Jefferson County's Distressed Real Properties Ordinance, but county ordinances apply only to unincorporated Jefferson County, not inside Arvada city limits.",
         confidence="Low", confidence_reason="Disagrees with operator records; verify whether operators register Arvada properties with Jefferson County.",
         source_urls=["https://www.jeffco.us/DocumentCenter/View/393/Distressed-Real-Properties-Ordinance-PDF", CO_NOTE and SURVEY["CO"]]),

    rule("city", "AL", "Birmingham", "City of Birmingham", "Unclear", "Unclear",
         registration_trigger="If the city adopts a program under HB 315: within 30 days after the property becomes vacant or within 30 days after assuming ownership (including acquisition through foreclosure).",
         ordinance_name="Alabama Act (2026 HB 315) authorizing Class 1 municipalities to adopt vacant property registration",
         ordinance_url="https://alison.legislature.state.al.us/files/pdf/SearchableInstruments/2026RS/HB315-enr.pdf",
         summary="A 2026 Alabama law (effective April 15, 2026) lets Birmingham adopt a vacant property registry with a citywide database and program administrator, requiring registration within 30 days of vacancy or acquisition (including REO). Whether Birmingham has adopted its ordinance was not confirmed.",
         confidence="Low", confidence_reason="Enabling law confirmed; city adoption not confirmed.",
         source_urls=["https://alison.legislature.state.al.us/files/pdf/SearchableInstruments/2026RS/HB315-enr.pdf",
                      "https://www.usfn.org/news/new-alabama-vacant-property-legislation-may-impact-reo-properties-in-birmingham"]),
]

save("12_batch_03.json", entries)
