"""
fallback_options.py — show how 3 fallback treatments rank full-timers for a
track, so we can pick how to handle drivers with no history AT that track.

Tiers tried for the primary pace signal:
  A) track  : last 3 races at THIS track
  B) type   : recent pace at this TRACK TYPE (intermediates, short, etc.)
  C) recent : recent overall pace (any track) — last resort

Three options compared (all share: track-pace primary when available):
  OPT1  shrink-recent : if we fall to 'recent', pull it toward mid-pack (P20)
  OPT2  type-first    : fall to TYPE pace before 'recent'; 'recent' only if no
                        type history either
  OPT3  both          : type-first, AND shrink whatever 'recent' remains

Uses real TRACK_TYPES/TRACK_NAMES from _track_maps.json.
Full-timers only (>=6 starts), like the live board.

Usage: python fallback_options.py --track Michigan
"""
import argparse, json, statistics

PACE_DELTA_TO_POS=6.0; NEUTRAL=20
STOP={"international","speedway","motor","raceway","superspeedway","the","of","at","park","circuit"}
def toks(n): return {w for w in ''.join(c if c.isalnum() else ' ' for c in str(n).lower()).split() if w and w not in STOP}
def tmatch(a,b):
    A,B=toks(a),toks(b); return bool(A and B and (A&B))

maps=json.load(open("_track_maps.json"))
TT=maps["TRACK_TYPES"]; TN=maps["TRACK_NAMES"]
def type_of_name(name):
    for code,nm in TN.items():
        if tmatch(nm,name):
            t=TT.get(code)
            if t: return t
    return None

def load_pace(years):
    out={}
    for y in years:
        try: out[y]=json.load(open(f"data/pace_{y}.json"))
        except FileNotFoundError: pass
    return out
def blend(rec):
    f=rec.get("fast20_avg_delta_pct"); m=rec.get("green_median_delta_pct")
    if f is None and m is None: return None
    if f is None: return m
    if m is None: return f
    return 0.5*f+0.5*m
def recs(pace,series,drv,track=None,ttype=None):
    r=[]
    for y in sorted(pace,reverse=True):
        sb=pace[y].get("series",{}).get(series)
        if not sb: continue
        for race in sb["races"]:
            if track and not tmatch(race["track"],track): continue
            if ttype and type_of_name(race["track"])!=ttype: continue
            rec=race["drivers"].get(drv)
            if not rec: continue
            b=blend(rec)
            if b is None: continue
            r.append((y,race.get("round",0),b))
    r.sort(key=lambda x:(-x[0],-x[1]))
    return [b for _,_,b in r]
def avg(xs,n): s=xs[:n]; return sum(s)/len(s) if s else None
def p2p(d): return None if d is None else 1+PACE_DELTA_TO_POS*d

def primary(pace,series,drv,track,ttype,mode):
    here=recs(pace,series,drv,track=track)
    if here:
        v=avg(here,3); n=min(len(here),3)
        if n<3: v=p2p(v); v=(n/3)*v+(1-n/3)*NEUTRAL; return v,"track",n
        return p2p(v),"track",n
    # no track history -> branch by mode
    typ=recs(pace,series,drv,ttype=ttype)
    rec=recs(pace,series,drv)
    if mode in ("type","both"):
        if typ: 
            v=avg(typ,5); n=min(len(typ),5)
            vp=p2p(v)
            if n<3: vp=(n/3)*vp+(1-n/3)*NEUTRAL
            return vp,"type",n
        if rec:
            vp=p2p(avg(rec,5)); 
            if mode=="both": vp=0.5*vp+0.5*NEUTRAL  # shrink last-resort recent
            return vp,"recent",min(len(rec),5)
        return None,"none",0
    else:  # shrink-recent: type not preferred, recent gets shrunk
        if rec:
            vp=p2p(avg(rec,5)); vp=0.5*vp+0.5*NEUTRAL
            return vp,"recent",min(len(rec),5)
        if typ:
            return p2p(avg(typ,5)),"type",min(len(typ),5)
        return None,"none",0

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--track",required=True)
    ap.add_argument("--series",default="NCS"); ap.add_argument("--years",default="2024,2025,2026")
    a=ap.parse_args(); years=[int(y) for y in a.years.split(",")]
    pace=load_pace(years); pts=json.load(open(f"data/points_{max(years)}.json"))["series"][a.series]
    ttype=type_of_name(a.track)
    cur=pace[max(years)]["series"][a.series]["races"]
    drivers=set()
    for r in cur: drivers.update(r["drivers"].keys())
    def starts(drv): return len([1 for race in pts["races"] for d in race.get("results",[]) if d.get("driver")==drv and d.get("finish_pos") is not None])
    def form(drv):
        hist=[]
        for race in pts["races"]:
            for d in race.get("results",[]):
                if d.get("driver")==drv and d.get("finish_pos") is not None: hist.append((race.get("round",0),d["finish_pos"]))
        hist.sort(key=lambda x:-x[0]); f=[p for _,p in hist[:8]]
        return statistics.mean(f) if f else None

    print(f"{a.series} · {a.track} (type={ttype}) · full-timers · three fallback options\n")
    rows={}
    detail={}  # mode -> {driver: (rank, pred, src)}
    for mode,key in (("shrink","OPT1 shrink-recent"),("type","OPT2 type-first"),("both","OPT3 both")):
        res=[]
        for drv in drivers:
            if starts(drv)<6: continue
            pv,src,n=primary(pace,a.series,drv,a.track,ttype,mode)
            fm=form(drv)
            sig=[(.40,pv),(.30,fm)]  # simplified: pace + form (others ~constant across options)
            av=[(w,v) for w,v in sig if v is not None]
            if not av: continue
            ws=sum(w for w,_ in av); pred=max(1.0,sum((w/ws)*v for w,v in av))
            res.append((pred,drv,src))
        res.sort(); rows[key]=res
        detail[key]={d:(i+1,p,s) for i,(p,d,s) in enumerate(res)}

    # Which drivers are on a fallback tier (no real track history) under ANY option?
    affected=set()
    for key,d in detail.items():
        for drv,(rank,pred,src) in d.items():
            if src!="track": affected.add(drv)

    print("FULL-TIMERS WITH NO MICHIGAN HISTORY (where options differ):")
    print(f"  {'driver':22}{'OPT1 shrink':>16}{'OPT2 type':>16}{'OPT3 both':>16}")
    print("  "+"-"*68)
    for drv in sorted(affected, key=lambda d: detail['OPT2 type-first'].get(d,(99,))[0]):
        cells=""
        for key in ("OPT1 shrink-recent","OPT2 type-first","OPT3 both"):
            r,p,s=detail[key].get(drv,(None,None,None))
            cells+=f"{f'#{r} ({p:.1f}){s[0]}':>16}" if r else f"{'-':>16}"
        print(f"  {drv:22}{cells}")
    print("\n  (rank, predicted finish, fallback tier: t=type r=recent)\n")

    # full top 25 of the chosen-gut option (type-first) for context
    print("OPT2 type-first — full top 25:")
    for i,(p,d,s) in enumerate(rows['OPT2 type-first'][:25],1):
        tag=f" ·{s[0]}" if s!="track" else ""
        print(f"  {i:>2} {d:22}{p:>6.1f}{tag}")

if __name__=="__main__": main()
