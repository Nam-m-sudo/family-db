from flask_sqlalchemy import SQLAlchemy
from datetime import date

db = SQLAlchemy()

RELATION_CHOICES = ["son", "daughter", "wife", "husband"]
SPOUSE_RELATIONS = ("wife", "husband")
GENDER_CHOICES = ["Male", "Female"]
STATUS_CHOICES = ["Alive", "Dead"]
BRANCH_STATUS_CHOICES = ["not_started", "in_progress", "submitted"]


class Person(db.Model):
    """A single family-tree entry. Trunk people (great-grandfather's generation)
    have branch_id = NULL and are shared/read-only to every branch. Everyone a
    branch family adds gets that branch's branch_id."""
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=True)

    relation_type = db.Column(db.String(20), nullable=False)  # root/son/daughter/spouse
    gender = db.Column(db.String(10))
    alive_status = db.Column(db.String(10), default="Alive")

    name = db.Column(db.String(120), nullable=False)       # English spelling
    name_kn = db.Column(db.String(120))                     # Kannada spelling (auto-suggested, editable)
    dob = db.Column(db.String(20))   # DD-MM-YYYY, optional
    dod = db.Column(db.String(20))   # DD-MM-YYYY, optional
    dod_masa = db.Column(db.String(30))    # lunar month at death (e.g. Chaitra), for Paksha Masa rites
    dod_paksha = db.Column(db.String(20))  # Shukla / Krishna paksha at death
    dod_thithi = db.Column(db.String(30))  # thithi at death (e.g. Chaturdashi)
    nakshatra = db.Column(db.String(60))      # nakshatra at birth
    gothra = db.Column(db.String(60))
    address = db.Column(db.Text)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    maps_link = db.Column(db.String(400))

    sibling_order = db.Column(db.Integer, default=1)  # 1 = eldest
    created_at = db.Column(db.DateTime, default=db.func.now())

    children = db.relationship(
        "Person",
        backref=db.backref("parent", remote_side=[id]),
        foreign_keys=[parent_id],
    )

    def age(self):
        if not self.dob:
            return None
        try:
            d, m, y = self.dob.split("-")
            born = date(int(y), int(m), int(d))
        except Exception:
            return None
        today = date.today()
        years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        return years


class Branch(db.Model):
    """One of the 9 families. token is the unlisted URL they use, no login."""
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(40), unique=True, nullable=False)
    label = db.Column(db.String(200), nullable=False)  # e.g. "Branch of Ramachandra (2nd son)"
    anchor_person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    contact_name = db.Column(db.String(120))
    contact_phone = db.Column(db.String(20))
    status = db.Column(db.String(20), default="not_started")
    created_at = db.Column(db.DateTime, default=db.func.now())

    anchor_person = db.relationship("Person", foreign_keys=[anchor_person_id])