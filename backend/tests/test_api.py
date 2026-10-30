import pytest
from fastapi import HTTPException
from backend import main

def test_meta_and_forecast_schema():
    meta=main.meta()
    assert meta["actualRecordCount"]==1488
    assert meta["forecastRecordCount"]==18104
    view=main.forecast_view("2026-01-15","09:00")
    assert view["summary"]["expectedIntervals"]==48
    assert {"forecastMw","actualMw","publishTime","horizonHours","lowerMw","upperMw","quality"}<=set(view["intervals"][0])

def test_invalid_dates_are_4xx():
    with pytest.raises(HTTPException) as exc: main.forecast_view("2026-02-01","09:00")
    assert exc.value.status_code==422
    with pytest.raises(HTTPException) as exc: main.accuracy("2026-01-20","2026-01-01","09:00")
    assert exc.value.status_code==422

def test_analysis_endpoint_results():
    h=main.horizon_error("2026-01-01","2026-01-31")
    d=main.error_distribution("2026-01-01","2026-01-31","09:00")
    assert len(h["buckets"])==5 and "sampleCount" in d

def test_client_balance_endpoint_uses_selected_forecast_and_flags_coverage():
    request=main.ClientBalanceRequest(deliveryDate="2026-01-15",cutoffTime="09:00",windSharePct=5,
        demandIntervals=[{"startTime":"2026-01-15T00:00:00Z","demandMw":1000}])
    result=main.client_balance(request)
    assert result["summary"]["matchedIntervals"]==1
    assert result["summary"]["coverageComplete"] is False
    assert result["intervals"][0]["potentialContributionMw"] is not None
    assert result["summary"]["demandMWh"]==500

def test_client_balance_national_demand_reference_and_explicit_share_modes():
    point={"startTime":"2026-01-15T00:00:00Z","demandMw":1000,"nationalDemandMw":20000}
    request=main.ClientBalanceRequest(deliveryDate="2026-01-15",allocationMode="national_demand",demandIntervals=[point])
    result=main.client_balance(request)
    assert result["intervals"][0]["clientSharePct"]==5
    assert result["intervals"][0]["allocatedWindMw"]==pytest.approx(result["intervals"][0]["forecastMw"]*.05)
    assert result["allocationMode"]=="national_demand"
    unavailable=main.client_balance(main.ClientBalanceRequest(deliveryDate="2026-01-15",allocationMode="national_demand",demandIntervals=[{"startTime":point["startTime"],"demandMw":1000}]))
    assert unavailable["intervals"][0]["allocatedWindMw"] is None
    with pytest.raises(HTTPException) as exc:
        main.client_balance(main.ClientBalanceRequest(deliveryDate="2026-01-15",allocationMode="share",demandIntervals=[{"startTime":point["startTime"],"demandMw":1000}]))
    assert exc.value.status_code==422

def test_client_balance_rejects_zero_national_demand_and_double_scaling():
    with pytest.raises(Exception):
        main.ClientBalanceRequest(deliveryDate="2026-01-15",allocationMode="national_demand",demandIntervals=[{"startTime":"2026-01-15T00:00:00Z","demandMw":1,"nationalDemandMw":0}])
    with pytest.raises(HTTPException) as exc:
        main.client_balance(main.ClientBalanceRequest(deliveryDate="2026-01-15",allocationMode="national_demand",windSharePct=5,demandIntervals=[]))
    assert exc.value.status_code==422
    with pytest.raises(HTTPException) as exc:
        main.client_balance(main.ClientBalanceRequest(deliveryDate="2026-01-15",allocationMode="share",windSharePct=5,demandIntervals=[{"startTime":"2026-01-15T00:00:00Z","demandMw":10,"nationalDemandMw":100}]))
    assert exc.value.status_code==422

def test_client_balance_rejects_duplicate_negative_and_bad_time():
    with pytest.raises(Exception):
        main.ClientBalanceRequest(deliveryDate="2026-01-15",windSharePct=5,
            demandIntervals=[{"startTime":"2026-01-15T00:00:00Z","demandMw":-1}])
    request=main.ClientBalanceRequest(deliveryDate="2026-01-15",windSharePct=5,
        demandIntervals=[{"startTime":"2026-01-15T00:00:00Z","demandMw":10},{"startTime":"2026-01-15T00:00:00+00:00","demandMw":10}])
    with pytest.raises(HTTPException) as exc: main.client_balance(request)
    assert exc.value.status_code==422

def test_client_balance_rejects_naive_off_grid_and_wrong_day():
    for timestamp in ["2026-01-15T00:00:00", "2026-01-15T00:15:00Z", "2026-01-16T00:00:00Z"]:
        request=main.ClientBalanceRequest(deliveryDate="2026-01-15",windSharePct=5,
            demandIntervals=[{"startTime":timestamp,"demandMw":10}])
        with pytest.raises(HTTPException) as exc: main.client_balance(request)
        assert exc.value.status_code==422

def test_client_balance_rejects_blank_timestamp_and_share_over_100():
    with pytest.raises(Exception):
        main.ClientBalanceRequest(deliveryDate="2026-01-15",windSharePct=101,
            demandIntervals=[{"startTime":"2026-01-15T00:00:00Z","demandMw":10}])
    with pytest.raises(Exception):
        main.ClientBalanceRequest(deliveryDate="2026-01-15",windSharePct=5,
            demandIntervals=[{"startTime":"","demandMw":10}])
