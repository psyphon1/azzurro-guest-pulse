# Putting the dashboard online as a public demo

This page explains how to show the Azzurro review dashboard to people who cannot run anything on their own
computer, for example on Streamlit Community Cloud. It is written for someone who is not a developer.

Labels used below: **[verified]** means it was tried on this project. **[not verified]** means it describes the
hosting service from general knowledge and could not be tried here, so check it on the service's own pages.

## 1. What the demo shows, and what it does not

* It shows a **snapshot**: the newest reviews (up to 300 per hotel) copied from a real collection run on one
  day, with their topic tags. It is **not live**. It never updates by itself. **[verified]**
* Every page of the demo carries a dark banner at the top: "SAMPLE DATA: a snapshot of real public Booking.com
  reviews, not live. Collected on <date>." The date is the last successful collection recorded in the file. **[verified]**
* It does **not collect reviews**. The collector needs a real, visible browser window, which a hosting service
  does not provide. Nothing on the host ever contacts Booking.com. **[verified]** the dashboard does not import the
  collector's browser code (a test checks this).
* If a hotel had no reviews when the snapshot was taken, it simply does not appear. Right now the snapshot has
  no reviews for Central Sydney: it was blocked twice and skipped (`docs/adr/004-central-sydney-not-collected.md`). It
  holds 733 reviews: Potts Point 300, Darling Harbour 300 (both partial in the full database) and Olympic Hotel
  Paddington 133. Refresh the snapshot (section 3) after Central Sydney has been collected.

## 2. Streamlit Community Cloud, step by step

**What the app reads.** On a host there is no `data/reviews.db`, so the dashboard automatically uses
`data/sample/reviews_sample.db`. On your own computer, if `data/reviews.db` exists it is used instead (the live
data, with no sample banner). Setting the environment variable `REVIEWS_DB` overrides both. **[verified]**

**What to commit and what never to.**

| Commit it | Never commit it |
|---|---|
| `data/sample/reviews_sample.db` (the snapshot) | `data/reviews.db` (the live collection) |
| `dashboard/`, `insights/`, `scraper/config.py` and the rest of the code | `.env`, `*.pem`, `cookies*.json` |
| `dashboard/requirements.txt`, `.streamlit/config.toml` | `data/raw/` |

The project's `.gitignore` blocks every `data/*.db` **including the sample snapshot**, on purpose: the snapshot holds
real public review text, so publishing it must be a deliberate step. When you have read the privacy checklist in
section 5 and decided to publish, add it explicitly:

```
git add -f data/sample/reviews_sample.db
git ls-files data/sample          # should now list the file
```

Before you push, run `git status` and read the list of files.

**Steps** (the screens may change; **[not verified]** against the current Streamlit site):

1. Put the project on GitHub (a new repository; public if you use the free tier, private repositories need
   permission to be granted to Streamlit). Include `data/sample/reviews_sample.db`.
2. Go to share.streamlit.io, sign in with GitHub, press **New app**.
3. Choose the repository and branch.
4. **Main file path:** `dashboard/app.py`
5. Open **Advanced settings** and pick a **Python version**. This project was tested on Python 3.15. If the host
   does not offer that, choose the newest it offers (3.11 or later is needed by the pandas version in the
   requirements). Whether the app runs on versions other than 3.15 was **not verified**; if the build fails, the
   build log says which package could not be installed.
6. **Requirements file.** Use `dashboard/requirements.txt`. It lists only four packages (streamlit, pandas,
   plotly, pydantic). Do **not** use the top-level `requirements.txt`: it also lists Playwright (the collector's
   browser tool) and pytest, which make the build large and slow and are not needed. To my knowledge the host looks
   for a requirements file next to the main file first, then in the repository root, so `dashboard/requirements.txt`
   should be picked up automatically. **[not verified]**. If the build log shows it installing playwright, the root
   file was used: rename or move the root file or check the service's documentation for how it picks the file.
7. Press **Deploy**. The first build takes a few minutes.
8. Open the app address. Check: the dark SAMPLE DATA banner is on top, the numbers appear and no red error box.

Secrets: this app needs none. Do not add any in the host's settings.

## 3. Refreshing the snapshot

Do this on your own computer, from the project folder, with the virtual environment active.

1. Collect: `python -m scraper.run --property all --mode full` (needs the visible browser; this is the only step
   that talks to Booking.com).
2. Tag topics on the live database: `python -m insights.pipeline --db data/reviews.db`
3. Export the snapshot: `python scripts/export_sample.py --db data/reviews.db --csv data/sample_reviews.csv --sample-db data/sample/reviews_sample.db --per-property 300`
   (reads the live file read-only; writes the CSV and the sample database).
4. Check it: `REVIEWS_DB=data/sample/reviews_sample.db streamlit run dashboard/app.py` and look for the banner.
5. Commit `data/sample/reviews_sample.db` and push. The host redeploys on its own.

Run step 2 **before** step 3. The tags are copied from the live file into the snapshot. Running the topic step
on the snapshot file itself does not work with the current export (its tag tables are created without the keys
the pipeline needs); this was observed when preparing this page. **[verified]**

## 4. Privacy checklist before it goes public

Tick every line before sharing the address.

- [ ] **The text is public.** Review titles, "liked" and "disliked" text and hotel replies were published by
      Booking.com. You are republishing them in a different place; make sure you are comfortable with that and
      with Booking.com's terms for it.
- [ ] **Staff first names may appear.** Guests sometimes type the name of a staff member in their review
      ("Maria at reception was lovely"). The dashboard cannot detect names. Search the snapshot for names you
      do not want shown (`sqlite3 data/sample/reviews_sample.db` or the dashboard's search box) before publishing.
- [ ] **E-mail addresses and phone numbers** typed into a review are hidden on screen and in the CSV download on a
      best-effort basis. Spelled-out ones ("john at gmail dot com") and unusual formats can slip through.
- [ ] **No reviewer names or accounts are stored** at all, so none can appear. **[verified]** (the database has
      no such columns; a test checks the dashboard and CSV).
- [ ] **No login.** Streamlit Community Cloud public apps have no password by default: anyone with the link can
      open it, and links get shared. Treat everything in the snapshot as visible to the world. **[not verified]**
      for the current hosting options; check whether the service offers viewer restrictions for your account.
- [ ] **The CSV download button is on.** Visitors can download the reviews on screen. Same content as above.
- [ ] You did not commit `data/reviews.db`, `.env` or cookie files (`git status`, then
      `git ls-files | grep -E "reviews.db|\.env"` should print nothing but the sample).

## 5. Private use instead

If the reviews should not be public, do not host it. Run it on a computer in the office:
`streamlit run dashboard/app.py --server.address 127.0.0.1` (only that computer) or let colleagues on the
network connect through a VPN or a reverse proxy that asks for a sign-in and uses HTTPS. See
`docs/security/dashboard.md` ("Residual risks: no authentication"). With the live `data/reviews.db` present the
dashboard shows live data and no sample banner.

## 6. Troubleshooting

* **"No review data found"**: neither `data/reviews.db` nor `data/sample/reviews_sample.db` exists in the
  deployed copy. The sample file was probably not committed: it is git-ignored by default, so it needs `git add -f data/sample/reviews_sample.db` (check `git ls-files data/sample`).
* **"The review database could not be read"**: the file is damaged or is not a review database. Re-export it
  (section 3).
* **The build installs playwright or takes very long**: the wrong requirements file was used (section 2, step 6).
* **A package fails to install on the chosen Python version**: pick a newer Python in Advanced settings.
* **The page says the data is stale** ("no successful update for more than 48 hours"): expected for a snapshot;
  the banner above it explains. A hotel with no reviews in the snapshot is listed too.
* **A new snapshot does not show up**: the app caches data for up to 5 minutes; reload the page, or reboot the
  app from the host's menu.
* **The page looks unstyled or shows an old design**: hard-refresh the browser.
