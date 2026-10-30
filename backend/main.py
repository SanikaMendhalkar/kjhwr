"""FastAPI application for the committed WindGauge snapshot."""
from __future__ import annotations
import csv, json, os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Literal
from fastapi.middleware.cors import CORSMiddleware
from functools import lru_cache
from backend.metrics import calculate_metrics, percentile
from backend.processing import cutoff_utc, horizon_bucket, horizon_hours, parse_utc, select_forecasts
from backend.uncertainty import uncertainty_band
from backend.scenario import calculate_balance

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"data"; LONDON=ZoneInfo("Europe/London")
app=FastAPI(title="WindGauge API",version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("CORS_ORIGINS","*").split(","),allow_methods=["GET","POST"],allow_headers=["*"])
FORECASTS_BY_DELIVERY: dict[str,list[dict]] = {}

class DemandPoint(BaseModel):
    startTime: str = Field(min_length=1)
    demandMw: float = Field(ge=0, allow_inf_nan=False)
    nationalDemandMw: float | None = Field(default=None, gt=0, allow_inf_nan=False)

class ClientBalanceRequest(BaseModel):
    deliveryDate: date
    cutoffTime: str = "09:00"
    allocationMode: Literal["share", "national_demand"] = "share"
    windSharePct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    demandIntervals: list[DemandPoint]

@lru_cache(maxsize=1)
def load_snapshot():
    global FORECASTS_BY_DELIVERY
    a,f,q=DATA/"actuals.csv",DATA/"forecasts.csv",DATA/"data-quality.json"
    if not a.exists() or not f.exists() or not q.exists(): raise HTTPException(503,"Validated data snapshot is unavailable. Run python -m backend.ingest.fetch.")
    def read(path):
        with path.open(encoding="utf-8",newline="") as fp: return list(csv.DictReader(fp))
    actual=[{"startTime":r["startTime"],"publishTime":r["publishTime"],"generation":float(r["generation"]) if r.get("generation") else None} for r in read(a)]
    forecasts=[{"startTime":r["startTime"],"publishTime":r["publishTime"],"generation":float(r["generation"]) if r.get("generation") else None} for r in read(f)]
    by_delivery: dict[str,list[dict]] = {}
    for row in forecasts:
        local_date=parse_utc(row["startTime"]).astimezone(LONDON).date().isoformat()
        by_delivery.setdefault(local_date,[]).append(row)
    FORECASTS_BY_DELIVERY=by_delivery
    return actual,forecasts,json.loads(q.read_text(encoding="utf-8"))

def num(x): return round(x,2) if x is not None else None
def selected_day(delivery:date,cutoff:time,actual,forecasts,quality,with_band=True):
    day_forecasts=FORECASTS_BY_DELIVERY.get(delivery.isoformat(),forecasts)
    selected=select_forecasts(day_forecasts,delivery,cutoff); actual_map={parse_utc(r["startTime"]).isoformat():r for r in actual}
    start=datetime.combine(delivery,datetime.min.time(),LONDON).astimezone(ZoneInfo("UTC"))
    stop=(datetime.combine(delivery,datetime.min.time(),LONDON)+timedelta(days=1)).astimezone(ZoneInfo("UTC"))
    intervals=[]; cursor=start
    reference=[]
    # Build this population only for the decision view's uncertainty band.
    if with_band:
        for fr in forecasts:
            ar=actual_map.get(parse_utc(fr["startTime"]).isoformat())
            if ar and fr.get("generation") is not None and ar.get("generation") is not None:
                h=horizon_hours(fr["startTime"],fr["publishTime"])
                if h>=0:
                    reference.append({"errorMw":fr["generation"]-ar["generation"],"deliveryDate":parse_utc(fr["startTime"]).astimezone(LONDON).date().isoformat(),"horizonBucket":horizon_bucket(h)})
    while cursor<stop:
        key=cursor.isoformat(); f=selected.get(key); method="exact"
        if f is None and cursor.minute==30:
            source=selected.get((cursor-timedelta(minutes=30)).isoformat())
            if source is not None:
                f={**source,"sourceForecastStartTime":source["startTime"],"startTime":cursor.isoformat().replace("+00:00","Z")}
                method="hourly_hold"
        elif f is not None:
            f={**f,"sourceForecastStartTime":f["startTime"]}
        a=actual_map.get(key)
        forecast=f.get("generation") if f else None; actual_value=a.get("generation") if a else None
        horizon=horizon_hours(f["startTime"],f["publishTime"]) if f and f.get("publishTime") else None
        band=uncertainty_band(forecast,horizon,reference,delivery.isoformat(),int(os.getenv("UNCERTAINTY_MIN_SAMPLES","30"))) if with_band and forecast is not None and horizon is not None else {"lowerMw":None,"upperMw":None,"sampleCount":0,"reason":"No eligible forecast." if not f else "Forecast value unavailable."}
        intervals.append({"startTime":cursor.isoformat().replace("+00:00","Z"),"forecastMw":num(forecast),"forecastMethod":method if f else None,"sourceForecastStartTime":f.get("sourceForecastStartTime") if f else None,"publishTime":f.get("publishTime") if f else None,"actualMw":num(actual_value),"errorMw":num(forecast-actual_value) if forecast is not None and actual_value is not None else None,"horizonHours":num(horizon),"lowerMw":num(band.get("lowerMw")),"upperMw":num(band.get("upperMw")),"uncertaintySampleCount":band.get("sampleCount"),"quality":"matched" if forecast is not None and actual_value is not None else "missing forecast" if forecast is None else "missing actual"})
        cursor+=timedelta(minutes=30)
    valid=[r for r in intervals if r["forecastMw"] is not None]; pairs=[(r["forecastMw"],r["actualMw"]) for r in intervals if r["forecastMw"] is not None and r["actualMw"] is not None]
    vals=[r["forecastMw"] for r in valid]
    pubs=sorted({r["publishTime"] for r in intervals if r["publishTime"]})
    exact_count=sum(r["forecastMethod"]=="exact" for r in intervals)
    held_count=sum(r["forecastMethod"]=="hourly_hold" for r in intervals)
    return {"deliveryDate":delivery.isoformat(),"cutoffLocal":datetime.combine(delivery-timedelta(days=1),cutoff,LONDON).isoformat(),"cutoffUtc":cutoff_utc(delivery,cutoff).isoformat().replace("+00:00","Z"),"intervals":intervals,"summary":{"expectedIntervals":len(intervals),"forecastIntervals":len(valid),"exactForecastIntervals":exact_count,"hourlyHeldIntervals":held_count,"matchedIntervals":len(pairs),"dailyForecastEnergyMWh":num(sum(vals)*.5) if vals else None,"energyMethod":"Hourly forecast MW is held over the following half-hour for display and matching; each displayed half-hour contributes MW × 0.5 h. Held values are identified and are not source records.","peakForecastMw":max(vals) if vals else None,"minimumForecastMw":min(vals) if vals else None,"publicationTimes":pubs,"distinctPublicationCount":len(pubs),"metrics":calculate_metrics(pairs)},"coverageLimitations":quality.get("knownLimitations",[])}

def parse_date(value:str)->date:
    try: return date.fromisoformat(value)
    except ValueError: raise HTTPException(422,"Date must use YYYY-MM-DD.")
def parse_time(value:str)->time:
    try: return time.fromisoformat(value)
    except ValueError: raise HTTPException(422,"Cutoff time must use HH:MM.")
def validate_range(start,end):
    if start>end: raise HTTPException(422,"Start date must be on or before end date.")
    if (end-start).days>366: raise HTTPException(422,"Date range cannot exceed 367 days.")
    if start<date(2026,1,1) or end>date(2026,1,31): raise HTTPException(422,"This snapshot covers January 2026 only.")

@app.get("/api/health")
def health():
    return {"status":"ok","snapshotAccessible":all((DATA/x).exists() for x in ["actuals.csv","forecasts.csv","data-quality.json"])}

@app.get("/api/meta")
def meta():
    actual,forecasts,q=load_snapshot()
    return {"availableDeliveryDateRange":q["requestedDeliveryRange"],"defaultCutoffTime":"09:00","timezone":"Europe/London; timestamps compared in UTC","actualRecordCount":len(actual),"forecastRecordCount":len(forecasts),"snapshotRefreshDate":q["retrievedAtUtc"],"dataQuality":q,"knownLimitations":q.get("knownLimitations",[])}

@app.get("/api/forecast-view")
def forecast_view(delivery_date:str=Query(...),cutoff_time:str="09:00"):
    d=parse_date(delivery_date); c=parse_time(cutoff_time)
    if not date(2026,1,1)<=d<=date(2026,1,31): raise HTTPException(422,"Delivery date must be in January 2026.")
    a,f,q=load_snapshot(); return selected_day(d,c,a,f,q)

@app.post("/api/client-balance")
def client_balance(request: ClientBalanceRequest):
    d=request.deliveryDate; c=parse_time(request.cutoffTime)
    if not date(2026,1,1)<=d<=date(2026,1,31): raise HTTPException(422,"Delivery date must be in January 2026.")
    if request.allocationMode == "share" and request.windSharePct is None:
        raise HTTPException(422,"Enter an explicit assumed client share percentage.")
    if request.allocationMode == "national_demand" and request.windSharePct is not None:
        raise HTTPException(422,"Choose either a national-demand reference or a fixed assumed share, not both.")
    if request.allocationMode == "share" and any(p.nationalDemandMw is not None for p in request.demandIntervals):
        raise HTTPException(422,"Fixed-share mode cannot also include national-demand references.")
    demand={}
    for point in request.demandIntervals:
        try: stamp=parse_utc(point.startTime)
        except (ValueError, TypeError): raise HTTPException(422,"Demand timestamps must be valid and include a timezone.")
        local=stamp.astimezone(LONDON)
        if local.date()!=d or local.minute not in (0,30) or local.second or local.microsecond:
            raise HTTPException(422,"Demand timestamps must be half-hour intervals on the selected delivery date (UK time).")
        key=stamp.isoformat()
        if key in demand: raise HTTPException(422,"Duplicate demand interval timestamp.")
        demand[key]={"demandMw":point.demandMw,"nationalDemandMw":point.nationalDemandMw}
    actual,forecasts,quality=load_snapshot()
    snapshot=selected_day(d,c,actual,forecasts,quality)
    intervals=[]
    for row in snapshot["intervals"]:
        key=parse_utc(row["startTime"]).isoformat()
        intervals.append({**row,**demand.get(key,{"demandMw":None,"nationalDemandMw":None})})
    try:
        result=calculate_balance(intervals,request.windSharePct)
    except ValueError as exc: raise HTTPException(422,str(exc))
    result.update({"deliveryDate":d.isoformat(),"cutoffLocal":snapshot["cutoffLocal"],"allocationMode":request.allocationMode,"windSharePct":request.windSharePct,"forecastSummary":snapshot["summary"],"coverageLimitations":snapshot["coverageLimitations"]})
    return result

@app.get("/api/accuracy")
def accuracy(start:str,end:str,cutoff_time:str="09:00"):
    s,e=parse_date(start),parse_date(end); validate_range(s,e); c=parse_time(cutoff_time); a,f,q=load_snapshot()
    days=[]; all_pairs=[]; series=[]
    for offset in range((e-s).days+1):
        result=selected_day(s+timedelta(days=offset),c,a,f,q,False); pairs=[(r["forecastMw"],r["actualMw"]) for r in result["intervals"] if r["forecastMw"] is not None and r["actualMw"] is not None]; all_pairs+=pairs
        series.extend({"startTime":r["startTime"],"forecastMw":r["forecastMw"],"actualMw":r["actualMw"]} for r in result["intervals"])
        days.append({"deliveryDate":result["deliveryDate"],**result["summary"]["metrics"],"expectedIntervals":result["summary"]["expectedIntervals"],"matchedIntervals":len(pairs),"missingIntervals":result["summary"]["expectedIntervals"]-len(pairs),"forecastIntervals":result["summary"]["forecastIntervals"],"exactForecastIntervals":result["summary"]["exactForecastIntervals"],"hourlyHeldIntervals":result["summary"]["hourlyHeldIntervals"],"publicationTimes":result["summary"]["publicationTimes"]})
    return {"start":s.isoformat(),"end":e.isoformat(),"cutoffTime":cutoff_time,"overall":calculate_metrics(all_pairs),"days":days,"series":series,"matchedIntervals":len(all_pairs),"evaluationMethod":"Latest WINDFOR publication at or before each delivery date's D-1 cutoff; exact hourly targets plus following half-hour held values are scored against FUELHH actuals.","dataQuality":q}

@app.get("/api/horizon-error")
def horizon_error(start:str,end:str):
    s,e=parse_date(start),parse_date(end); validate_range(s,e); a,f,q=load_snapshot(); amap={parse_utc(r["startTime"]).isoformat():r for r in a}; groups={k:[] for k in ["0–6 h","6–12 h","12–24 h","24–48 h","48+ h"]}
    for r in f:
        local=parse_utc(r["startTime"]).astimezone(LONDON).date()
        if not s<=local<=e: continue
        ar=amap.get(parse_utc(r["startTime"]).isoformat())
        if not ar or ar["generation"] is None or r["generation"] is None: continue
        h=horizon_hours(r["startTime"],r["publishTime"])
        if h>=0: groups[horizon_bucket(h)].append((r["generation"],ar["generation"]))
    return {"buckets":[{"bucket":k,"lowerInclusiveHours":lo,"upperExclusiveHours":hi,**calculate_metrics(v)} for k,lo,hi in [("0–6 h",0,6),("6–12 h",6,12),("12–24 h",12,24),("24–48 h",24,48),("48+ h",48,None)] for v in [groups[k]]],"dataQuality":q}

@app.get("/api/error-distribution")
def error_distribution(start:str,end:str,cutoff_time:str="09:00"):
    s,e=parse_date(start),parse_date(end); validate_range(s,e); c=parse_time(cutoff_time); a,f,q=load_snapshot(); pairs=[]
    for offset in range((e-s).days+1):
        x=selected_day(s+timedelta(days=offset),c,a,f,q,False)
        pairs += [(r["forecastMw"],r["actualMw"]) for r in x["intervals"] if r["forecastMw"] is not None and r["actualMw"] is not None]
    errors=[f-a for f,a in pairs]; step=max(100,round(max([abs(x) for x in errors],default=1000)/8/100)*100); bins=[]
    for left in range(-int(max([abs(x) for x in errors],default=step)//step+1)*step,int(max([abs(x) for x in errors],default=step)//step+1)*step+1,step):
        bins.append({"fromMw":left,"toMw":left+step,"count":sum(left<=x<left+step for x in errors)})
    return {"sampleCount":len(errors),"bins":bins,"signedErrorPercentilesMw":{"p10":percentile(errors,.10),"p50":percentile(errors,.50),"p90":percentile(errors,.90)},"absoluteErrorPercentilesMw":{"p90":percentile([abs(x) for x in errors],.90),"p95":percentile([abs(x) for x in errors],.95)},"dataQuality":q,"definition":"error = forecast - actual (MW); positive is overforecast."}

from fastapi.staticfiles import StaticFiles
WEB=ROOT/"frontend"/"dist"
if WEB.exists():
    app.mount("/",StaticFiles(directory=WEB,html=True),name="web")
