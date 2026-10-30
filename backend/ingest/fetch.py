"""Fetch and validate the January 2026 Elexon snapshot.

Run from the repository root with: python -m backend.ingest.fetch
The streams are filtered in UTC publication time and settlement date. Pages do
not exist on these optimized stream endpoints; requests are intentionally split
into one-day chunks to bound payload size.
"""
from __future__ import annotations
import asyncio, csv, json, logging, os, time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import httpx
from backend.processing import parse_utc

BASE="https://data.elexon.co.uk/bmrs/api/v1"
ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/"data"
START=date(2026,1,1); END=date(2026,1,31)
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger(__name__)

async def get_rows(client:httpx.AsyncClient,path:str,params:dict)->list[dict]:
    for attempt in range(6):
        try:
            response=await client.get(f"{BASE}{path}",params=params)
            response.raise_for_status()
            payload=response.json()
            rows=payload.get("data",[]) if isinstance(payload,dict) else payload
            if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):
                raise ValueError(f"Unexpected schema from {path}")
            return rows
        except (httpx.HTTPError,ValueError) as exc:
            if attempt==5: raise RuntimeError(f"Failed request {path} {params}: {exc}") from exc
            delay=min(30,2**attempt)
            log.warning("Request retry %s after %ss: %s",path,delay,exc); await asyncio.sleep(delay)
    return []

async def fetch():
    limits=httpx.Limits(max_connections=4)
    async with httpx.AsyncClient(timeout=httpx.Timeout(90),limits=limits,follow_redirects=True) as client:
        actual=[]
        for day_offset in range((END-START).days+1):
            day=START+timedelta(days=day_offset)
            rows=await get_rows(client,"/datasets/FUELHH/stream",{"settlementDateFrom":day.isoformat(),"settlementDateTo":day.isoformat(),"fuelType":"WIND"})
            actual.extend(rows); log.info("FUELHH %s: %d rows",day,len(rows))
        forecasts=[]
        # Forecast horizons include publications before January. Fetch daily chunks,
        # then retain all rows targeting the requested delivery dates.
        pub=date(2025,12,1)
        last=date(2026,2,1)
        while pub<=last:
            lo=datetime.combine(pub,datetime.min.time(),timezone.utc)
            hi=lo+timedelta(days=1)
            rows=await get_rows(client,"/datasets/WINDFOR/stream",{"publishDateTimeFrom":lo.isoformat().replace("+00:00","Z"),"publishDateTimeTo":hi.isoformat().replace("+00:00","Z")})
            forecasts.extend(rows); log.info("WINDFOR publication day %s: %d rows",pub,len(rows))
            pub+=timedelta(days=1)
    return actual,forecasts

def normalize(rows:list[dict],kind:str)->tuple[list[dict],dict]:
    valid=[]; warnings=Counter(); seen={}
    for row in rows:
        start=parse_utc(row.get("startTime"))
        publish=parse_utc(row.get("publishTime"))
        if start is None or (kind=="forecast" and publish is None): warnings["null_or_bad_timestamp"]+=1; continue
        if kind=="actual" and row.get("fuelType")!="WIND": continue
        try: generation=float(row["generation"]) if row.get("generation") is not None else None
        except (TypeError,ValueError): generation=None; warnings["malformed_generation"]+=1
        if generation is None: warnings["null_generation"]+=1
        # Stable policy: duplicate source key resolves by lexicographically greatest
        # canonical source row; identical duplicates collapse to one.
        key=(start.isoformat(),publish.isoformat() if publish else "")
        item={"startTime":start.isoformat().replace("+00:00","Z"),"publishTime":publish.isoformat().replace("+00:00","Z") if publish else "", "generation":generation}
        if kind=="actual": item["fuelType"]="WIND"
        canonical=json.dumps(row,sort_keys=True,default=str)
        if key in seen:
            warnings["duplicate_source_key"]+=1
            if canonical<=seen[key][0]: continue
        seen[key]=(canonical,item)
    valid=[entry[1] for entry in seen.values()]
    return sorted(valid,key=lambda r:(r["startTime"],r["publishTime"])),dict(warnings)

def main():
    actual_raw,forecast_raw=asyncio.run(fetch())
    actual,warn_a=normalize(actual_raw,"actual"); forecasts,warn_f=normalize(forecast_raw,"forecast")
    # Keep forecast points whose target's UK-local calendar date is in January.
    from zoneinfo import ZoneInfo
    london=ZoneInfo("Europe/London")
    forecasts=[r for r in forecasts if START<=parse_utc(r["startTime"]).astimezone(london).date()<=END]
    expected=[]
    for d in range(31):
        day=START+timedelta(days=d)
        # Derive target intervals using UTC steps bounded by London-local midnight.
        local=datetime.combine(day,datetime.min.time(),london)
        cursor=local.astimezone(timezone.utc); stop=(local+timedelta(days=1)).astimezone(timezone.utc)
        while cursor<stop: expected.append(cursor.isoformat().replace("+00:00","Z")); cursor+=timedelta(minutes=30)
    actual_keys={r["startTime"] for r in actual}
    forecast_targets={r["startTime"] for r in forecasts}
    report={"source":"Elexon BMRS Insights API v1","retrievedAtUtc":datetime.now(timezone.utc).isoformat(),"requestedDeliveryRange":{"start":START.isoformat(),"end":END.isoformat()},"actual":{"records":len(actual),"coveredIntervals":len(actual_keys),"expectedIntervals":len(expected),"missingIntervals":[x for x in expected if x not in actual_keys],"warnings":warn_a,"unit":"MW; FUELHH half-hourly generation","targetResolutionMinutes":30},"forecast":{"records":len(forecasts),"coveredTargetIntervals":len(forecast_targets),"expectedActualIntervalCount":len(expected),"missingTargetIntervals":[x for x in expected if x not in forecast_targets],"warnings":warn_f,"unit":"MW; WINDFOR generation with publishTime preserved","targetResolutionMinutes":60,"resolutionEvidence":"Distinct WINDFOR target startTime values are hourly in the validated sample; Elexon describes WINDFOR forecast profiles as 49 points spanning 48 hours."},"pagination":"Stream endpoints returned a flat JSON array and expose no page token; one-day bounded date chunks used.","deduplication":"For duplicate (startTime,publishTime) source keys, collapse identical rows; on conflict retain lexicographically greatest canonical JSON source row. Conflicts are counted.","knownLimitations":["WINDFOR target points are hourly while FUELHH actuals are half-hourly. Exact startTime matching therefore leaves half of January actual intervals without a corresponding forecast; no interpolation is applied.","A 09:00 D-1 selection can have only limited eligible data for early delivery hours; those intervals remain missing when no eligible publication targets them."]}
    DATA.mkdir(exist_ok=True)
    for name,rows in [("actuals.csv",actual),("forecasts.csv",forecasts)]:
        with (DATA/name).open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ["startTime","publishTime","generation"]); writer.writeheader(); writer.writerows(rows)
    (DATA/"data-quality.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    log.info("Saved %d actuals, %d forecast records; %d actual gaps",len(actual),len(forecasts),len(report["actual"]["missingIntervals"]))

if __name__=="__main__": main()
