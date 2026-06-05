# Diagnostic + targeted cleanup for the personnel data in data/race_docs.json.
#
# Two independent checks (run from the repo root):
#   python diag_personnel.py            # report only
#   python diag_personnel.py --fix      # apply fixes
#
# Check 1 — CROSS-SERIES LEAK: a roster filed under a series whose Jayski URL
#           section doesn't match (e.g. a Cup roster stored under NTS). Fix:
#           drop that roster so the sweep can refetch it correctly.
#
# Check 2 — HANDLE-NAME DUPLICATE: a crew member whose first "name" is actually
#           a system handle (e.g. "Tpatterson Patterson"), which indexes as a
#           separate person from the real "Tyler Patterson". Fix: rewrite the
#           handle name to the real full name when a confident match exists on
#           the SAME team + SAME position + same last name elsewhere in the data.
import json, sys, os, re
from collections import defaultdict

path = "data/race_docs.json"
d = json.load(open(path, encoding="utf-8"))
SECT = {"NCS": "nascar-cup-series", "NOS": "oreilly-auto-parts-series", "NTS": "truck-series"}

# ---------------------------------------------------------------------------
# Check 1: cross-series leaks (URL section vs filed series)
# ---------------------------------------------------------------------------
leaks = []
for yr, bys in d.items():
    for series, races in bys.items():
        for rid, rec in races.items():
            url = (rec.get("docs", {}).get("roster") or {}).get("url", "")
            want = SECT.get(series, "")
            if url and want and want not in url.lower():
                leaks.append((yr, series, rid, rec.get("track", ""), url))

# ---------------------------------------------------------------------------
# Check 2: handle-name duplicates
# ---------------------------------------------------------------------------
# A "handle" first name is one where, lowercased, it contains the last name as
# a substring (e.g. "tpatterson" contains "patterson"), or it's a single token
# that's clearly not a given name (mixed-case run with the surname embedded).
def is_handle_first(first, last):
    f, l = first.lower().strip(), last.lower().strip()
    if not f or not l or len(l) < 4:
        return False
    # the giveaway: the surname is embedded in the "first name" token
    return l in f and f != l

def split_name(name):
    parts = re.sub(r"\s+", " ", (name or "").strip()).split(" ")
    if len(parts) < 2:
        return None, None
    return parts[0], parts[-1]

# Catalog every (name) -> set of (team, position, cars) contexts it appears in.
# Also collect, per last name, the set of "good" full names (non-handle first).
contexts = defaultdict(lambda: {"teams": set(), "positions": set(), "cars": set(), "count": 0})
good_by_last = defaultdict(set)     # lastname(lower) -> {good full names}

def each_member(rec):
    roster = (rec.get("docs", {}).get("roster") or {}).get("rows") or []
    for car in roster:
        team = (car.get("team") or "").strip()
        cnum = str(car.get("car") or "")
        if car.get("crew_chief"):
            yield car["crew_chief"], team, "Crew Chief", cnum
        for c in (car.get("crew") or []):
            if c.get("name"):
                yield c["name"], team, (c.get("position") or ""), cnum

for yr, bys in d.items():
    for series, races in bys.items():
        for rid, rec in races.items():
            for name, team, pos, cnum in each_member(rec):
                first, last = split_name(name)
                if not last:
                    continue
                ctx = contexts[name]
                ctx["teams"].add(team); ctx["positions"].add(pos)
                ctx["cars"].add(cnum); ctx["count"] += 1
                if first and not is_handle_first(first, last):
                    good_by_last[last.lower()].add(name)

# For each handle-name, find a confident real-name match: same last name, a
# shared team, and a shared position. If exactly one such good name exists,
# that's our merge target.
merges = {}        # bad name -> good name
ambiguous = []     # bad names with 0 or >1 candidates (reported, not merged)
for name, ctx in contexts.items():
    first, last = split_name(name)
    if not last or not is_handle_first(first, last):
        continue
    cands = []
    for good in good_by_last.get(last.lower(), ()):
        gctx = contexts[good]
        shares_team = bool(ctx["teams"] & gctx["teams"])
        shares_pos = bool(ctx["positions"] & gctx["positions"])
        if shares_team and shares_pos:
            cands.append(good)
    if len(cands) == 1:
        merges[name] = cands[0]
    else:
        ambiguous.append((name, cands))

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
print("=== Check 1: cross-series roster leaks ===")
if not leaks:
    print("  none\n")
else:
    for yr, series, rid, track, url in leaks:
        print(f"  {yr} {series} race {rid}  {track}\n      {url}")
    print()

print("=== Check 2: handle-name duplicates ===")
if not merges and not ambiguous:
    print("  none")
else:
    for bad, good in sorted(merges.items()):
        print(f"  MERGE  \"{bad}\"  ->  \"{good}\"   (teams={sorted(contexts[bad]['teams'])}, pos={sorted(contexts[bad]['positions'])})")
    for bad, cands in ambiguous:
        why = "no confident match" if not cands else f"ambiguous: {cands}"
        print(f"  SKIP   \"{bad}\"   ({why})")

# ---------------------------------------------------------------------------
# Fix
# ---------------------------------------------------------------------------
if "--fix" in sys.argv:
    changed = False
    # Check 1: drop mis-filed rosters
    for yr, series, rid, *_ in leaks:
        docs = d[yr][series][rid].get("docs", {})
        docs.pop("roster", None)
        if not docs:
            d[yr][series].pop(rid, None)
        changed = True
    # Check 2: rewrite handle names to their real full name in every roster row
    if merges:
        for yr, bys in d.items():
            for series, races in bys.items():
                for rid, rec in races.items():
                    roster = (rec.get("docs", {}).get("roster") or {}).get("rows") or []
                    for car in roster:
                        if car.get("crew_chief") in merges:
                            car["crew_chief"] = merges[car["crew_chief"]]; changed = True
                        for c in (car.get("crew") or []):
                            if c.get("name") in merges:
                                c["name"] = merges[c["name"]]; changed = True
    if changed:
        tmp = path + ".tmp"
        json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
        print(f"\nApplied: dropped {len(leaks)} leaked roster(s), merged {len(merges)} handle name(s).")
        if leaks:
            print("Re-run the roster sweep to refetch the dropped races correctly.")
    else:
        print("\nNothing to change.")
else:
    if leaks or merges:
        print("\nRe-run with  --fix  to apply.")
