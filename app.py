import os
import secrets

import requests
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify

from models import db, Person, Branch, RELATION_CHOICES, GENDER_CHOICES, STATUS_CHOICES, SPOUSE_RELATIONS
from vocab import NAKSHATRAS, GOTHRAS, MASAS, PAKSHAS, THITHIS

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SITE_NAME = "Mavathoor Family"

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "family_collect.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")


@app.context_processor
def inject_site_name():
    return {"site_name": SITE_NAME}

# Change this directly, or set an ADMIN_PASSWORD environment variable to override it.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

db.init_app(app)


# ------------------------- helpers -------------------------
def require_admin():
    return session.get("is_admin", False)


def get_root_person():
    return Person.query.filter_by(relation_type="root", branch_id=None).first()


def gender_for_relation(relation, submitted_gender=None):
    if relation in ("son", "husband"):
        return "Male"
    if relation in ("daughter", "wife"):
        return "Female"
    return submitted_gender or "Male"  # root: asked explicitly in the form


def resolve_other(value, other_text):
    """If the dropdown value is 'Other', use whatever the person typed instead."""
    if value == "Other":
        return (other_text or "").strip() or "Other"
    return value


def apply_person_fields(person, form):
    """Copy the submitted form fields onto a Person (used for add and edit alike)."""
    relation = form.get("relation_type", person.relation_type or "son")
    person.relation_type = relation
    person.gender = gender_for_relation(relation, form.get("gender"))
    person.alive_status = form.get("alive_status", "Alive")
    person.name = form.get("name", "").strip()
    person.name_kn = form.get("name_kn", "").strip()
    person.dob = form.get("dob", "").strip()
    person.dod = form.get("dod", "").strip()
    person.dod_masa = form.get("dod_masa", "").strip()
    person.dod_paksha = form.get("dod_paksha", "").strip()
    person.dod_thithi = form.get("dod_thithi", "").strip()
    person.nakshatra = resolve_other(form.get("nakshatra", "").strip(), form.get("nakshatra_other"))
    person.gothra = resolve_other(form.get("gothra", "").strip(), form.get("gothra_other"))
    person.address = form.get("address", "").strip()
    person.phone = form.get("phone", "").strip()
    person.email = form.get("email", "").strip()
    person.maps_link = form.get("maps_link", "").strip()
    # Spouses (wife/husband) aren't part of a sibling ordering — keep whatever was stored, or 1.
    if relation not in SPOUSE_RELATIONS:
        person.sibling_order = int(form.get("sibling_order") or 1)
    elif person.sibling_order is None:
        person.sibling_order = 1
    return person


def delete_person_cascade(person):
    """Delete a person and everyone under them in the tree (their descendants)."""
    for child in list(person.children):
        delete_person_cascade(child)
    db.session.delete(person)


def find_anchored_conflict(person):
    """Returns the first person in this subtree (person included) that a
    branch link is anchored to, or None if it's safe to delete the whole
    subtree."""
    if Branch.query.filter_by(anchor_person_id=person.id).first():
        return person
    for child in person.children:
        conflict = find_anchored_conflict(child)
        if conflict:
            return conflict
    return None


def is_custom_value(value, choices):
    """True if `value` isn't one of the fixed dropdown keys — i.e. it was typed
    in via the 'Other' box."""
    known_keys = {key for key, _en, _kn in choices}
    return bool(value) and value not in known_keys


def person_tree_rows(anchor, branch_id):
    """Flatten a tree (anchor + everyone with the given branch_id) into an
    ordered, indent-aware list. branch_id=None is used for the shared root
    tree; a real branch.id is used for one family's branch."""
    people_by_parent = {}
    others = Person.query.filter(Person.branch_id == branch_id, Person.id != anchor.id).all()
    all_people = [anchor] + others
    for p in all_people:
        people_by_parent.setdefault(p.parent_id, []).append(p)
    for siblings in people_by_parent.values():
        siblings.sort(key=lambda p: (p.sibling_order or 1))

    rows = []

    def walk(person, depth):
        rows.append((person, depth))
        for child in people_by_parent.get(person.id, []):
            walk(child, depth + 1)

    walk(anchor, 0)
    return rows


def build_person_tree(anchor, branch_id):
    """Same people as person_tree_rows, but shaped for the visual chart:
    {"person": <Person>, "spouses": [{"person": <Person>}, ...], "children": [...]}
    A spouse (wife or husband, whichever fits the person's gender) is kept
    separate from "children" so they render beside their partner instead of
    as one more child underneath them. Any descendants that ended up attached
    to a spouse (parent_id = their id) are folded back into the main person's
    "children" so nothing goes missing from the chart."""
    people_by_parent = {}
    others = Person.query.filter(Person.branch_id == branch_id, Person.id != anchor.id).all()
    for p in [anchor] + others:
        people_by_parent.setdefault(p.parent_id, []).append(p)
    for siblings in people_by_parent.values():
        siblings.sort(key=lambda p: (p.sibling_order or 1))

    def node(person):
        raw_children = people_by_parent.get(person.id, [])
        spouses = [c for c in raw_children if c.relation_type in SPOUSE_RELATIONS]
        descendants = [c for c in raw_children if c.relation_type not in SPOUSE_RELATIONS]
        for s in spouses:
            descendants.extend(people_by_parent.get(s.id, []))
        descendants.sort(key=lambda p: (p.sibling_order or 1))
        return {
            "person": person,
            "spouses": [{"person": s} for s in spouses],
            "children": [node(c) for c in descendants],
        }

    return node(anchor)


# ------------------------- Transliteration (best-effort, always editable) -------------------------
@app.route("/api/transliterate")
def api_transliterate():
    """Suggests a Kannada spelling for text typed in English, using the same
    phonetic transliteration service behind Google's Indic keyboards. This is
    a best-effort suggestion only — always check and correct it. Requires
    internet access; if it fails for any reason, nothing is filled in and the
    person can type the Kannada spelling by hand instead."""
    text = request.args.get("text", "").strip()
    if not text:
        return jsonify({"kannada": ""})
    try:
        resp = requests.get(
            "https://inputtools.google.com/request",
            params={"text": text, "itc": "kn-t-i0-und", "num": 1, "cp": 0, "cs": 1, "ie": "utf-8", "oe": "utf-8"},
            timeout=3,
        )
        data = resp.json()
        suggestion = data[1][0][1][0] if data[0] == "SUCCESS" else ""
    except Exception:
        suggestion = ""
    return jsonify({"kannada": suggestion})


# ------------------------- Admin: login -------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Wrong password.", "danger")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


# ------------------------- Admin: dashboard -------------------------
@app.route("/admin")
def admin_dashboard():
    if not require_admin():
        return redirect(url_for("admin_login"))
    root = get_root_person()
    branches = Branch.query.order_by(Branch.id).all()
    return render_template("admin_dashboard.html", root=root, branches=branches)


# ------------------------- Root person: create (only used once) -------------------------
@app.route("/admin/root/create", methods=["GET", "POST"])
def admin_root_create():
    if not require_admin():
        return redirect(url_for("admin_login"))
    if get_root_person():
        flash("A root person already exists — edit them instead of creating a new one.", "danger")
        return redirect(url_for("admin_root_home"))

    if request.method == "POST":
        person = Person(branch_id=None, parent_id=None, relation_type="root")
        apply_person_fields(person, request.form)
        db.session.add(person)
        db.session.commit()
        flash(f"Created root person: {person.name}.", "success")
        return redirect(url_for("admin_root_home"))

    return render_template(
        "root_create.html",
        genders=GENDER_CHOICES,
        statuses=STATUS_CHOICES,
        nakshatras=NAKSHATRAS,
        gothras=GOTHRAS,
        masas=MASAS,
        pakshas=PAKSHAS,
        thithis=THITHIS,
    )


# ------------------------- Root person: tree view (mirrors a branch) -------------------------
@app.route("/admin/root")
def admin_root_home():
    if not require_admin():
        return redirect(url_for("admin_login"))
    root = get_root_person()
    if not root:
        return redirect(url_for("admin_root_create"))
    tree = build_person_tree(root, branch_id=None)
    return render_template("family_tree.html", branch=None, root=root, tree=tree)


@app.route("/admin/root/add", methods=["GET", "POST"])
def admin_root_add_person():
    if not require_admin():
        return redirect(url_for("admin_login"))
    root = get_root_person()
    if not root:
        return redirect(url_for("admin_root_create"))

    rows = person_tree_rows(root, branch_id=None)
    people_for_dropdown = [p for p, _depth in rows]
    default_parent_id = request.args.get("parent_id", type=int) or root.id
    default_relation = request.args.get("relation", "son")

    if request.method == "POST":
        parent_id = int(request.form.get("parent_id"))
        person = Person(branch_id=None, parent_id=parent_id)
        apply_person_fields(person, request.form)
        db.session.add(person)
        db.session.commit()
        flash(f"Added {person.name}.", "success")
        return redirect(url_for("admin_root_home"))

    return render_template(
        "person_form.html",
        branch=None,
        person=None,
        nakshatra_is_other=False,
        gothra_is_other=False,
        is_anchor=False,
        people_for_dropdown=people_for_dropdown,
        default_parent_id=default_parent_id,
        default_relation=default_relation,
        relations=RELATION_CHOICES,
        genders=GENDER_CHOICES,
        statuses=STATUS_CHOICES,
        nakshatras=NAKSHATRAS,
        gothras=GOTHRAS,
        masas=MASAS,
        pakshas=PAKSHAS,
        thithis=THITHIS,
    )


@app.route("/admin/root/edit/<int:person_id>", methods=["GET", "POST"])
def admin_root_edit_person(person_id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    person = Person.query.filter_by(id=person_id, branch_id=None).first_or_404()
    root = get_root_person()
    rows = person_tree_rows(root, branch_id=None)

    def is_descendant_or_self(candidate):
        node = candidate
        while node is not None:
            if node.id == person.id:
                return True
            node = node.parent
        return False
    people_for_dropdown = [p for p, _depth in rows if not is_descendant_or_self(p)]

    if request.method == "POST":
        parent_id = request.form.get("parent_id") or None
        person.parent_id = int(parent_id) if parent_id else None
        apply_person_fields(person, request.form)
        db.session.commit()
        flash(f"Updated {person.name}.", "success")
        return redirect(url_for("admin_root_home"))

    return render_template(
        "person_form.html",
        branch=None,
        person=person,
        nakshatra_is_other=is_custom_value(person.nakshatra, NAKSHATRAS),
        gothra_is_other=is_custom_value(person.gothra, GOTHRAS),
        is_anchor=(person.id == root.id),
        people_for_dropdown=people_for_dropdown,
        default_parent_id=person.parent_id,
        default_relation=person.relation_type,
        relations=RELATION_CHOICES,
        genders=GENDER_CHOICES,
        statuses=STATUS_CHOICES,
        nakshatras=NAKSHATRAS,
        gothras=GOTHRAS,
        masas=MASAS,
        pakshas=PAKSHAS,
        thithis=THITHIS,
    )


@app.route("/admin/root/delete/<int:person_id>", methods=["POST"])
def admin_root_delete_person(person_id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    person = Person.query.filter_by(id=person_id, branch_id=None).first_or_404()

    conflict = find_anchored_conflict(person)
    if conflict:
        flash(f"Can't delete — a branch link is anchored to {conflict.name}. Remove that branch first.", "danger")
        return redirect(url_for("admin_root_home"))

    name = person.name
    delete_person_cascade(person)
    db.session.commit()
    flash(f"Removed {name} (and anyone entered under them).", "info")
    return redirect(url_for("admin_root_home"))


# ------------------------- Admin: branch links -------------------------
@app.route("/admin/branches/add", methods=["GET", "POST"])
def admin_add_branch():
    """Create one branch link per family — pick which of the root's sons/
    daughters they descend from, and a unique unlisted link is generated."""
    if not require_admin():
        return redirect(url_for("admin_login"))

    possible_anchors = Person.query.filter(
        Person.branch_id.is_(None), Person.relation_type.in_(["son", "daughter"])
    ).order_by(Person.sibling_order).all()

    if request.method == "POST":
        anchor_id = request.form.get("anchor_person_id")
        token = secrets.token_urlsafe(12)
        branch = Branch(
            token=token,
            label=request.form.get("label", "").strip(),
            anchor_person_id=int(anchor_id),
            contact_name=request.form.get("contact_name", "").strip(),
            contact_phone=request.form.get("contact_phone", "").strip(),
        )
        db.session.add(branch)
        db.session.commit()
        flash(f"Branch created. Link: /branch/{token}", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("admin_add_branch.html", possible_anchors=possible_anchors)


# ------------------------- Branch family view (no login, token link) -------------------------
@app.route("/branch/<token>")
def branch_home(token):
    branch = Branch.query.filter_by(token=token).first_or_404()
    tree = build_person_tree(branch.anchor_person, branch_id=branch.id)
    return render_template("family_tree.html", branch=branch, root=None, tree=tree)


@app.route("/branch/<token>/add", methods=["GET", "POST"])
def branch_add_person(token):
    branch = Branch.query.filter_by(token=token).first_or_404()
    rows = person_tree_rows(branch.anchor_person, branch_id=branch.id)
    people_for_dropdown = [p for p, _depth in rows]

    default_parent_id = request.args.get("parent_id", type=int) or branch.anchor_person_id
    default_relation = request.args.get("relation", "son")

    if request.method == "POST":
        parent_id = int(request.form.get("parent_id"))
        person = Person(branch_id=branch.id, parent_id=parent_id)
        apply_person_fields(person, request.form)
        db.session.add(person)
        if branch.status == "not_started":
            branch.status = "in_progress"
        db.session.commit()
        flash(f"Added {person.name}.", "success")
        return redirect(url_for("branch_home", token=token))

    return render_template(
        "person_form.html",
        branch=branch,
        person=None,
        nakshatra_is_other=False,
        gothra_is_other=False,
        is_anchor=False,
        people_for_dropdown=people_for_dropdown,
        default_parent_id=default_parent_id,
        default_relation=default_relation,
        relations=RELATION_CHOICES,
        genders=GENDER_CHOICES,
        statuses=STATUS_CHOICES,
        nakshatras=NAKSHATRAS,
        gothras=GOTHRAS,
        masas=MASAS,
        pakshas=PAKSHAS,
        thithis=THITHIS,
    )


@app.route("/branch/<token>/edit/<int:person_id>", methods=["GET", "POST"])
def branch_edit_person(token, person_id):
    branch = Branch.query.filter_by(token=token).first_or_404()
    is_anchor = (person_id == branch.anchor_person_id)
    if is_anchor:
        person = Person.query.get_or_404(person_id)
    else:
        person = Person.query.filter_by(id=person_id, branch_id=branch.id).first_or_404()

    rows = person_tree_rows(branch.anchor_person, branch_id=branch.id)
    def is_descendant_or_self(candidate):
        node = candidate
        while node is not None:
            if node.id == person.id:
                return True
            node = node.parent
        return False
    people_for_dropdown = [p for p, _depth in rows if not is_descendant_or_self(p)]

    if request.method == "POST":
        if not is_anchor:
            parent_id = int(request.form.get("parent_id"))
            person.parent_id = parent_id
        apply_person_fields(person, request.form)
        db.session.commit()
        flash(f"Updated {person.name}.", "success")
        return redirect(url_for("branch_home", token=token))

    return render_template(
        "person_form.html",
        branch=branch,
        person=person,
        is_anchor=is_anchor,
        nakshatra_is_other=is_custom_value(person.nakshatra, NAKSHATRAS),
        gothra_is_other=is_custom_value(person.gothra, GOTHRAS),
        people_for_dropdown=people_for_dropdown,
        default_parent_id=person.parent_id,
        default_relation=person.relation_type,
        relations=RELATION_CHOICES,
        genders=GENDER_CHOICES,
        statuses=STATUS_CHOICES,
        nakshatras=NAKSHATRAS,
        gothras=GOTHRAS,
        masas=MASAS,
        pakshas=PAKSHAS,
        thithis=THITHIS,
    )


@app.route("/branch/<token>/delete/<int:person_id>", methods=["POST"])
def branch_delete_person(token, person_id):
    branch = Branch.query.filter_by(token=token).first_or_404()
    person = Person.query.filter_by(id=person_id, branch_id=branch.id).first_or_404()
    name = person.name
    delete_person_cascade(person)
    db.session.commit()
    flash(f"Removed {name} (and anyone entered under them).", "info")
    return redirect(url_for("branch_home", token=token))


@app.route("/branch/<token>/done", methods=["POST"])
def branch_mark_done(token):
    branch = Branch.query.filter_by(token=token).first_or_404()
    branch.status = "submitted"
    db.session.commit()
    flash("Marked as submitted. Thank you!", "success")
    return redirect(url_for("branch_home", token=token))


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001, use_reloader=False)