"""German university registry (email domain -> university) for signup auto-fill and the
university typeahead.

Mirrors the UK/AU/CA seeds but for Germany, *code-seeded* (the US list is loaded
externally in prod). Rows live in the same `us_universities` table — a legacy name that
is really a "known university email domains" map — tagged with `country_code='DE'`.

Covers the TU9 technical universities, the major research universities (U15 + excellence
cluster), the largest universities of applied sciences (Hochschulen — hugely popular with
international students), and the best-known private/business schools.

Idempotent: `seed_de_universities` only inserts domains not already present.
"""
from sqlalchemy.orm import Session

from app import models

# (email_domain, university_name, location)
DE_UNIVERSITIES: list[tuple[str, str, str]] = [
    # --- TU9 (leading technical universities) ---
    ("rwth-aachen.de", "RWTH Aachen University", "Aachen, Germany"),
    ("tu-berlin.de", "Technical University of Berlin", "Berlin, Germany"),
    ("tu-braunschweig.de", "TU Braunschweig", "Braunschweig, Germany"),
    ("tu-darmstadt.de", "Technical University of Darmstadt", "Darmstadt, Germany"),
    ("stud.tu-darmstadt.de", "Technical University of Darmstadt", "Darmstadt, Germany"),
    ("tu-dresden.de", "TU Dresden", "Dresden, Germany"),
    ("uni-hannover.de", "Leibniz University Hannover", "Hannover, Germany"),
    ("kit.edu", "Karlsruhe Institute of Technology (KIT)", "Karlsruhe, Germany"),
    ("student.kit.edu", "Karlsruhe Institute of Technology (KIT)", "Karlsruhe, Germany"),
    ("tum.de", "Technical University of Munich (TUM)", "Munich, Germany"),
    ("mytum.de", "Technical University of Munich (TUM)", "Munich, Germany"),
    ("uni-stuttgart.de", "University of Stuttgart", "Stuttgart, Germany"),

    # --- Top research universities ---
    ("lmu.de", "Ludwig Maximilian University of Munich (LMU)", "Munich, Germany"),
    ("campus.lmu.de", "Ludwig Maximilian University of Munich (LMU)", "Munich, Germany"),
    ("uni-heidelberg.de", "Heidelberg University", "Heidelberg, Germany"),
    ("stud.uni-heidelberg.de", "Heidelberg University", "Heidelberg, Germany"),
    ("hu-berlin.de", "Humboldt University of Berlin", "Berlin, Germany"),
    ("fu-berlin.de", "Free University of Berlin", "Berlin, Germany"),
    ("uni-bonn.de", "University of Bonn", "Bonn, Germany"),
    ("uni-freiburg.de", "University of Freiburg", "Freiburg, Germany"),
    ("uni-tuebingen.de", "University of Tübingen", "Tübingen, Germany"),
    ("uni-goettingen.de", "University of Göttingen", "Göttingen, Germany"),
    ("stud.uni-goettingen.de", "University of Göttingen", "Göttingen, Germany"),
    ("uni-koeln.de", "University of Cologne", "Cologne, Germany"),
    ("uni-frankfurt.de", "Goethe University Frankfurt", "Frankfurt, Germany"),
    ("uni-hamburg.de", "University of Hamburg", "Hamburg, Germany"),
    ("studium.uni-hamburg.de", "University of Hamburg", "Hamburg, Germany"),
    ("uni-muenster.de", "University of Münster", "Münster, Germany"),
    ("uni-wuerzburg.de", "University of Würzburg", "Würzburg, Germany"),
    ("uni-mannheim.de", "University of Mannheim", "Mannheim, Germany"),
    ("students.uni-mannheim.de", "University of Mannheim", "Mannheim, Germany"),
    ("fau.de", "Friedrich-Alexander University Erlangen-Nürnberg (FAU)", "Erlangen, Germany"),
    ("uni-leipzig.de", "Leipzig University", "Leipzig, Germany"),
    ("uni-jena.de", "Friedrich Schiller University Jena", "Jena, Germany"),
    ("uni-kiel.de", "Kiel University", "Kiel, Germany"),
    ("uni-konstanz.de", "University of Konstanz", "Konstanz, Germany"),
    ("uni-ulm.de", "Ulm University", "Ulm, Germany"),
    ("uni-due.de", "University of Duisburg-Essen", "Essen, Germany"),
    ("rub.de", "Ruhr University Bochum", "Bochum, Germany"),
    ("ruhr-uni-bochum.de", "Ruhr University Bochum", "Bochum, Germany"),
    ("tu-dortmund.de", "TU Dortmund University", "Dortmund, Germany"),
    ("uni-bielefeld.de", "Bielefeld University", "Bielefeld, Germany"),
    ("uni-bremen.de", "University of Bremen", "Bremen, Germany"),
    ("uni-regensburg.de", "University of Regensburg", "Regensburg, Germany"),
    ("uni-marburg.de", "University of Marburg", "Marburg, Germany"),
    ("uni-giessen.de", "Justus Liebig University Giessen", "Giessen, Germany"),
    ("uni-augsburg.de", "University of Augsburg", "Augsburg, Germany"),
    ("uni-bayreuth.de", "University of Bayreuth", "Bayreuth, Germany"),
    ("uni-potsdam.de", "University of Potsdam", "Potsdam, Germany"),
    ("uni-halle.de", "Martin Luther University Halle-Wittenberg", "Halle, Germany"),
    ("uni-rostock.de", "University of Rostock", "Rostock, Germany"),
    ("uni-saarland.de", "Saarland University", "Saarbrücken, Germany"),
    ("uni-hohenheim.de", "University of Hohenheim", "Stuttgart, Germany"),
    ("uni-paderborn.de", "Paderborn University", "Paderborn, Germany"),
    ("uni-kassel.de", "University of Kassel", "Kassel, Germany"),
    ("uni-wuppertal.de", "University of Wuppertal", "Wuppertal, Germany"),
    ("uni-siegen.de", "University of Siegen", "Siegen, Germany"),
    ("tu-chemnitz.de", "Chemnitz University of Technology", "Chemnitz, Germany"),
    ("rptu.de", "RPTU Kaiserslautern-Landau", "Kaiserslautern, Germany"),
    ("tu-ilmenau.de", "TU Ilmenau", "Ilmenau, Germany"),
    ("tu-freiberg.de", "TU Bergakademie Freiberg", "Freiberg, Germany"),
    ("uni-osnabrueck.de", "Osnabrück University", "Osnabrück, Germany"),
    ("uni-oldenburg.de", "University of Oldenburg", "Oldenburg, Germany"),
    ("uni-mainz.de", "Johannes Gutenberg University Mainz", "Mainz, Germany"),
    ("uni-trier.de", "University of Trier", "Trier, Germany"),
    ("uni-passau.de", "University of Passau", "Passau, Germany"),
    ("uni-bamberg.de", "University of Bamberg", "Bamberg, Germany"),
    ("leuphana.de", "Leuphana University Lüneburg", "Lüneburg, Germany"),

    # --- Major universities of applied sciences (Hochschulen / HAW) ---
    ("hm.edu", "Munich University of Applied Sciences (HM)", "Munich, Germany"),
    ("th-koeln.de", "TH Köln (Cologne University of Applied Sciences)", "Cologne, Germany"),
    ("htw-berlin.de", "HTW Berlin (University of Applied Sciences)", "Berlin, Germany"),
    ("hwr-berlin.de", "Berlin School of Economics and Law (HWR)", "Berlin, Germany"),
    ("beuth-hochschule.de", "Berliner Hochschule für Technik (BHT)", "Berlin, Germany"),
    ("fra-uas.de", "Frankfurt University of Applied Sciences", "Frankfurt, Germany"),
    ("h-da.de", "Darmstadt University of Applied Sciences (h_da)", "Darmstadt, Germany"),
    ("hs-rm.de", "RheinMain University of Applied Sciences", "Wiesbaden, Germany"),
    ("hs-mannheim.de", "Mannheim University of Applied Sciences", "Mannheim, Germany"),
    ("hs-esslingen.de", "Esslingen University of Applied Sciences", "Esslingen, Germany"),
    ("hs-karlsruhe.de", "Karlsruhe University of Applied Sciences", "Karlsruhe, Germany"),
    ("hs-aalen.de", "Aalen University of Applied Sciences", "Aalen, Germany"),
    ("hs-anhalt.de", "Anhalt University of Applied Sciences", "Köthen, Germany"),
    ("hs-fulda.de", "Fulda University of Applied Sciences", "Fulda, Germany"),
    ("hs-bremen.de", "Bremen University of Applied Sciences", "Bremen, Germany"),
    ("hs-augsburg.de", "Augsburg University of Applied Sciences", "Augsburg, Germany"),

    # --- Well-known private / business schools ---
    ("whu.edu", "WHU – Otto Beisheim School of Management", "Vallendar, Germany"),
    ("frankfurt-school.de", "Frankfurt School of Finance & Management", "Frankfurt, Germany"),
    ("fs.de", "Frankfurt School of Finance & Management", "Frankfurt, Germany"),
    ("esmt.org", "ESMT Berlin", "Berlin, Germany"),
    ("hertie-school.org", "Hertie School", "Berlin, Germany"),
    ("constructor.university", "Constructor University (formerly Jacobs University)", "Bremen, Germany"),
    ("code.berlin", "CODE University of Applied Sciences", "Berlin, Germany"),
    ("iu.org", "IU International University of Applied Sciences", "Erfurt, Germany"),
    ("gisma.com", "GISMA University of Applied Sciences", "Potsdam, Germany"),
]


def seed_de_universities(db: Session) -> int:
    """Insert German universities into the us_universities table (country_code='DE').

    Idempotent: only domains not already present are inserted, so existing rows (and the
    externally-loaded US list) are never modified.
    """
    existing = {
        (domain or "").strip().lower()
        for (domain,) in db.query(models.USUniversity.email_domain).all()
    }
    inserted = 0
    for raw_domain, name, location in DE_UNIVERSITIES:
        domain = (raw_domain or "").strip().lower()
        if not domain or domain in existing:
            continue
        db.add(
            models.USUniversity(
                email_domain=domain,
                university_name=name,
                location=location,
                country_code="DE",
            )
        )
        existing.add(domain)
        inserted += 1
    if inserted:
        db.commit()
    return inserted
