# Queer Community, Service Directory

Deploy this folder to GitHub Pages.

Upload these items to the root of a GitHub repository:

- `index.html`
- `build_site.py`
- `requirements.txt`
- `queer_community_service_directory_poster.png`
- `.github/workflows/update-directory.yml`

The workflow rebuilds `index.html` from the published Google Sheets CSV every month and can also be run manually from GitHub Actions.

Moderation: add a column named `Approved` in the Google Sheet. Once that column exists, only rows with `yes`, `y`, `true`, `1`, or `approved` go live.
