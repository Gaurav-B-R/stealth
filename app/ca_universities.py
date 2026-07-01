"""Canadian university/college registry (email domain -> institution) for signup auto-fill.

Mirrors the US `us_universities` data and the Australian `au_universities` seed, but
for Canada and *code-seeded* (the US list is loaded externally in prod). Rows live in
the same `us_universities` table — a legacy name that is really a "known university
email domains" map — tagged with `country_code='CA'`. The signup auto-fill
(`/api/auth/university-by-email`) looks up by the full email domain, so well-known
student subdomains are included so e.g. name@mail.utoronto.ca resolves too.

Designated Learning Institutions (DLIs) for a Canadian Study Permit include both
universities and public colleges, so major colleges are included alongside universities.

Idempotent: `seed_ca_universities` only inserts domains not already present.
"""
from sqlalchemy.orm import Session

from app import models

# (email_domain, institution_name, location) — major Canadian universities and public
# colleges, plus common student subdomains for the largest schools.
CA_UNIVERSITIES: list[tuple[str, str, str]] = [
    # U15 research universities
    ("utoronto.ca", "University of Toronto", "Toronto, ON"),
    ("mail.utoronto.ca", "University of Toronto", "Toronto, ON"),
    ("ubc.ca", "University of British Columbia", "Vancouver, BC"),
    ("student.ubc.ca", "University of British Columbia", "Vancouver, BC"),
    ("mail.ubc.ca", "University of British Columbia", "Vancouver, BC"),
    ("mcgill.ca", "McGill University", "Montreal, QC"),
    ("mail.mcgill.ca", "McGill University", "Montreal, QC"),
    ("ualberta.ca", "University of Alberta", "Edmonton, AB"),
    ("umontreal.ca", "Université de Montréal", "Montreal, QC"),
    ("mcmaster.ca", "McMaster University", "Hamilton, ON"),
    ("uwaterloo.ca", "University of Waterloo", "Waterloo, ON"),
    ("uwo.ca", "Western University", "London, ON"),
    ("ucalgary.ca", "University of Calgary", "Calgary, AB"),
    ("queensu.ca", "Queen's University", "Kingston, ON"),
    ("uottawa.ca", "University of Ottawa", "Ottawa, ON"),
    ("dal.ca", "Dalhousie University", "Halifax, NS"),
    ("umanitoba.ca", "University of Manitoba", "Winnipeg, MB"),
    ("myumanitoba.ca", "University of Manitoba", "Winnipeg, MB"),
    ("ulaval.ca", "Université Laval", "Quebec City, QC"),
    ("usask.ca", "University of Saskatchewan", "Saskatoon, SK"),
    # Other large public universities
    ("sfu.ca", "Simon Fraser University", "Burnaby, BC"),
    ("yorku.ca", "York University", "Toronto, ON"),
    ("my.yorku.ca", "York University", "Toronto, ON"),
    ("concordia.ca", "Concordia University", "Montreal, QC"),
    ("live.concordia.ca", "Concordia University", "Montreal, QC"),
    ("uvic.ca", "University of Victoria", "Victoria, BC"),
    ("carleton.ca", "Carleton University", "Ottawa, ON"),
    ("cmail.carleton.ca", "Carleton University", "Ottawa, ON"),
    ("torontomu.ca", "Toronto Metropolitan University", "Toronto, ON"),
    ("ryerson.ca", "Toronto Metropolitan University", "Toronto, ON"),
    ("uoguelph.ca", "University of Guelph", "Guelph, ON"),
    ("mun.ca", "Memorial University of Newfoundland", "St. John's, NL"),
    ("uwindsor.ca", "University of Windsor", "Windsor, ON"),
    ("unb.ca", "University of New Brunswick", "Fredericton, NB"),
    ("uregina.ca", "University of Regina", "Regina, SK"),
    ("usherbrooke.ca", "Université de Sherbrooke", "Sherbrooke, QC"),
    ("uqam.ca", "Université du Québec à Montréal", "Montreal, QC"),
    ("brocku.ca", "Brock University", "St. Catharines, ON"),
    ("uleth.ca", "University of Lethbridge", "Lethbridge, AB"),
    ("wlu.ca", "Wilfrid Laurier University", "Waterloo, ON"),
    ("mylaurier.ca", "Wilfrid Laurier University", "Waterloo, ON"),
    ("lakeheadu.ca", "Lakehead University", "Thunder Bay, ON"),
    ("trentu.ca", "Trent University", "Peterborough, ON"),
    ("ontariotechu.ca", "Ontario Tech University", "Oshawa, ON"),
    ("ontariotechu.net", "Ontario Tech University", "Oshawa, ON"),
    ("unbc.ca", "University of Northern British Columbia", "Prince George, BC"),
    ("mtroyal.ca", "Mount Royal University", "Calgary, AB"),
    ("macewan.ca", "MacEwan University", "Edmonton, AB"),
    ("mymacewan.ca", "MacEwan University", "Edmonton, AB"),
    ("tru.ca", "Thompson Rivers University", "Kamloops, BC"),
    ("upei.ca", "University of Prince Edward Island", "Charlottetown, PE"),
    ("smu.ca", "Saint Mary's University", "Halifax, NS"),
    ("cbu.ca", "Cape Breton University", "Sydney, NS"),
    ("viu.ca", "Vancouver Island University", "Nanaimo, BC"),
    ("kpu.ca", "Kwantlen Polytechnic University", "Surrey, BC"),
    ("athabascau.ca", "Athabasca University", "Athabasca, AB"),
    ("ocadu.ca", "OCAD University", "Toronto, ON"),
    # Major public colleges (common DLIs for Study Permit / SDS)
    ("senecacollege.ca", "Seneca Polytechnic", "Toronto, ON"),
    ("myseneca.senecacollege.ca", "Seneca Polytechnic", "Toronto, ON"),
    ("georgebrown.ca", "George Brown College", "Toronto, ON"),
    ("humber.ca", "Humber Polytechnic", "Toronto, ON"),
    ("centennialcollege.ca", "Centennial College", "Toronto, ON"),
    ("conestogac.on.ca", "Conestoga College", "Kitchener, ON"),
    ("sheridancollege.ca", "Sheridan College", "Oakville, ON"),
    ("algonquincollege.com", "Algonquin College", "Ottawa, ON"),
    ("fanshawec.ca", "Fanshawe College", "London, ON"),
    ("douglascollege.ca", "Douglas College", "New Westminster, BC"),
    ("bcit.ca", "British Columbia Institute of Technology", "Burnaby, BC"),
    ("mohawkcollege.ca", "Mohawk College", "Hamilton, ON"),
    ("durhamcollege.ca", "Durham College", "Oshawa, ON"),
    ("niagaracollege.ca", "Niagara College", "Welland, ON"),
    ("langara.ca", "Langara College", "Vancouver, BC"),

    # Additional universities
    ("uwinnipeg.ca", "University of Winnipeg", "Winnipeg, MB"),
    ("brandonu.ca", "Brandon University", "Brandon, MB"),
    ("royalroads.ca", "Royal Roads University", "Victoria, BC"),
    ("capilanou.ca", "Capilano University", "North Vancouver, BC"),
    ("ufv.ca", "University of the Fraser Valley", "Abbotsford, BC"),
    ("twu.ca", "Trinity Western University", "Langley, BC"),
    ("ecuad.ca", "Emily Carr University of Art + Design", "Vancouver, BC"),
    ("acadiau.ca", "Acadia University", "Wolfville, NS"),
    ("stfx.ca", "St. Francis Xavier University", "Antigonish, NS"),
    ("msvu.ca", "Mount Saint Vincent University", "Halifax, NS"),
    ("nscad.ca", "NSCAD University", "Halifax, NS"),
    ("mta.ca", "Mount Allison University", "Sackville, NB"),
    ("stu.ca", "St. Thomas University", "Fredericton, NB"),
    ("ubishops.ca", "Bishop's University", "Sherbrooke, QC"),
    ("laurentian.ca", "Laurentian University", "Sudbury, ON"),
    ("nipissingu.ca", "Nipissing University", "North Bay, ON"),
    ("algomau.ca", "Algoma University", "Sault Ste. Marie, ON"),
    ("redeemer.ca", "Redeemer University", "Ancaster, ON"),
    ("yukonu.ca", "Yukon University", "Whitehorse, YT"),
    ("usainteanne.ca", "Université Sainte-Anne", "Church Point, NS"),
    ("hec.ca", "HEC Montréal", "Montreal, QC"),
    ("polymtl.ca", "Polytechnique Montréal", "Montreal, QC"),
    ("etsmtl.ca", "École de technologie supérieure (ÉTS)", "Montreal, QC"),
    ("uqtr.ca", "Université du Québec à Trois-Rivières", "Trois-Rivières, QC"),
    ("uqac.ca", "Université du Québec à Chicoutimi", "Saguenay, QC"),
    ("uqar.ca", "Université du Québec à Rimouski", "Rimouski, QC"),
    ("uqo.ca", "Université du Québec en Outaouais", "Gatineau, QC"),
    ("teluq.ca", "Université TÉLUQ", "Quebec City, QC"),

    # Ontario public colleges
    ("flemingcollege.ca", "Fleming College", "Peterborough, ON"),
    ("loyalistcollege.com", "Loyalist College", "Belleville, ON"),
    ("sl.on.ca", "St. Lawrence College", "Kingston, ON"),
    ("cambriancollege.ca", "Cambrian College", "Sudbury, ON"),
    ("canadorecollege.ca", "Canadore College", "North Bay, ON"),
    ("confederationcollege.ca", "Confederation College", "Thunder Bay, ON"),
    ("georgiancollege.ca", "Georgian College", "Barrie, ON"),
    ("lambtoncollege.ca", "Lambton College", "Sarnia, ON"),
    ("saultcollege.ca", "Sault College", "Sault Ste. Marie, ON"),
    ("stclaircollege.ca", "St. Clair College", "Windsor, ON"),
    ("northerncollege.ca", "Northern College", "Timmins, ON"),
    ("collegelacite.ca", "Collège La Cité", "Ottawa, ON"),
    ("collegeboreal.ca", "Collège Boréal", "Sudbury, ON"),

    # British Columbia public colleges & institutes
    ("camosun.ca", "Camosun College", "Victoria, BC"),
    ("vcc.ca", "Vancouver Community College", "Vancouver, BC"),
    ("cnc.bc.ca", "College of New Caledonia", "Prince George, BC"),
    ("okanagan.bc.ca", "Okanagan College", "Kelowna, BC"),
    ("selkirk.ca", "Selkirk College", "Castlegar, BC"),
    ("nic.bc.ca", "North Island College", "Courtenay, BC"),
    ("jibc.ca", "Justice Institute of British Columbia", "New Westminster, BC"),
    ("coastmountaincollege.ca", "Coast Mountain College", "Terrace, BC"),

    # Alberta polytechnics & colleges
    ("sait.ca", "Southern Alberta Institute of Technology (SAIT)", "Calgary, AB"),
    ("nait.ca", "Northern Alberta Institute of Technology (NAIT)", "Edmonton, AB"),
    ("bowvalleycollege.ca", "Bow Valley College", "Calgary, AB"),
    ("rdpolytech.ca", "Red Deer Polytechnic", "Red Deer, AB"),
    ("lethbridgecollege.ca", "Lethbridge College", "Lethbridge, AB"),
    ("oldscollege.ca", "Olds College", "Olds, AB"),
    ("norquest.ca", "NorQuest College", "Edmonton, AB"),
    ("keyano.ca", "Keyano College", "Fort McMurray, AB"),

    # Prairie / Atlantic / Territorial public colleges & polytechnics
    ("rrc.ca", "Red River College Polytechnic", "Winnipeg, MB"),
    ("assiniboine.net", "Assiniboine Community College", "Brandon, MB"),
    ("saskpolytech.ca", "Saskatchewan Polytechnic", "Saskatoon, SK"),
    ("nscc.ca", "Nova Scotia Community College", "Halifax, NS"),
    ("nbcc.ca", "New Brunswick Community College", "Fredericton, NB"),
    ("ccnb.ca", "Collège communautaire du Nouveau-Brunswick", "Bathurst, NB"),
    ("cna.nl.ca", "College of the North Atlantic", "Stephenville, NL"),
    ("hollandcollege.com", "Holland College", "Charlottetown, PE"),

    # Quebec CEGEPs / colleges (common international destinations)
    ("vaniercollege.qc.ca", "Vanier College", "Montreal, QC"),
    ("dawsoncollege.qc.ca", "Dawson College", "Montreal, QC"),
    ("johnabbott.qc.ca", "John Abbott College", "Sainte-Anne-de-Bellevue, QC"),
    ("cvm.qc.ca", "Cégep du Vieux Montréal", "Montreal, QC"),
    ("lasallecollege.com", "LaSalle College", "Montreal, QC"),
]


def seed_ca_universities(db: Session) -> int:
    """Insert Canadian institutions into the us_universities table (country_code='CA').

    Idempotent: only domains not already present are inserted, so existing rows (and the
    externally-loaded US list) are never modified.
    """
    existing = {
        (domain or "").strip().lower()
        for (domain,) in db.query(models.USUniversity.email_domain).all()
    }
    inserted = 0
    for raw_domain, name, location in CA_UNIVERSITIES:
        domain = (raw_domain or "").strip().lower()
        if not domain or domain in existing:
            continue
        db.add(
            models.USUniversity(
                email_domain=domain,
                university_name=name,
                location=location,
                country_code="CA",
            )
        )
        existing.add(domain)
        inserted += 1
    if inserted:
        db.commit()
    return inserted
