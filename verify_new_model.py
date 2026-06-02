"""
verify_new_model.py — replicate the new pace-dominant predictDriverForRace
against the real pace + points data, so we can eyeball the predicted order for
a track BEFORE trusting the live site.

Mirrors app.js exactly:
  pace blend = 0.5*fast20_delta + 0.5*median_delta  (lower = faster)
  pace -> expected finish pos:  1 + 6.0 * delta
  signals (weights):
    40% pace last-3 at this track   (fallback: type -> recent)
    18% pace recent track type
    12% all-time finish at this track
    10% qual at track type (true qual_pos)
    10% qual at this track  (true qual_pos)
    10% recent form (last 8 finishes)
  missing signals redistribute proportionally.

Usage:
  python verify_new_model.py --track Nashville          # uses NCS
  python verify_new_model.py --track Michigan --series NCS
"""

import argparse, json, statistics

PACE_DELTA_TO_POS = 6.0
STOP = {"international","speedway","motor","raceway","superspeedway","the","of","at","park","circuit"}

def toks(n):
    return {w for w in ''.join(c if c.isalnum() else ' ' for c in str(n).lower()).split() if w and w not in STOP}
def tmatch(a,b):
    A,B=toks(a),toks(b)
    return bool(A and B and (A & B))

def load_pace(years):
    out={}
    for y in years:
        try: out[y]=json.load(open(f"data/pace_{y}.json"))
        except FileNotFoundError: pass
    return out

def pace_blend(rec):
    f=rec.get("fast20_avg_delta_pct"); m=rec.get("green_median_delta_pct")
    if f is None and m is None: return None
    if f is None: return m
    if m is None: return f
    return 0.5*f+0.5*m

def _clean_pace_name(raw):
    s=str(raw or "").strip()
    import re as _re
    s=_re.sub(r"^\*\s*","",s); s=_re.sub(r"\s*\([^)]*\)","",s)
    s=_re.sub(r"\s*#\s*$","",s); return _re.sub(r"\s+"," ",s).strip()

def _norm_pace(n):
    import unicodedata
    s=unicodedata.normalize("NFD",_clean_pace_name(n).lower())
    s="".join(c for c in s if not unicodedata.combining(c))
    for ch in ".,'’": s=s.replace(ch,"")
    for suf in (" jr"," sr"," ii"," iii"," iv"):
        if s.endswith(suf): s=s[:-len(suf)]
    return " ".join(s.split())

def pace_records(pace, series, driver, track_name=None):
    want=_norm_pace(driver)
    recs=[]
    for y in sorted(pace, reverse=True):
        sb=pace[y].get("series",{}).get(series)
        if not sb: continue
        for r in sb["races"]:
            if track_name and not tmatch(r["track"], track_name): continue
            if "_byNorm" not in r:
                m={}
                for k,rec in r["drivers"].items():
                    nk=_norm_pace(k)
                    if nk not in m or rec.get("green_laps",0)>m[nk].get("green_laps",0): m[nk]=rec
                r["_byNorm"]=m
            rec=r["_byNorm"].get(want)
            if not rec: continue
            b=pace_blend(rec)
            if b is None: continue
            recs.append((y, r.get("round",0), b, rec.get("green_laps",0), rec.get("race_ref_green",0)))
    recs.sort(key=lambda x:(-x[0],-x[1]))
    return [(b,g,rg) for _,_,b,g,rg in recs]

def avg(xs,n):
    s=[b for b,_,_ in xs[:n]]
    return sum(s)/len(s) if s else None

def greenratio(xs,n):
    # ratio of the best clean run in the window to that race's field-max
    best=None
    for b,g,rg in xs[:n]:
        if best is None or g>best[0]: best=(g,rg)
    if not best or best[1]<=0: return None
    return best[0]/best[1]

# We don't have the app's TRACK_NAMES/TRACK_TYPES here, so approximate track
# type from the points data isn't needed — for verification we focus on the
# track-specific pace (primary signal) which is what dominates. Type/qual
# signals are loaded from points if present.

# Drafting / pack tracks where pace is NOT predictive — mirrors the live
# model's isDraftingTrack(). Daytona, Talladega, Atlanta (post-2022 repave).
def is_drafting_track(track_name):
    t = (track_name or "").lower()
    return ("daytona" in t and "road" not in t) or "talladega" in t or "atlanta" in t

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--track", required=True)
    ap.add_argument("--series", default="NCS")
    ap.add_argument("--years", default="2024,2025,2026")
    ap.add_argument("--fulltime", action="store_true", help="full-timers only (like the live board)")
    args=ap.parse_args()
    years=[int(y) for y in args.years.split(",")]
    pace=load_pace(years)
    if not pace:
        raise SystemExit("no pace files found")

    # points (current year) for finish/qual/form
    pts=json.load(open(f"data/points_{max(years)}.json"))["series"][args.series]

    # collect every driver who has pace data this season
    cur=pace[max(years)]["series"][args.series]["races"]
    drivers=set()
    for r in cur: drivers.update(r["drivers"].keys())

    def finish_history(driver):
        rows=[]
        for race in pts["races"]:
            for d in race.get("results",[]):
                if d.get("driver")==driver and d.get("finish_pos") is not None:
                    rows.append((race.get("round",0), d))
        rows.sort(key=lambda x:-x[0])
        return [d for _,d in rows]

    out=[]
    for drv in drivers:
        # primary pace: last 3 at this track (fallback recent)
        here=pace_records(pace,args.series,drv,track_name=args.track)
        if here: tp=avg(here,3); src="track"
        else:
            recent=pace_records(pace,args.series,drv)
            tp=avg(recent,5); src="recent" if recent else "none"
        # recent pace (proxy for type, since we lack type map here)
        recent=pace_records(pace,args.series,drv)
        typep=avg(recent,5)
        hist=finish_history(drv)
        # all-time-at-track finish, trimmed of super-low (bad) outliers (IQR fence)
        track_fin=[d["finish_pos"] for race in pts["races"] if tmatch(race.get("track",""),args.track)
                   for d in race.get("results",[]) if d.get("driver")==drv and d.get("finish_pos")]
        def _trim_bad(vals):
            if len(vals)>=4:
                s=sorted(vals)
                def q(p): return s[min(len(s)-1,int(p*(len(s)-1)))]
                q1,q3=q(.25),q(.75); fence=q3+1.5*(q3-q1)
                t=[v for v in vals if v<=fence]
                if t: return t
            return vals
        alltime=statistics.mean(_trim_bad(track_fin)) if track_fin else None
        # qual at track (true qual_pos)
        tq=[d.get("qual_pos") for race in pts["races"] if tmatch(race.get("track",""),args.track)
            for d in race.get("results",[]) if d.get("driver")==drv and d.get("qual_pos")]
        track_qual=statistics.mean(tq) if tq else None
        # form last 8, trimmed of best + worst
        last8=[d["finish_pos"] for d in hist[:8] if d.get("finish_pos")]
        def _trim_hl(vals):
            return sorted(vals)[1:-1] if len(vals)>=4 else vals
        form=statistics.mean(_trim_hl(last8)) if last8 else None

        p2p=lambda d:None if d is None else 1+PACE_DELTA_TO_POS*d
        # primary pace w/ clean-run-RELATIVE shrinkage (mirror app.js)
        MIDPACK, SOFT = 20, 22
        if here:
            tp_pos=p2p(tp); src_used="track"
            ratio=greenratio(here,3)
            shr=min(0.5,(0.65-ratio)/0.65*0.6) if (ratio is not None and ratio<0.65) else 0
            anch=MIDPACK
        else:
            rec=pace_records(pace,args.series,drv)  # harness: recent stands in for type+recent
            if rec:
                tp_pos=p2p(avg(rec,5)); src_used="recent"; shr=0.40; anch=SOFT
            else:
                tp_pos=None; src_used="none"; shr=0; anch=MIDPACK
        typep=avg(pace_records(pace,args.series,drv),5)
        starts=len([1 for race in pts["races"] for d in race.get("results",[])
                    if d.get("driver")==drv and d.get("finish_pos") is not None])
        if tp_pos is not None:
            if shr>0 and src_used!="track":
                relief=max(0,min(1,(20-tp_pos)/15))
                shr*=(1-0.85*relief)
            if 0<starts<12 and shr<1:
                shr=min(0.80, shr+(12-starts)/12*0.25)
            if shr>0: tp_pos=(1-shr)*tp_pos+shr*anch
        # weights: pace 50/10, all-time 15, qual-track 10, form 15
        sig=[(.50,tp_pos),(.10,p2p(typep)),(.15,alltime),(.10,track_qual),(.15,form)]
        av=[(w,v) for w,v in sig if v is not None]
        if not av: continue
        ws=sum(w for w,_ in av)
        pred=sum((w/ws)*v for w,v in av)
        # DRAFTING-TRACK override (mirror live model): drop pace, predict from
        # finish history — all-time-here 65% + qual 15% + finish-form 20%.
        if is_drafting_track(args.track):
            dsig=[(.65,alltime),(.15,track_qual),(.20,form)]
            dav=[(w,v) for w,v in dsig if v is not None]
            if dav:
                dws=sum(w for w,_ in dav)
                pred=max(1.0,sum((w/dws)*v for w,v in dav))
                src_used="draft"
            # else: no finish history at the draft track — leave pace-based pred
        out.append((max(1.0,pred), drv, src_used, tp, starts))

    out.sort()
    fulltimers=[r for r in out if r[4]>=6]
    print(f"{args.series} · {args.track} · predicted order (new pace model)")
    print(f"{'(* = part-timer, <6 starts)' if not args.fulltime else '(full-timers only)'}")
    print(f"  [{len(out)} drivers with pace data; {len(fulltimers)} have >=6 starts]\n")
    print(f"{'#':>2} {'driver':24}{'pred':>6}{'pace src':>10}{'trkPace%':>9}{'starts':>7}")
    print("-"*62)
    shown=0
    for pred,drv,src,tp,starts in out:
        part = starts < 6
        if args.fulltime and part: continue
        shown+=1
        tps=f"{tp:.2f}" if tp is not None else "-"
        flag="* " if part else "  "
        print(f"{shown:>2} {flag+drv:24}{pred:>6.1f}{src:>10}{tps:>9}{starts:>7}")

if __name__=="__main__":
    main()
