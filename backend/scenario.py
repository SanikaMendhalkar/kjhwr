"""Client demand and wind scenario calculations on matched half-hour intervals."""
from __future__ import annotations
from typing import Iterable


def calculate_balance(intervals: Iterable[dict], wind_share_pct: float | None = None) -> dict:
    """Estimate a utility's proportional allocation of national wind by interval.

    Pass a percentage for the explicit fixed-share scenario. Otherwise each row
    must contain positive nationalDemandMw and share is client demand / national
    demand. Missing values are kept unavailable rather than imputed.
    """
    if wind_share_pct is not None and not 0 <= wind_share_pct <= 100:
        raise ValueError("Assumed client share must be between 0 and 100%.")
    rows = []
    for item in intervals:
        demand = item.get("demandMw")
        forecast = item.get("forecastMw")
        national_demand = item.get("nationalDemandMw")
        if national_demand is not None and national_demand <= 0:
            raise ValueError("National demand must be greater than zero MW.")
        share = wind_share_pct / 100 if wind_share_pct is not None else (
            demand / national_demand if demand is not None and national_demand is not None else None
        )
        if share is not None and share > 1:
            raise ValueError("Client demand share cannot exceed 100%; check the interval units and national-demand reference.")
        valid = demand is not None and forecast is not None and share is not None
        wind = forecast * share if valid else None
        contribution = min(demand, wind) if valid else None
        signed = demand - wind if valid else None
        residual = max(0, signed) if valid else None
        surplus = max(0, -signed) if valid else None
        low = high = None
        if valid and item.get("lowerMw") is not None and item.get("upperMw") is not None:
            wind_low = max(0, item["lowerMw"] * share)
            wind_high = max(0, item["upperMw"] * share)
            low = max(0, demand - wind_high)
            high = max(0, demand - wind_low)
        rows.append({**item, "clientSharePct": round(share * 100, 4) if share is not None else None,
                     "allocatedWindMw": wind, "estimatedAllocatedWindMw": wind,
                     "potentialContributionMw": contribution,
                     "signedDemandMinusWindMw": signed, "residualMw": residual,
                     "windSurplusMw": surplus, "residualLowerMw": low,
                     "residualUpperMw": high, "balanceValid": valid})
    valid = [r for r in rows if r["balanceValid"]]
    uncertainty_samples = [int(r.get("uncertaintySampleCount") or 0) for r in valid if r["residualLowerMw"] is not None]
    provided_demand_mwh = sum(r["demandMw"] for r in rows if r.get("demandMw") is not None) * .5
    demand_mwh = sum(r["demandMw"] for r in valid) * .5
    forecast_mwh = sum(r["allocatedWindMw"] for r in valid) * .5
    contribution_mwh = sum(r["potentialContributionMw"] for r in valid) * .5
    residual_mwh = sum(r["residualMw"] for r in valid) * .5
    surplus_mwh = sum(r["windSurplusMw"] for r in valid) * .5
    national_demand_mwh = sum(r.get("nationalDemandMw") or 0 for r in valid) * .5
    client_share_pct = (wind_share_pct if wind_share_pct is not None else
                        round(demand_mwh / national_demand_mwh * 100, 4) if national_demand_mwh else None)
    return {"intervals": rows, "summary": {
        "inputIntervals": len(rows), "matchedIntervals": len(valid),
        "expectedIntervals": 48, "demandMWh": round(demand_mwh, 2),
        "providedDemandMWh": round(provided_demand_mwh, 2),
        "nationalDemandMWh": round(national_demand_mwh, 2) if national_demand_mwh else None,
        "clientSharePct": client_share_pct,
        "forecastWindMWh": round(forecast_mwh, 2),
        "estimatedAllocatedWindMWh": round(forecast_mwh, 2),
        "potentialContributionMWh": round(contribution_mwh, 2),
        "residualMWh": round(residual_mwh, 2), "windSurplusMWh": round(surplus_mwh, 2),
        "potentialWindCoveragePct": round(contribution_mwh / demand_mwh * 100, 2) if demand_mwh else None,
        "coverageComplete": len(valid) == 48,
        "uncertaintyIntervals": sum(r["residualLowerMw"] is not None for r in valid),
        "uncertaintySampleCountMin": min(uncertainty_samples) if uncertainty_samples else None,
        "uncertaintySampleCountMax": max(uncertainty_samples) if uncertainty_samples else None,
        "residualLowerMWh": round(sum(r["residualLowerMw"] for r in valid if r["residualLowerMw"] is not None) * .5, 2) if valid and all(r["residualLowerMw"] is not None for r in valid) else None,
        "residualUpperMWh": round(sum(r["residualUpperMw"] for r in valid if r["residualUpperMw"] is not None) * .5, 2) if valid and all(r["residualUpperMw"] is not None for r in valid) else None,
    }}
