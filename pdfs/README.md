# Publication PDFs

To attach a downloadable PDF to a publication on the [Publications page](../publications.html):

1. Name the file after the paper's PubMed ID (PMID) — for example `38613387.pdf` for the
   Cdc13 strand-exchange paper (PMID 38613387). You can find a paper's PMID on its entry on
   the Publications page, or by searching for it on PubMed.
2. Add the file to this `pdfs/` folder (via a normal commit, or by using GitHub's
   "Add file → Upload files" button on this folder's page in a browser — no command line
   needed).
3. That's it. The next time the "Update publications from PubMed" GitHub Action runs
   (automatically every Monday, or immediately, since adding a file here also triggers it),
   it will notice the matching PDF and add a "PDF" download link next to that publication's
   PubMed link automatically. You can also trigger it manually from the repo's
   **Actions → Update publications from PubMed → Run workflow** button if you don't want to
   wait.

A paper with no PDF here just won't show a PDF link — nothing else needs to change.
