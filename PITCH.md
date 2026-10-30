# WindGauge — client pitch

## The problem

Wind output depends on weather, and forecasts change as new information arrives. A retrospective analysis can mislead if it uses a forecast published after the purchasing decision.

## The proposal

WindGauge reconstructs the Elexon wind forecast available at a selected day-ahead cutoff, then evaluates it against actual wind generation. The main dashboard adds a transparent proportional allocation scenario using an explicit client-entered share of GB wind; it does not require national-demand data. It is an analyst aid, not an automated purchasing recommendation.

## Demonstration

Choose a January 2026 delivery date and D−1 cutoff. Select a half-hour time window and enter the client’s MW requirement for each interval, along with an explicit assumed share of GB wind. WindGauge applies that share to each selected forecast interval, then sums the client energy requirement, estimated wind contribution and indicative residual as MWh. Review the publication timestamp and lead per interval, and explain that this proportional estimate is not contracted supply or confirmed thermal procurement. Then open Accuracy to compare national forecast MAE, RMSE, signed bias, P95 absolute error and errors by horizon.

## Interpretation and value

The latest forecast published by the cutoff is selected per hourly target interval; it is held into the following half-hour and visibly marked as derived. Error is forecast minus actual, so positive means overforecast. MAE describes typical absolute miss; RMSE weights larger misses more heavily; bias gives direction. Absolute-error percentiles show the size of larger misses. The uncertainty range is a same-horizon empirical residual range, not a guarantee. Visible publication and coverage data gives analysts a reproducible way to discuss wind forecast uncertainty in day-ahead planning.

## Limitations and next steps

WINDFOR is hourly and FUELHH is half-hourly. The source snapshot remains hourly; the dashboard derives the following half-hour with a visible hourly-hold marker. Coverage is January 2026. The entered MW requirement is held constant across the selected intervals. The GB-wind share is a user-supplied assumption applied directly; no national-demand input is used. Proportional allocation does not model how wind is actually distributed to utilities, and its utility-level accuracy has not been validated. Residual is not a confirmed thermal requirement and excludes other generation, contracts, imports, storage, losses, balancing, prices, transmission and plant constraints. Accuracy metrics remain national-forecast metrics. A pilot should use verified half-hourly client demand and portfolio allocation before operational use.

