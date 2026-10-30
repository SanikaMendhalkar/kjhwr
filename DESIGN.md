# Technical walkthrough

## Architecture

FastAPI serves snapshot-backed JSON endpoints and pure analysis functions. React, TypeScript, Vite and Recharts provide the interface. A multi-stage Docker build compiles the UI and installs Python in one container for a straightforward local MVP.

## Ingestion and source contract

backend/ingest/fetch.py uses HTTPX, explicit 90-second timeouts, retries and exponential backoff. It fetches actuals one settlement date at a time and forecasts in one-day publication windows from December 2025 through 1 February 2026. Stream endpoints return flat arrays and expose no pagination cursor.

FUELHH is filtered to WIND and returns 48 records per January date. WINDFOR provides dataset, publishTime, startTime and generation. Elexon describes WINDFOR profiles as 49 points spanning 48 hours; the observed target cadence is hourly. Values are numeric average MW. FUELHH reporting excludes embedded generation and wind farms without operational meters. API timestamps are normalized to UTC ISO strings in CSV. Null, malformed and duplicate counts are reported. Duplicate keys use startTime and publishTime; identical rows collapse and conflicts resolve to the lexicographically greatest canonical JSON row. The actual snapshot has complete coverage; forecast hourly points cover 744 of the 1,488 half-hour actual times.

## Time, cutoff and forecast selection

backend/processing.py rejects naive timestamps and normalizes aware values to UTC. The selected cutoff combines the configured time with the previous Europe/London calendar date and converts it to UTC. Each target interval uses the maximum eligible publishTime at or before cutoff. Later publications cannot appear in the Decision view. Default 09:00 D−1 is a modelling assumption.

## Matching and metrics

Raw forecasts and actuals first join by exact startTime. For the half-hour view, a selected hourly forecast is held forward for the following :30 interval. These rows include forecastMethod=hourly_hold and sourceForecastStartTime; the raw snapshot remains unchanged. Cutoff eligibility is applied before holding, so future publications cannot enter the decision view. Daily energy sums 48 half-hour values × 0.5 hours. Errors use forecast minus actual. MAE, RMSE, bias, MAPE, WAPE and absolute-error percentiles use matched finite pairs; MAPE's near-zero threshold is 1 MW and unavailable denominators return null.

Horizon is startTime minus publishTime. Negative horizons are excluded from horizon metrics and invalid timestamps raise errors. Half-open buckets are 0–6, 6–12, 12–24, 24–48 and 48+ hours. Horizon accuracy evaluates raw publication records against actuals at hourly source cadence; Decision accuracy evaluates the latest eligible source records at cutoff and their explicitly marked hourly-hold values.

## Uncertainty

The range uses signed-error P10 and P90 from earlier delivery dates in the same horizon bucket: lower = forecast − P90 and upper = forecast − P10. Future delivery-day errors are excluded. The default minimum is 30 samples, configurable by environment. There is no fallback to an unrelated bucket. Earlier calibration errors can overlap the historical accuracy window; the range is descriptive and is not an independent validation interval.

## API and frontend

backend/main.py implements health, metadata, forecast view, client-balance, accuracy, horizon-error and error-distribution routes. Snapshot tables are cached per process. The React UI preserves the selected view, date, horizon, client requirement and interval in URL parameters; it offers date/time controls, CSV export, charts, interval table, loading/error states and methodology. The UI accepts one client MW value repeated across a selected half-hour window or a separate MW value per interval, plus an explicit assumed GB-wind share. It applies the share directly to the point-in-time national forecast and calculates interval results; it does not request or infer national demand. Utility-level proportional accuracy is not independently validated. The API retains a national-demand calculation mode for direct integration clients, though the dashboard does not expose it. Accuracy explains source selection, hourly-to-half-hour matching, metric definitions, sample counts and historical interpretation. CSS variables define the paper, petrol, orange, border and typography palette; mobile layout, keyboard focus and reduced motion are included.

## Docker, tests and trade-offs

The root Dockerfile builds the Vite app and FastAPI environment. Compose exposes port 8000 and includes a health check. A Render blueprint is provided; the container reads the platform PORT and uses an HTTP health path. Since snapshot files are baked into the image, Render's ephemeral filesystem is sufficient. App startup uses only committed snapshot data. Pytest checks cutoff leakage, timezone conversion, metrics, horizon boundaries, uncertainty sample gating and API behavior.

The MVP prioritizes point-in-time correctness, visible coverage, reproducibility and a local run. The Decision view accepts a client MW value repeated across a selected half-hour window or a separate MW value per interval, plus a fixed assumed share of GB wind. The share is applied directly to each selected forecast interval; national demand is not requested or inferred. Per interval, potential wind contribution is capped at client demand and residual is max(0, demand − allocated wind). Window energy is summed from half-hour MW × 0.5 hours. This proportional estimate is not measured utility supply or confirmed thermal procurement. Accuracy metrics describe national forecasts only. Other generation, contracts, imports, storage, losses, prices, balancing, transmission and plant constraints are out of scope. Uncertainty is descriptive and may overlap the evaluation window. Operational use requires verified interval load and portfolio data, domain review and monitoring.




