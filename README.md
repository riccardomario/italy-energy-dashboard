# Italy Energy Dashboard

Interactive daily dashboard of Italian power-system data (load, generation by
technology, cross-border flows) sourced from the ENTSO-e Transparency Platform.

- **Live dashboard**: _to be added after first deploy_
- **Data source**: [ENTSO-e Transparency Platform](https://transparency.entsoe.eu/) API
- **Coverage**: 2016 → present, 7 Italian bidding zones, hourly resolution

## Architecture

```
GitHub repo (this)
   |
   |-- GitHub Actions cron (06:00 UTC daily, 06:00 UTC day 1 monthly)
   |       fetches latest ENTSO-e data, updates parquet files, commits back
   |
   `-- Streamlit Community Cloud
           reads parquet files, serves password-protected dashboard
```

## Local setup

```powershell
py -m pip install -r requirements.txt
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
# edit .streamlit\secrets.toml with your ENTSO-e token and a dashboard password
```

## One-time backfill (2016 -> today)

```powershell
py pipeline\backfill.py
```

Runs ~30-60 minutes, writes `data\load.parquet`, `data\generation.parquet`,
`data\flows.parquet`. Commit these files to the repo after the run.

## Run the dashboard locally

```powershell
py -m streamlit run dashboard\Home.py
```

## Local backup to Excel

```powershell
py tools\export_to_excel.py
```

Produces a `.xlsx` workbook (one sheet per technology) in the project folder.

## Project layout

```
.github/workflows/   GitHub Actions cron jobs
data/                Parquet files (committed)
pipeline/            ENTSO-e fetch + update scripts
dashboard/           Streamlit app (Home + pages/)
tools/               On-demand utilities (Excel export, etc.)
.streamlit/          Streamlit config and secrets template
```
