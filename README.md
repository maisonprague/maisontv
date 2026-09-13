# IPTV playlists generated from iptv-org

This repository generates two M3U playlists from the current public data published by [iptv-org/iptv](https://github.com/iptv-org/iptv). It never contains a hand-maintained list of stream URLs. Each run downloads the official category index and the selected official country playlists, then writes only valid HTTP(S) streams that have matching upstream category metadata.

The project follows iptv-org's distribution model: it only republishes links from its public playlists. No paid, private, authenticated, or scraped sources are added.

## Files

- `playlists/countries.m3u` — groups are `COUNTRY | CATEGORY`, for example `CZ | Sports`.
- `playlists/categories.m3u` — groups are categories such as `Sports`; channel names are prefixed with the country, for example `[CZ] Channel`.
- `config/config.yml` — ordered, enable/disable configuration for countries and categories.

Duplicate stream URLs, non-HTTP(S) URLs, malformed M3U records, and records with missing category metadata are excluded. No availability probes run by default, so a transient stream failure cannot remove an otherwise valid record. If the essential upstream category index is unavailable, or no selected country playlist can be fetched, generation fails before either existing playlist is replaced.

## Create and publish

1. Create a new GitHub repository and push this project to its default branch (usually `main`).
2. In **Settings → Pages**, set **Build and deployment → Source** to **GitHub Actions**.
3. In **Settings → Actions → General**, allow workflows to have **Read and write permissions**. If your organization restricts Actions, also allow the actions used in `.github/workflows/update.yml`.
4. Open **Actions → Update IPTV playlists → Run workflow** to create the first playlists and deployment. It also runs every day at 03:17 UTC.

After the first successful deployment, replace the placeholders below:

```
https://<GITHUB_USERNAME>.github.io/<REPOSITORY>/playlists/countries.m3u
https://<GITHUB_USERNAME>.github.io/<REPOSITORY>/playlists/categories.m3u
```

These URLs stay constant; all 15 TiviMate installations should use the same two URLs. In TiviMate, add a playlist, choose **M3U URL**, paste one URL, and repeat for the other playlist if you want both views.

## Configuration and local run

Edit `config/config.yml`. The order of enabled `countries` and `categories` controls output order. Set `enabled: false` or remove an entry to exclude it. The `gb` entry maps to iptv-org's `uk` country-playlist path while retaining `GB` in the TiviMate group name. The generator intentionally does not invent a category when iptv-org metadata does not provide one.

Requires Python 3.11 or newer:

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt  # Windows PowerShell
.venv/Scripts/python scripts/generate_playlists.py
.venv/Scripts/python -m unittest discover -s tests -v
```

On macOS/Linux, use `.venv/bin/pip` and `.venv/bin/python`. Change the `cron` expression in `.github/workflows/update.yml` to change the schedule. Generated M3U files are deterministic for a given upstream revision and configuration.
