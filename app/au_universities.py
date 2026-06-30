"""Australian university registry (email domain -> university) for signup auto-fill.

Mirrors the US `us_universities` data, but for Australia and *code-seeded* (the US
list is loaded externally in prod). Rows live in the same `us_universities` table —
a legacy name that is really a "known university email domains" map — tagged with
`country_code='AU'`. The signup auto-fill (`/api/auth/university-by-email`) looks up
by the full email domain, so student subdomains are included where well-known.

Idempotent: `seed_au_universities` only inserts domains not already present.
"""
from sqlalchemy.orm import Session

from app import models

# (email_domain, university_name, location) — all 40+ Australian universities,
# plus common student subdomains so e.g. name@student.unsw.edu.au resolves too.
AU_UNIVERSITIES: list[tuple[str, str, str]] = [
    # Group of Eight
    ("unimelb.edu.au", "University of Melbourne", "Melbourne, VIC"),
    ("student.unimelb.edu.au", "University of Melbourne", "Melbourne, VIC"),
    ("sydney.edu.au", "University of Sydney", "Sydney, NSW"),
    ("uni.sydney.edu.au", "University of Sydney", "Sydney, NSW"),
    ("unsw.edu.au", "UNSW Sydney", "Sydney, NSW"),
    ("student.unsw.edu.au", "UNSW Sydney", "Sydney, NSW"),
    ("ad.unsw.edu.au", "UNSW Sydney", "Sydney, NSW"),
    ("anu.edu.au", "Australian National University", "Canberra, ACT"),
    ("monash.edu", "Monash University", "Melbourne, VIC"),
    ("student.monash.edu", "Monash University", "Melbourne, VIC"),
    ("uq.edu.au", "University of Queensland", "Brisbane, QLD"),
    ("uqconnect.edu.au", "University of Queensland", "Brisbane, QLD"),
    ("uwa.edu.au", "University of Western Australia", "Perth, WA"),
    ("student.uwa.edu.au", "University of Western Australia", "Perth, WA"),
    ("adelaide.edu.au", "University of Adelaide", "Adelaide, SA"),
    ("student.adelaide.edu.au", "University of Adelaide", "Adelaide, SA"),
    # Australian Technology Network & other large public universities
    ("uts.edu.au", "University of Technology Sydney", "Sydney, NSW"),
    ("student.uts.edu.au", "University of Technology Sydney", "Sydney, NSW"),
    ("qut.edu.au", "Queensland University of Technology", "Brisbane, QLD"),
    ("connect.qut.edu.au", "Queensland University of Technology", "Brisbane, QLD"),
    ("rmit.edu.au", "RMIT University", "Melbourne, VIC"),
    ("student.rmit.edu.au", "RMIT University", "Melbourne, VIC"),
    ("curtin.edu.au", "Curtin University", "Perth, WA"),
    ("student.curtin.edu.au", "Curtin University", "Perth, WA"),
    ("unisa.edu.au", "University of South Australia", "Adelaide, SA"),
    ("mymail.unisa.edu.au", "University of South Australia", "Adelaide, SA"),
    ("mq.edu.au", "Macquarie University", "Sydney, NSW"),
    ("students.mq.edu.au", "Macquarie University", "Sydney, NSW"),
    ("uow.edu.au", "University of Wollongong", "Wollongong, NSW"),
    ("deakin.edu.au", "Deakin University", "Geelong, VIC"),
    ("griffith.edu.au", "Griffith University", "Brisbane, QLD"),
    ("griffithuni.edu.au", "Griffith University", "Brisbane, QLD"),
    ("latrobe.edu.au", "La Trobe University", "Melbourne, VIC"),
    ("newcastle.edu.au", "University of Newcastle", "Newcastle, NSW"),
    ("uon.edu.au", "University of Newcastle", "Newcastle, NSW"),
    ("swinburne.edu.au", "Swinburne University of Technology", "Melbourne, VIC"),
    ("swin.edu.au", "Swinburne University of Technology", "Melbourne, VIC"),
    ("student.swin.edu.au", "Swinburne University of Technology", "Melbourne, VIC"),
    ("westernsydney.edu.au", "Western Sydney University", "Sydney, NSW"),
    ("jcu.edu.au", "James Cook University", "Townsville, QLD"),
    ("my.jcu.edu.au", "James Cook University", "Townsville, QLD"),
    ("flinders.edu.au", "Flinders University", "Adelaide, SA"),
    ("utas.edu.au", "University of Tasmania", "Hobart, TAS"),
    ("bond.edu.au", "Bond University", "Gold Coast, QLD"),
    ("canberra.edu.au", "University of Canberra", "Canberra, ACT"),
    ("csu.edu.au", "Charles Sturt University", "Bathurst, NSW"),
    ("ecu.edu.au", "Edith Cowan University", "Perth, WA"),
    ("our.ecu.edu.au", "Edith Cowan University", "Perth, WA"),
    ("murdoch.edu.au", "Murdoch University", "Perth, WA"),
    ("vu.edu.au", "Victoria University", "Melbourne, VIC"),
    ("live.vu.edu.au", "Victoria University", "Melbourne, VIC"),
    ("cqu.edu.au", "CQUniversity", "Rockhampton, QLD"),
    ("usq.edu.au", "University of Southern Queensland", "Toowoomba, QLD"),
    ("unisq.edu.au", "University of Southern Queensland", "Toowoomba, QLD"),
    ("scu.edu.au", "Southern Cross University", "Lismore, NSW"),
    ("acu.edu.au", "Australian Catholic University", "North Sydney, NSW"),
    ("myacu.edu.au", "Australian Catholic University", "North Sydney, NSW"),
    ("cdu.edu.au", "Charles Darwin University", "Darwin, NT"),
    ("federation.edu.au", "Federation University Australia", "Ballarat, VIC"),
    ("students.federation.edu.au", "Federation University Australia", "Ballarat, VIC"),
    ("une.edu.au", "University of New England", "Armidale, NSW"),
    ("myune.edu.au", "University of New England", "Armidale, NSW"),
    ("usc.edu.au", "University of the Sunshine Coast", "Sunshine Coast, QLD"),
    ("unisc.edu.au", "University of the Sunshine Coast", "Sunshine Coast, QLD"),
    ("torrens.edu.au", "Torrens University Australia", "Adelaide, SA"),
    ("nd.edu.au", "University of Notre Dame Australia", "Fremantle, WA"),
    ("notredame.edu.au", "University of Notre Dame Australia", "Fremantle, WA"),
    ("divinity.edu.au", "University of Divinity", "Melbourne, VIC"),
]


def seed_au_universities(db: Session) -> int:
    """Insert any missing Australian university domains. Returns the count inserted.

    Idempotent and additive — safe to run on every startup. Existing rows (incl. the
    externally-loaded US list) are never modified.
    """
    existing = {
        (domain or "").strip().lower()
        for (domain,) in db.query(models.USUniversity.email_domain).all()
    }
    inserted = 0
    for raw_domain, name, location in AU_UNIVERSITIES:
        domain = (raw_domain or "").strip().lower()
        if not domain or domain in existing:
            continue
        db.add(
            models.USUniversity(
                email_domain=domain,
                university_name=name,
                location=location,
                country_code="AU",
            )
        )
        existing.add(domain)
        inserted += 1
    if inserted:
        db.commit()
    return inserted
