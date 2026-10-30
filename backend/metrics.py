"""Accuracy metrics for matched forecast/actual observations."""
from __future__ import annotations
import math
from typing import Iterable

def percentile(values: list[float], q: float) -> float | None:
    if not values: return None
    xs = sorted(values); pos = (len(xs)-1)*q; lo = math.floor(pos); hi = math.ceil(pos)
    return xs[lo] + (xs[hi]-xs[lo])*(pos-lo)

def calculate_metrics(pairs: Iterable[tuple[float, float]], near_zero_mw: float = 1.0) -> dict:
    """Pairs are (forecast MW, actual MW); signed error is forecast minus actual."""
    clean = [(float(f),float(a)) for f,a in pairs if f is not None and a is not None and math.isfinite(float(f)) and math.isfinite(float(a))]
    errors = [f-a for f,a in clean]; absolute = [abs(e) for e in errors]
    mape_pairs = [(e,a) for e,(_,a) in zip(errors,clean) if abs(a) > near_zero_mw]
    denom = sum(abs(a) for _,a in clean)
    return {"matchedCount":len(clean),"maeMw":sum(absolute)/len(clean) if clean else None,
      "rmseMw":math.sqrt(sum(e*e for e in errors)/len(errors)) if clean else None,
      "biasMw":sum(errors)/len(errors) if clean else None,
      "mapePct":sum(abs(e/a)*100 for e,a in mape_pairs)/len(mape_pairs) if mape_pairs else None,
      "mapeCount":len(mape_pairs),"mapeExcludedNearZero":len(clean)-len(mape_pairs),
      "wapePct":sum(absolute)/denom*100 if denom else None,
      "p90AbsoluteErrorMw":percentile(absolute,.90),"p95AbsoluteErrorMw":percentile(absolute,.95)}
