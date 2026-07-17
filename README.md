# SURVEY CORPS — Guild Skill Register

Static site that mirrors a public Google Sheet skill register for the
Milky Way Idle guild **SURVEY CORPS**, and publishes it to GitHub Pages.

The pipeline is one-directional and credential-free:

```
public Google Sheet  ──(anonymous CSV export)──▶  Python  ──▶  _site/  ──▶  GitHub Pages
```

No Google Sheets writes, no API keys, no service accounts. It only reads the
sheet's published CSV export (`?format=csv`), which works because the sheet is
shared as "anyone with the link".

## What it does

1. **Fetch** the sheet as CSV (`src/reader.py`).
2. **Parse** it into typed `MemberRow` / `SkillEntry` dataclasses, validating the
   header against sentinel columns so a sheet restructure fails loudly.
3. **Process** rows into a summary (`src/processor.py`) — *this is the seam for
   future custom logic*; today it computes member count and per-skill averages.
4. **Build** `_site/index.html` (self-contained, inline CSS) and
   `_site/data.json` (`src/build.py`).

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

python -m pytest tests/ -v      # offline unit tests
python -m src.build             # live fetch -> writes _site/
open _site/index.html
```

## Deploy (GitHub Actions)

`.github/workflows/deploy.yml` builds and deploys on an hourly schedule and on
manual dispatch, using the artifact-based Pages flow
(`actions/upload-pages-artifact` + `actions/deploy-pages`).

### One-time manual step

After pushing to GitHub, enable Pages:

> **Settings → Pages → Build and deployment → Source: GitHub Actions**

Then trigger the workflow once from the **Actions** tab (or wait for the hourly
schedule). Subsequent runs update the site automatically.

## Configuration

All layout assumptions live in `src/config.py` (spreadsheet ID, CSV URL, ordered
skill list, column offsets, and header sentinels). If the sheet layout changes,
`src/build.py` exits non-zero with a `SheetStructureError` describing the
mismatch — update `config.py` to match the new layout.
