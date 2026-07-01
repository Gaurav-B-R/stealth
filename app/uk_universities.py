"""UK university registry (email domain -> university) for signup auto-fill.

Mirrors the US `us_universities` data and the Australian/Canadian seeds, but for the
United Kingdom and *code-seeded* (the US list is loaded externally in prod). Rows live
in the same `us_universities` table — a legacy name that is really a "known university
email domains" map — tagged with `country_code='UK'`. The signup auto-fill
(`/api/auth/university-by-email`) looks up by the full email domain, so well-known
student subdomains are included so e.g. name@student.manchester.ac.uk resolves too.

Idempotent: `seed_uk_universities` only inserts domains not already present.
"""
from sqlalchemy.orm import Session

from app import models

# (email_domain, university_name, location) — Russell Group + other major UK
# universities, plus common student subdomains for the largest schools.
UK_UNIVERSITIES: list[tuple[str, str, str]] = [
    # Oxbridge + Golden Triangle
    ("ox.ac.uk", "University of Oxford", "Oxford, England"),
    ("cam.ac.uk", "University of Cambridge", "Cambridge, England"),
    ("imperial.ac.uk", "Imperial College London", "London, England"),
    ("ucl.ac.uk", "University College London", "London, England"),
    ("lse.ac.uk", "London School of Economics", "London, England"),
    ("kcl.ac.uk", "King's College London", "London, England"),
    # Russell Group
    ("ed.ac.uk", "University of Edinburgh", "Edinburgh, Scotland"),
    ("sms.ed.ac.uk", "University of Edinburgh", "Edinburgh, Scotland"),
    ("manchester.ac.uk", "University of Manchester", "Manchester, England"),
    ("student.manchester.ac.uk", "University of Manchester", "Manchester, England"),
    ("postgrad.manchester.ac.uk", "University of Manchester", "Manchester, England"),
    ("bristol.ac.uk", "University of Bristol", "Bristol, England"),
    ("warwick.ac.uk", "University of Warwick", "Coventry, England"),
    ("live.warwick.ac.uk", "University of Warwick", "Coventry, England"),
    ("glasgow.ac.uk", "University of Glasgow", "Glasgow, Scotland"),
    ("student.gla.ac.uk", "University of Glasgow", "Glasgow, Scotland"),
    ("bham.ac.uk", "University of Birmingham", "Birmingham, England"),
    ("student.bham.ac.uk", "University of Birmingham", "Birmingham, England"),
    ("leeds.ac.uk", "University of Leeds", "Leeds, England"),
    ("sheffield.ac.uk", "University of Sheffield", "Sheffield, England"),
    ("nottingham.ac.uk", "University of Nottingham", "Nottingham, England"),
    ("soton.ac.uk", "University of Southampton", "Southampton, England"),
    ("durham.ac.uk", "Durham University", "Durham, England"),
    ("liverpool.ac.uk", "University of Liverpool", "Liverpool, England"),
    ("liv.ac.uk", "University of Liverpool", "Liverpool, England"),
    ("newcastle.ac.uk", "Newcastle University", "Newcastle, England"),
    ("ncl.ac.uk", "Newcastle University", "Newcastle, England"),
    ("cardiff.ac.uk", "Cardiff University", "Cardiff, Wales"),
    ("qmul.ac.uk", "Queen Mary University of London", "London, England"),
    ("exeter.ac.uk", "University of Exeter", "Exeter, England"),
    ("york.ac.uk", "University of York", "York, England"),
    ("qub.ac.uk", "Queen's University Belfast", "Belfast, Northern Ireland"),
    # Other large / well-known universities
    ("lancaster.ac.uk", "Lancaster University", "Lancaster, England"),
    ("bath.ac.uk", "University of Bath", "Bath, England"),
    ("st-andrews.ac.uk", "University of St Andrews", "St Andrews, Scotland"),
    ("lboro.ac.uk", "Loughborough University", "Loughborough, England"),
    ("leicester.ac.uk", "University of Leicester", "Leicester, England"),
    ("le.ac.uk", "University of Leicester", "Leicester, England"),
    ("surrey.ac.uk", "University of Surrey", "Guildford, England"),
    ("reading.ac.uk", "University of Reading", "Reading, England"),
    ("sussex.ac.uk", "University of Sussex", "Brighton, England"),
    ("uea.ac.uk", "University of East Anglia", "Norwich, England"),
    ("abdn.ac.uk", "University of Aberdeen", "Aberdeen, Scotland"),
    ("dundee.ac.uk", "University of Dundee", "Dundee, Scotland"),
    ("strath.ac.uk", "University of Strathclyde", "Glasgow, Scotland"),
    ("hw.ac.uk", "Heriot-Watt University", "Edinburgh, Scotland"),
    ("stir.ac.uk", "University of Stirling", "Stirling, Scotland"),
    ("kent.ac.uk", "University of Kent", "Canterbury, England"),
    ("city.ac.uk", "City, University of London", "London, England"),
    ("soas.ac.uk", "SOAS University of London", "London, England"),
    ("brunel.ac.uk", "Brunel University London", "London, England"),
    ("rhul.ac.uk", "Royal Holloway, University of London", "Egham, England"),
    ("gold.ac.uk", "Goldsmiths, University of London", "London, England"),
    ("bbk.ac.uk", "Birkbeck, University of London", "London, England"),
    ("westminster.ac.uk", "University of Westminster", "London, England"),
    ("greenwich.ac.uk", "University of Greenwich", "London, England"),
    ("mdx.ac.uk", "Middlesex University", "London, England"),
    ("aston.ac.uk", "Aston University", "Birmingham, England"),
    ("swansea.ac.uk", "Swansea University", "Swansea, Wales"),
    ("ulster.ac.uk", "Ulster University", "Belfast, Northern Ireland"),
    ("port.ac.uk", "University of Portsmouth", "Portsmouth, England"),
    ("plymouth.ac.uk", "University of Plymouth", "Plymouth, England"),
    ("coventry.ac.uk", "Coventry University", "Coventry, England"),
    ("herts.ac.uk", "University of Hertfordshire", "Hatfield, England"),
    ("northumbria.ac.uk", "Northumbria University", "Newcastle, England"),
    ("mmu.ac.uk", "Manchester Metropolitan University", "Manchester, England"),
    ("ntu.ac.uk", "Nottingham Trent University", "Nottingham, England"),
    ("brookes.ac.uk", "Oxford Brookes University", "Oxford, England"),
    ("dmu.ac.uk", "De Montfort University", "Leicester, England"),
]


def seed_uk_universities(db: Session) -> int:
    """Insert UK universities into the us_universities table (country_code='UK').

    Idempotent: only domains not already present are inserted, so existing rows (and the
    externally-loaded US list) are never modified.
    """
    existing = {
        (domain or "").strip().lower()
        for (domain,) in db.query(models.USUniversity.email_domain).all()
    }
    inserted = 0
    for raw_domain, name, location in UK_UNIVERSITIES:
        domain = (raw_domain or "").strip().lower()
        if not domain or domain in existing:
            continue
        db.add(
            models.USUniversity(
                email_domain=domain,
                university_name=name,
                location=location,
                country_code="UK",
            )
        )
        existing.add(domain)
        inserted += 1
    if inserted:
        db.commit()
    return inserted
