# Safe, merge-ONLY personnel cleanup for data/race_docs.json.
#
# This is the "Check 2" half of diag_personnel.py — handle-name de-duplication —
# with the dangerous "Check 1" (cross-series leak / roster-dropping) REMOVED and
# hard guardrails added so it can never delete a roster or a person.
#
#   python merge_personnel.py            # report only (dry run)
#   python merge_personnel.py --fix      # apply the merges
#
# What it does: a crew member whose first "name" is actually a system handle
# (e.g. "Tpatterson Patterson") indexes as a separate person from the real
# "Tyler Patterson". When a confident match exists (same last name, a shared
# team, AND a shared position, with exactly ONE candidate), the handle name is
# rewritten to the real full name everywhere it appears.
#
# What it will NEVER do: drop a roster, drop a race, add or remove any crew row.
# It only RENAMES strings. Before writing, it verifies the race count, roster
# count, and total crew-member count are all unchanged — if any differ, it
# aborts without writing. (Tip: commit first so `git checkout` can undo.)
import json, sys, os, re
from collections import defaultdict

path = "data/race_docs.json"
d = json.load(open(path, encoding="utf-8"))

# ---------------------------------------------------------------------------
# Detection (identical to diag_personnel.py Check 2)
# ---------------------------------------------------------------------------
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

merges = {}        # bad name -> good name
ambiguous = []     # bad names with 0 or >1 candidates (reported, not merged)
for name, ctx in contexts.items():
    first, last = split_name(name)
    if not last or not is_handle_first(first, last):
        continue
    cands = []
    for good in good_by_last.get(last.lower(), ()):
        gctx = contexts[good]
        if (ctx["teams"] & gctx["teams"]) and (ctx["positions"] & gctx["positions"]):
            cands.append(good)
    if len(cands) == 1:
        merges[name] = cands[0]
    else:
        ambiguous.append((name, cands))

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
print("=== Handle-name duplicates (merge-only) ===")
if not merges and not ambiguous:
    print("  none")
else:
    for bad, good in sorted(merges.items()):
        print(f"  MERGE  \"{bad}\"  ->  \"{good}\"   "
              f"(teams={sorted(contexts[bad]['teams'])}, pos={sorted(contexts[bad]['positions'])})")
    for bad, cands in ambiguous:
        why = "no confident match" if not cands else f"ambiguous: {cands}"
        print(f"  SKIP   \"{bad}\"   ({why})")

# ---------------------------------------------------------------------------
# Helpers for the guardrails: count rosters + crew members
# ---------------------------------------------------------------------------
def tallies(data):
    races = rosters = members = 0
    for _yr, bys in data.items():
        for _series, rcs in bys.items():
            for _rid, rec in rcs.items():
                races += 1
                roster = (rec.get("docs", {}).get("roster") or {}).get("rows")
                if roster is not None:
                    rosters += 1
                    for car in roster:
                        if car.get("crew_chief"):
                            members += 1
                        members += len(car.get("crew") or [])
    return races, rosters, members

# ---------------------------------------------------------------------------
# Apply (rename only) + verify nothing was added or removed
# ---------------------------------------------------------------------------
if "--fix" in sys.argv:
    if not merges:
        print("\nNothing to merge.")
        sys.exit(0)

    before = tallies(d)
    cells = 0
    for yr, bys in d.items():
        for series, races in bys.items():
            for rid, rec in races.items():
                roster = (rec.get("docs", {}).get("roster") or {}).get("rows") or []
                for car in roster:
                    if car.get("crew_chief") in merges:
                        car["crew_chief"] = merges[car["crew_chief"]]; cells += 1
                    for c in (car.get("crew") or []):
                        if c.get("name") in merges:
                            c["name"] = merges[c["name"]]; cells += 1
    after = tallies(d)

    # GUARDRAIL: a rename must not change any structural count. If it did,
    # something is wrong — refuse to write and leave the file untouched.
    if before != after:
        print("\nABORTED — structural counts changed, refusing to write.")
        print(f"  before (races, rosters, members) = {before}")
        print(f"  after  (races, rosters, members) = {after}")
        sys.exit(1)

    tmp = path + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    print(f"\nApplied: merged {len(merges)} handle name(s) across {cells} roster cell(s).")
    print(f"Verified unchanged: {before[0]} races, {before[1]} rosters, {before[2]} crew members.")
else:
    if merges:
        print("\nRe-run with  --fix  to apply (rename-only; commit first so it's easy to undo).")
