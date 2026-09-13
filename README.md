# Family Tree Data Collection (v1 — structured form)

A separate, standalone app from the main Mavathoor Family website. Its only job
is to collect raw family-tree data from the 9 branch families, so you can
review it and later merge it into the main site.

## How it works

1. **Trunk data** (great-grandfather, his spouse, his sons/daughters) is
   entered once by you via `/admin/trunk/add`. This is shared and fixed —
   no branch family can see or edit it.
2. For each of the 9 families, you create a **branch link** via
   `/admin/branches/add`, picking which trunk son/daughter they descend from.
   This gives you an unlisted URL like `/branch/AbCd1234xyz` — no login
   required, just send that link privately to that family.
3. Each family opens their link and adds their own descendants: click
   **+ son / + daughter / + spouse** next to any person already in their
   branch, fill in the form, save. The page reminds them to add children
   eldest → youngest, and there's a birth-order number to keep that straight.
4. When a family is done, they click "Mark our family as fully entered" —
   you'll see that status on your admin dashboard (`/admin`).
5. This is **staging data**, not the live site. Once a branch is submitted,
   review it (spelling, duplicate names, disagreements between branches on
   the trunk generation) before copying it into the main website's database.

## Fields collected per person

Alive/Deceased status, name, date of birth (age is calculated automatically
wherever a DOB is entered), nakshatra, gothra, address, phone, email, and an
optional Google Maps link to their house. Only name is required — everything
else can be left blank and filled in later.

## Running it locally

```bash
cd family_collect
pip install -r requirements.txt
export ADMIN_PASSWORD="pick-something-only-you-know"
python app.py
```

Open http://localhost:5001/admin (note: different port from the main site,
5001 not 5000, so you can run both at once during setup).

## What's intentionally NOT in this version

- The visual click-on-a-box tree — this version uses a simple list with
  "+ son / + daughter / + spouse" links instead. Once the data model here is
  proven out, the same `Person`/`Branch` tables can power a visual tree view
  without changing how data is stored.
- Editing/deleting entries after they're saved — for v1, mistakes are best
  fixed by you in the admin view or directly in the database, since this
  will only be used briefly during initial data collection.
- Merging into the main website's `FamilyMember` table — that's a manual
  review step for now; ask me to help script that once branches are submitted.
