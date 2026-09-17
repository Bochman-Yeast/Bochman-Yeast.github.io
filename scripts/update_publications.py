#!/usr/bin/env python3
"""
Auto-update publications.html from PubMed.

What this does:
  1. Searches PubMed for the lab's publications (see PUBMED_QUERY below).
  2. Fetches full records for any PMID not already present on the page.
  3. Formats each new record to match the site's existing citation style
     and inserts it into <ol id="pub-list"> in the right place (newest first).
  4. If a matching PDF exists at pdfs/<PMID>.pdf, adds a "PDF" download
     link next to the PubMed link — for both new and pre-existing entries.
  5. Updates the "last updated <Month Year>" note.

This script is meant to be run by the GitHub Actions workflow at
.github/workflows/update-publications.yml on a weekly schedule (and on
demand via "Run workflow"). It can also be run by hand:

    python3 scripts/update_publications.py

It only ever touches publications.html and exits cleanly (no changes)
when there's nothing new. It never removes or reorders existing entries.

If the automated search ever needs tightening (e.g. it starts pulling in
a different "Bochman ML"), edit PUBMED_QUERY below.
"""
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PUB_HTML = REPO_ROOT / "publications.html"
PDF_DIR = REPO_ROOT / "pdfs"

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
# Adjust this if the search ever needs to be narrowed or widened.
PUBMED_QUERY = "Bochman ML[Author]"
USER_AGENT = "bochman-lab-website-publication-updater (mailto:bochman@iu.edu)"

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _get(url, params, retries=3):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": USER_AGENT})
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise last_err


def search_pmids():
    data = _get(f"{EUTILS}/esearch.fcgi", {
        "db": "pubmed",
        "term": PUBMED_QUERY,
        "retmax": "300",
        "retmode": "json",
        "sort": "pub date",
    })
    return json.loads(data)["esearchresult"].get("idlist", [])


def fetch_records(pmids):
    """Fetch full XML records for a batch of PMIDs, in chunks of 100."""
    records = {}
    for i in range(0, len(pmids), 100):
        chunk = pmids[i:i + 100]
        data = _get(f"{EUTILS}/efetch.fcgi", {
            "db": "pubmed",
            "id": ",".join(chunk),
            "retmode": "xml",
        })
        root = ET.fromstring(data)
        for article in root.findall(".//PubmedArticle"):
            pmid_el = article.find(".//MedlineCitation/PMID")
            if pmid_el is None or not pmid_el.text:
                continue
            records[pmid_el.text.strip()] = article
        time.sleep(0.4)  # be polite to NCBI without an API key
    return records


def format_authors(article):
    parts = []
    for author in article.findall(".//AuthorList/Author"):
        last = author.findtext("LastName")
        initials = author.findtext("Initials")
        collective = author.findtext("CollectiveName")
        if collective:
            parts.append(html.escape(collective))
            continue
        if not last:
            continue
        suffix = author.findtext("Suffix")
        name = f"{last} {initials}" if initials else last
        if suffix:
            name = f"{name} {suffix}"
        name = html.escape(name)
        if last == "Bochman" and initials == "ML":
            name = f"<b>{name}</b>"
        parts.append(name)
    return ", ".join(parts) + "."


def format_journal_and_date(article):
    journal_abbrev = article.findtext(".//MedlineJournalInfo/MedlineTA") \
        or article.findtext(".//Journal/ISOAbbreviation") \
        or article.findtext(".//Journal/Title") or ""
    pubdate = article.find(".//Journal/JournalIssue/PubDate")
    year = month = day = None
    if pubdate is not None:
        year = pubdate.findtext("Year")
        month = pubdate.findtext("Month")
        day = pubdate.findtext("Day")
        if not year:
            medline_date = pubdate.findtext("MedlineDate") or ""
            m = re.match(r"(\d{4})", medline_date)
            if m:
                year = m.group(1)
    if not year:
        year = "n.d."

    date_str = year
    if month:
        date_str += f" {month}"
        if day:
            date_str += f" {day}"

    volume = article.findtext(".//Journal/JournalIssue/Volume")
    issue = article.findtext(".//Journal/JournalIssue/Issue")
    pages = article.findtext(".//Pagination/MedlinePgn")

    cite = date_str
    if volume:
        cite += f";{volume}"
        if issue:
            cite += f"({issue})"
        if pages:
            cite += f":{pages}"
    cite += "."
    return html.escape(journal_abbrev), cite, year


def sort_year(year):
    m = re.match(r"(\d{4})", str(year))
    return int(m.group(1)) if m else 0


def is_review(article):
    for pt in article.findall(".//PublicationTypeList/PublicationType"):
        if pt.text and "review" in pt.text.lower():
            return True
    return False


def is_preprint(article, journal_abbrev):
    for pt in article.findall(".//PublicationTypeList/PublicationType"):
        if pt.text and "preprint" in pt.text.lower():
            return True
    return journal_abbrev.lower() in ("biorxiv", "medrxiv", "biorxiv.", "medrxiv.")


def extract_title(article):
    """Full title text, including any nested markup (e.g. <i>species names</i>),
    which plain .findtext() would silently truncate at the first child tag."""
    el = article.find(".//ArticleTitle")
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def normalize_title(title):
    """Loose match key so we can spot the same paper under two PMIDs
    (a bioRxiv/medRxiv preprint and its later peer-reviewed version)."""
    t = re.sub(r"<[^>]+>", "", title).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return t.strip()


def build_li(pmid, article):
    raw_title = extract_title(article)
    title = html.escape(re.sub(r"\.$", "", raw_title)) + "."
    authors = format_authors(article)
    journal_abbrev, cite_tail, year = format_journal_and_date(article)

    preprint = is_preprint(article, journal_abbrev)
    badges = '<span class="badge">Preprint</span>' if preprint else ""
    review_tag = " <em>Review</em>" if is_review(article) else ""

    pdf_link = ""
    if (PDF_DIR / f"{pmid}.pdf").exists():
        pdf_link = f' &middot; <a href="pdfs/{pmid}.pdf">PDF</a>'

    li_html = (
        f'<li data-pmid="{pmid}"><span class="yr">{sort_year(year)}</span>'
        f'<div><b>{title}</b>{badges}{review_tag}<br>'
        f'<span class="pub-authors">{authors}</span> '
        f'<span class="pub-journal">{journal_abbrev}.</span> {cite_tail} '
        f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" target="_blank" rel="noopener">PMID: {pmid}</a>'
        f'{pdf_link}</div></li>'
    )
    return li_html, sort_year(year), normalize_title(raw_title), preprint


def existing_pmids_and_titles(text):
    pmids = set(re.findall(r'data-pmid="(\d+)"', text))
    # Fall back to scraping PMID links for any legacy <li> without data-pmid yet.
    pmids |= set(re.findall(r'PMID:\s*(\d+)', text))

    titles = set()
    for li in re.findall(r"<li\b.*?</li>", text, flags=re.S):
        m = re.search(r"<b>(.*?)</b>", li, flags=re.S)
        if m:
            titles.add(normalize_title(m.group(1)))
    return pmids, titles


def add_pdf_links_to_existing(text):
    """Add a PDF link to any existing <li> that lacks one but has a matching file."""
    changed = False

    def repl(m):
        nonlocal changed
        li_html = m.group(0)
        pmid_m = re.search(r'PMID:\s*(\d+)', li_html)
        if not pmid_m:
            return li_html
        pmid = pmid_m.group(1)
        if "pdfs/" in li_html:
            return li_html
        if (PDF_DIR / f"{pmid}.pdf").exists():
            changed = True
            return li_html.replace(
                "</div></li>",
                f' &middot; <a href="pdfs/{pmid}.pdf">PDF</a></div></li>',
            )
        return li_html

    new_text = re.sub(r"<li\b.*?</li>", repl, text, flags=re.S)
    return new_text, changed


def ensure_data_pmid_attrs(text):
    """Backfill data-pmid="..." on any <li> that doesn't have it yet."""
    def repl(m):
        li_html = m.group(0)
        if 'data-pmid="' in li_html[:40]:
            return li_html
        pmid_m = re.search(r'PMID:\s*(\d+)', li_html)
        if not pmid_m:
            return li_html
        return li_html.replace("<li>", f'<li data-pmid="{pmid_m.group(1)}">', 1)

    return re.sub(r"<li\b.*?</li>", repl, text, flags=re.S)


def main():
    text = PUB_HTML.read_text(encoding="utf-8")
    text = ensure_data_pmid_attrs(text)

    existing_pmids, existing_titles = existing_pmids_and_titles(text)

    try:
        all_pmids = search_pmids()
    except Exception as e:  # network hiccup shouldn't fail the whole workflow loudly
        print(f"PubMed search failed: {e}", file=sys.stderr)
        sys.exit(0)

    new_pmids = [p for p in all_pmids if p not in existing_pmids]

    text, pdf_changed = add_pdf_links_to_existing(text)

    candidates = []  # (yr, li_html, norm_title, preprint, pmid)
    if new_pmids:
        records = fetch_records(new_pmids)
        for pmid in new_pmids:
            article = records.get(pmid)
            if article is None:
                continue
            li_html, yr, norm_title, preprint = build_li(pmid, article)
            candidates.append((yr, li_html, norm_title, preprint, pmid))

    # Drop anything that's already on the page under a different PMID
    # (most commonly: a bioRxiv/medRxiv preprint whose peer-reviewed
    # version — a different PMID — is already listed).
    candidates = [c for c in candidates if c[2] not in existing_titles]

    # Within this batch, if the same paper shows up twice (e.g. both its
    # preprint and its just-indexed published version came back as "new"
    # in the same run), keep only one: prefer the peer-reviewed record.
    by_title = {}
    for c in candidates:
        yr, li_html, norm_title, preprint, pmid = c
        if norm_title not in by_title:
            by_title[norm_title] = c
        else:
            existing_choice = by_title[norm_title]
            if existing_choice[3] and not preprint:
                by_title[norm_title] = c  # prefer the non-preprint version
    new_entries = [(yr, li_html) for (yr, li_html, _, _, _) in by_title.values()]

    if not new_entries and not pdf_changed:
        PUB_HTML.write_text(text, encoding="utf-8")
        print("No new publications and no new PDF links found. Nothing to do.")
        return

    if new_entries:
        # Insert each new entry into the list in the right position (newest first).
        # We insert relative to the first existing <li data-pmid> whose year is <=,
        # falling back to the top or bottom of the list as needed.
        for yr, li_html in sorted(new_entries, key=lambda t: -t[0]):
            list_match = re.search(r'(<ol class="pub-list" id="pub-list">)(.*?)(</ol>)', text, re.S)
            list_open, list_body, list_close = list_match.groups()

            items = re.findall(r"<li\b.*?</li>", list_body, flags=re.S)
            insert_at = len(items)
            for i, item in enumerate(items):
                m = re.search(r'<span class="yr">(\d+)</span>', item)
                if m and int(m.group(1)) <= yr:
                    insert_at = i
                    break
            items.insert(insert_at, li_html)
            new_body = "\n\n      " + "\n\n      ".join(items) + "\n\n    "
            text = text[:list_match.start()] + list_open + new_body + list_close + text[list_match.end():]

    # Update the "last updated" note to the current month/year.
    import datetime
    now = datetime.datetime.utcnow()
    stamp = now.strftime("%B %Y")
    text = re.sub(r"last updated \w+ \d{4}", f"last updated {stamp}", text)

    PUB_HTML.write_text(text, encoding="utf-8")
    print(f"Added {len(new_entries)} new publication(s); PDF links updated: {pdf_changed}.")


if __name__ == "__main__":
    main()
