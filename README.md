# Lottery Tracker Pro — Web Edition

Phone-friendly website for Maryland Pick 3, Pick 4, Pick 5, Multi-Match, and Powerball. No invented winning numbers.

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:5000`. Click **Check new draws** to request results.

## Deploy

Upload this project to a GitHub repository and create a Python web service on Render using the included `render.yaml`, or deploy to any host that supports Python/Flask. Set the startup command to `gunicorn --bind 0.0.0.0:$PORT app:app`.

**Important:** On free/ephemeral hosting, SQLite data may be lost when the service restarts. Attach a persistent disk and set `LOTTERY_DB` to its file path for durable year-long records. A persistent hosting plan or database is needed for reliable background ingestion.

## Automatic results

The app provides an on-demand refresh endpoint (`POST /api/refresh`). To check periodically after draws, configure an external scheduler/cron service to POST to your hosted `/api/refresh` endpoint. **The included app does not itself run a guaranteed always-on scheduler.** Protect this endpoint before exposing a heavily used public site. Powerball uses NY Open Data, which may lag drawings. Maryland Lottery publishes a limited recent history, and its website markup can change. If the Maryland parser cannot verify a row, it reports an error instead of displaying fabricated results. You must verify the parser against live source HTML after deployment. Historical years require a separate backfill source or import capability.

## Statistics

For Pick games, frequency counts **digits that appear at least once in a drawing**, not exact 3/4/5-digit combinations. Exact-combination search is available in Draw History. Multi-Match/Powerball frequency counts main balls; Powerball red-ball frequency is not yet charted separately. Missed drawings means the number was absent from the most recent loaded records; it is not a forecast.
