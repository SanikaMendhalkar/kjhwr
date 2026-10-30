# WindGauge

WindGauge is a locally runnable analyst dashboard for reconstructing GB wind forecasts available at a chosen day-ahead cutoff and comparing them with actual wind generation. It is forecast analysis and scenario support, not trading automation or a complete procurement plan.

## Features

- Decision reconstruction with configurable D−1 cutoff, publication time per source forecast, half-hourly matched actuals, daily forecast energy and CSV export.
- Accuracy view with MAE, RMSE, bias, absolute-error percentiles, daily chart, error distribution and horizon buckets, plus an explanation of forecast selection, matching, scoring and uncertainty.
- Proportional allocation scenario: select a delivery date and half-hour range, enter one customer requirement in MW to repeat or a separate MW value per half-hour, and provide an explicit assumed share of GB wind. The fixed share is applied directly to each point-in-time national forecast; no national-demand data is requested. Customer energy, estimated wind contribution and indicative residual are calculated per interval and summed as MWh.
- Indicative empirical uncertainty range when enough same-horizon historical errors are available.
- URL state, native keyboard-friendly date and time controls, responsive design and documented assumptions.

## Snapshot and data quality

Data was retrieved from the public Elexon BMRS Insights API v1 on 29 October 2026. Actuals use FUELHH with settlementDateFrom, settlementDateTo and fuelType=WIND. Forecasts use WINDFOR filtered by publishDateTimeFrom and publishDateTimeTo. The [FUELHH stream](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream) and [WINDFOR stream](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream) return flat JSON rows. The stream endpoints expose no pagination cursor, so ingestion uses bounded daily requests with retries. Elexon documents generation by fuel type as average MW and notes that its renewable outturn excludes embedded generation and wind farms without operational meters ([data notes](https://bmrs.elexon.co.uk/generation-by-fuel-type)).

- Actuals: 1,488 national WIND rows; all 1,488 expected half-hour intervals present; no null, malformed or duplicate warnings. The Elexon total is limited to generation visible to its metering and reporting scope.
- Forecasts: 18,104 records with publishTime preserved and 744 unique January target intervals.
- WINDFOR targets are hourly while FUELHH actuals are half-hourly. The raw snapshot retains 744 hourly source targets; the Decision and Accuracy views carry each eligible hourly forecast forward to the following :30 interval and mark it as hourly_hold. Raw source files stay unchanged.
- Elexon describes WINDFOR profiles as 49 values spanning 48 hours, and the observed target cadence is hourly. Dashboard energy sums 48 half-hour values as MW × 0.5 hours; each hourly source forecast contributes one hour across its exact and held intervals.
- The full coverage, missing target list, warnings and refresh timestamp are in data/data-quality.json.

## Selection and analysis

All timestamps are timezone-aware and normalized to UTC internally. A cutoff uses Europe/London on the preceding local calendar day. The latest forecast published at or before the cutoff is selected for each hourly target startTime. That value is held for the following half-hour when matching FUELHH; derived rows expose forecastMethod=hourly_hold and the original source target time. The default 09:00 D−1 cutoff is a configurable modelling assumption, not an asserted market deadline.

Error is forecast minus actual in MW; positive means overforecast. Decision and Accuracy metrics use the hourly source point plus its derived hourly-hold half-hour match, yielding up to 48 matched periods per complete day. MAPE excludes actual values with absolute magnitude at or below 1 MW. WAPE is unavailable when total absolute actual generation is zero. Percentiles use linear interpolation. Horizon is startTime minus publishTime with half-open groups 0–6, 6–12, 12–24, 24–48 and 48+ hours. Horizon accuracy evaluates raw publication records at source cadence; Decision accuracy evaluates cutoff-selected source forecasts and identified hourly-hold values.

The Decision view accepts one client MW value repeated across a selected window or a list of client MW values, one per half-hour. It converts each interval to MWh as MW × 0.5, applies the user-entered assumed GB-wind share directly to the point-in-time Elexon forecast, and calculates wind contribution and residual per interval before summing the window energy. No national-demand input or inferred share is used. Missing forecast intervals are flagged; totals are withheld unless the selected window has full forecast coverage. Proportional scaling is an estimate, not contracted wind or confirmed thermal procurement; national wind is not necessarily distributed in proportion to demand. Contracts, dispatch, transmission constraints, storage, imports, losses and other generation are outside scope.

Uncertainty uses signed-error P10/P90 from earlier delivery days in the same horizon bucket (no future delivery-day errors are used for a decision date). Lower = forecast − P90(error), upper = forecast − P10(error). At least 30 comparable errors are required, with no cross-bucket fallback. The historical reference may overlap the accuracy evaluation window, so the band is descriptive rather than independent validation and is not guaranteed.

## Architecture

    Elexon API -> manual ingestion -> CSV snapshot and quality report
    React + TypeScript + Vite + Recharts -> FastAPI analysis API
    Docker builds the UI and backend into one container

Business logic lives separately from HTTP routes. The serving application reads only the committed snapshot.

## Local run

Requires Python 3.11+ and Node 20+.

    python -m pip install -r backend/requirements-dev.txt
    python -m uvicorn backend.main:app --reload --port 8000

In another terminal:

    cd frontend
    npm install
    npm run dev

Open http://localhost:5173. Vite proxies the API to port 8000.

## Docker

    docker compose up --build

Open http://localhost:8000. The container has a health check and does not contact Elexon during startup. Configure CORS_ORIGINS and UNCERTAINTY_MIN_SAMPLES for hosted deployments.

## Tests and build

    python -m pytest
    cd frontend
    npm run build

The ingestion command is python -m backend.ingest.fetch. Review data/data-quality.json before replacing the committed snapshot.

## Deployment

Vercel is configured to build the root Dockerfile with its Container preset (`vercel.json`). The image serves both the React interface and FastAPI endpoints from one process and reads the included data snapshot. Vercel's Container runtime is currently in beta and uses usage-based compute. Its free Hobby plan is for personal, non-commercial projects; a client/company deployment needs an eligible paid plan. To enable automatic deployments on GitHub pushes, create a GitHub repository, push this project, and import it into Vercel. The current workspace has no GitHub or Vercel credentials, so no public deployment is claimed yet. See [Vercel Docker containers](https://vercel.com/changelog/deploy-a-container-from-a-plain-dockerfile), [Vercel Hobby plan](https://vercel.com/docs/plans/hobby), and [GitHub integration](https://vercel.com/docs/git/vercel-for-github).

## Limitations

Coverage is January 2026 only. The committed raw data retains the hourly WINDFOR cadence; dashboard half-hour values after each exact hourly point use the clearly marked hourly-hold assumption. The cutoff is an assumption. Client demand is entered for the chosen horizon, and is compared with total GB wind as a scale reference only. A client-specific procurement workflow would need the client's load forecast and verified contracted/portfolio allocation, plus other generation and market positions.

## AI disclosure

AI assistance: OpenAI Codex was used to assist with implementation, debugging, testing and documentation. Data retrieval, calculations, tests and assumptions were reviewed against the returned Elexon records and public documentation during development.

## Screenshots

No screenshots are committed yet. The views are available locally after startup.


