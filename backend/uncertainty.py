"""Empirical signed-error uncertainty ranges with explicit sample requirements."""
from __future__ import annotations
from backend.metrics import percentile
from backend.processing import horizon_bucket

def uncertainty_band(forecast_mw: float, hours: float, reference: list[dict], delivery_date: str, minimum: int = 30) -> dict:
    bucket = horizon_bucket(hours)
    # A decision on delivery_date can only use errors from earlier delivery days.
    errors = [float(r["errorMw"]) for r in reference if r.get("errorMw") is not None and r.get("deliveryDate", "") < delivery_date and r.get("horizonBucket") == bucket]
    if len(errors) < minimum: return {"lowerMw":None,"upperMw":None,"sampleCount":len(errors),"bucket":bucket,"reason":f"Need {minimum} comparable historical errors; found {len(errors)}."}
    p10,p90=percentile(errors,.10),percentile(errors,.90)
    return {"lowerMw":forecast_mw-p90,"upperMw":forecast_mw-p10,"sampleCount":len(errors),"bucket":bucket,"reason":None}
