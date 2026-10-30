from datetime import date,time
import pytest
from backend.processing import cutoff_utc,select_forecasts,horizon_hours,horizon_bucket
from backend.metrics import calculate_metrics,percentile
from backend.uncertainty import uncertainty_band
from backend.scenario import calculate_balance

def test_cutoff_selection_never_leaks_later_publication():
    rows=[{"startTime":"2026-01-15T10:00:00Z","publishTime":"2026-01-14T08:55:00Z","generation":1},{"startTime":"2026-01-15T10:00:00Z","publishTime":"2026-01-14T09:05:00Z","generation":2}]
    chosen=select_forecasts(rows,date(2026,1,15),time(9))
    assert list(chosen.values())[0]["generation"]==1

def test_cutoff_utc_and_timezone_boundary():
    # January London is UTC; preceding local calendar date is used.
    assert cutoff_utc(date(2026,1,2),time(9)).isoformat()=="2026-01-01T09:00:00+00:00"
    assert select_forecasts([{"startTime":"2026-01-01T23:00:00Z","publishTime":"2025-12-31T09:00:00Z","generation":9}],date(2026,1,1),time(9))

def test_no_eligible_forecast():
    assert select_forecasts([{"startTime":"2026-01-15T10:00:00Z","publishTime":"2026-01-14T09:01:00Z","generation":1}],date(2026,1,15),time(9))=={}

def test_metrics_known_values_and_near_zero():
    m=calculate_metrics([(10,8),(8,10),(50,0)])
    assert m["maeMw"]==pytest.approx(54/3)
    assert m["rmseMw"]==pytest.approx((4+4+2500)**.5/3**.5)
    assert m["biasMw"]==pytest.approx(50/3)
    assert m["mapeCount"]==2 and m["mapeExcludedNearZero"]==1
    assert m["wapePct"]==pytest.approx(54/18*100)

def test_metrics_unavailable_on_empty_and_percentile():
    assert calculate_metrics([])["maeMw"] is None
    assert calculate_metrics([(2,0)])["wapePct"] is None
    assert percentile([0,10],.9)==pytest.approx(9)

@pytest.mark.parametrize("h,b",[(0,"0–6 h"),(5.99,"0–6 h"),(6,"6–12 h"),(12,"12–24 h"),(24,"24–48 h"),(48,"48+ h")])
def test_horizon_boundaries(h,b): assert horizon_bucket(h)==b

def test_horizon_and_invalid_values():
    assert horizon_hours("2026-01-02T12:00:00Z","2026-01-02T06:00:00Z")==6
    with pytest.raises(ValueError): horizon_bucket(-.1)
    with pytest.raises(ValueError): horizon_hours("2026-01-02T12:00:00","2026-01-02T06:00:00Z")

def test_uncertainty_bounds_and_insufficient_sample():
    refs=[{"errorMw":i,"deliveryDate":"2026-01-01","horizonBucket":"0–6 h"} for i in range(40)]
    refs.append({"errorMw":100000,"deliveryDate":"2026-01-03","horizonBucket":"0–6 h"})
    band=uncertainty_band(100,2,refs,"2026-01-02",30)
    assert band["lowerMw"]<=band["upperMw"] and band["sampleCount"]==40
    assert band["upperMw"]<100
    assert uncertainty_band(100,2,refs,"2026-01-02",41)["lowerMw"] is None

def test_client_balance_interval_energy_contribution_and_surplus():
    result=calculate_balance([
        {"startTime":"a","demandMw":100,"forecastMw":80,"lowerMw":70,"upperMw":90},
        {"startTime":"b","demandMw":50,"forecastMw":80,"lowerMw":70,"upperMw":90},
    ],100)
    first,second=result["intervals"]
    assert first["potentialContributionMw"]==80 and first["residualMw"]==20
    assert second["potentialContributionMw"]==50 and second["residualMw"]==0 and second["windSurplusMw"]==30
    assert result["summary"]["demandMWh"]==75
    assert result["summary"]["potentialContributionMWh"]==65
    assert result["summary"]["residualMWh"]==10
    assert first["residualLowerMw"]==10 and first["residualUpperMw"]==30

def test_client_balance_missing_forecast_is_excluded_not_filled():
    result=calculate_balance([{"demandMw":100,"forecastMw":None}],50)
    assert result["intervals"][0]["balanceValid"] is False
    assert result["summary"]["matchedIntervals"]==0
    assert result["summary"]["demandMWh"]==0
    assert result["summary"]["potentialWindCoveragePct"] is None
    assert result["summary"]["coverageComplete"] is False

def test_client_balance_rejects_invalid_share_and_missing_uncertainty():
    with pytest.raises(ValueError): calculate_balance([],101)
    result=calculate_balance([{"demandMw":1,"forecastMw":1,"lowerMw":None,"upperMw":None}],50)
    assert result["summary"]["residualLowerMWh"] is None

def test_client_balance_complete_half_hour_day_and_zero_demand():
    day=[{"startTime":str(i),"demandMw":10,"forecastMw":6,"lowerMw":5,"upperMw":7} for i in range(48)]
    result=calculate_balance(day,50)
    assert result["summary"]["coverageComplete"] is True
    assert result["summary"]["demandMWh"]==240
    assert result["summary"]["forecastWindMWh"]==72
    assert result["summary"]["potentialContributionMWh"]==72
    assert result["summary"]["residualMWh"]==168
    assert result["summary"]["potentialWindCoveragePct"]==30
    zero=calculate_balance([{"demandMw":0,"forecastMw":4}],100)
    assert zero["summary"]["potentialWindCoveragePct"] is None

def test_proportional_allocation_fixed_share_is_direct_not_scaled_twice():
    result=calculate_balance([{"startTime":"a","demandMw":40,"forecastMw":200}],20)
    row=result["intervals"][0]
    assert row["clientSharePct"]==20
    assert row["estimatedAllocatedWindMw"]==40
    assert row["residualMw"]==0
    assert row["potentialContributionMw"]==40
    assert result["summary"]["providedDemandMWh"]==20

def test_proportional_allocation_uses_interval_national_demand_and_validates_it():
    row={"startTime":"a","demandMw":50,"nationalDemandMw":500,"forecastMw":200}
    result=calculate_balance([row])
    assert result["intervals"][0]["clientSharePct"]==10
    assert result["intervals"][0]["allocatedWindMw"]==20
    assert result["intervals"][0]["residualMw"]==30
    assert result["summary"]["nationalDemandMWh"]==250
    with pytest.raises(ValueError,match="greater than zero"):
        calculate_balance([{**row,"nationalDemandMw":0}])
    with pytest.raises(ValueError,match="cannot exceed 100%"):
        calculate_balance([{**row,"demandMw":600}])
    missing=calculate_balance([{"demandMw":50,"forecastMw":200,"nationalDemandMw":None}])
    assert missing["intervals"][0]["allocatedWindMw"] is None
    assert missing["summary"]["matchedIntervals"]==0

def test_proportional_daily_aggregation_and_incomplete_intervals():
    day=[{"startTime":str(i),"demandMw":10,"nationalDemandMw":100,"forecastMw":80} for i in range(48)]
    result=calculate_balance(day)
    assert result["summary"]["coverageComplete"] is True
    assert result["summary"]["demandMWh"]==240
    assert result["summary"]["nationalDemandMWh"]==2400
    assert result["summary"]["forecastWindMWh"]==192
    assert result["summary"]["residualMWh"]==48
    partial=calculate_balance(day[:47]+[{**day[-1],"nationalDemandMw":None}])
    assert partial["summary"]["matchedIntervals"]==47
    assert partial["summary"]["coverageComplete"] is False
    assert partial["summary"]["providedDemandMWh"]==240
    assert partial["summary"]["demandMWh"]==235
