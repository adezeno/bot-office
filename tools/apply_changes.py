#!/usr/bin/env python3
"""Apply open GitHub issues labelled office-change to data.js (first-name copy).
Idempotent: issues stay open until Jarvis puts the change on the Tasks page and closes them.
The request gate (tools/gate.py) comes first: nothing runs while the bots are paused, and only requests the owner
opened apply. Look-alikes from any other account are reported by number and ignored.
Name lists never live in this public repo. Jarvis's sync sets GANA_PRIVATE to his private folder, so typed text
("next" requests) goes through his full filter, then the page's masks again, then the check his publish step runs
(the hook's); text that still fails is skipped, never written. The GitHub Action has no names, so it applies only "done" and stage moves and leaves
typed text for Jarvis's next sync. Before anything is written, the whole file gets the name-free checks: if one
fails, nothing is written, so the Action commits nothing. A run that would change only the time leaves the file alone."""
import json, re, sys, datetime, os
import gate  # tools/gate.py, next to this file; imported before the private folder joins the path
clean = file_problems = None
if os.environ.get("GANA_PRIVATE"):
    sys.path.insert(0, os.environ["GANA_PRIVATE"])
    from sanitize import clean, file_problems  # fails loudly if the private side is broken: nothing is half-cleaned
repo = sys.argv[1] if len(sys.argv) > 1 else "adezeno/bot-office"
path = sys.argv[2] if len(sys.argv) > 2 else "data.js"
why = gate.paused(repo, [".", os.environ.get("GANA_PRIVATE")])
if why:
    gate.report("paused: true (%s). No request was applied." % why)
    sys.exit(0)
gate.report("paused: false")
src = open(path).read()
m = re.match(r"\s*window\.OFFICE_DATA\s*=\s*(.*?);?\s*$", src, re.S)
data = json.loads(m.group(1))
issues, ignored = gate.requests(repo)
for n in ignored:
    gate.report("ignored #%s: not the owner's request" % n)


def unstamped(d):
    """the board without the time of a run (and an empty record counts as none), to tell a change from a re-run"""
    d = json.loads(json.dumps(d)); oc = d.pop("officeChanges", None)
    if isinstance(oc, dict) and (oc.get("applied") or oc.get("skipped")):
        d["officeChanges"] = {k: v for k, v in oc.items() if k != "at"}
    return d


was = unstamped(data)
tasks = {t.get("id"): t for t in data.get("tasks", [])}
names = gate.full_names(data)  # the page's first-name cut, for the masks
STAGES = {"Inbox","Next","Doing","Waiting On","Needs Zeno","Done"}
applied, skipped = [], []
for i in issues:
    mm = re.search(r"```json\s*(\{.*?\})\s*```", i.get("body") or "", re.S)
    try: r = json.loads(mm.group(1))
    except Exception: skipped.append((i["number"], "no request JSON")); continue
    k = r.get("taskId"); t = tasks.get(k) if isinstance(k, str) else None; a = r.get("action"); v = r.get("value")
    if not t: skipped.append((i["number"], "task not on board")); continue
    if a == "done": t["stage"] = "Done"
    elif a == "stage" and isinstance(v, str) and v in STAGES: t["stage"] = v
    elif a == "next" and isinstance(v, str) and v.strip():
        if not clean: skipped.append((i["number"], "typed text waits for Jarvis's sync")); continue
        # his filter first (it knows the real names and keeps the given name), then the page's masks, then the cut
        text = gate.mask(clean(v.strip()), names).strip()[:300].strip()
        if not text or gate.problems(text) or file_problems("data.js", text.encode("utf-8")):
            skipped.append((i["number"], "fails the privacy check")); continue  # never written, never logged
        t["next"] = text
    else: skipped.append((i["number"], "bad action")); continue
    t["pendingJarvis"] = i["number"]; t["pendingAction"] = a; applied.append(i["number"])
now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
data["officeChanges"] = {"applied": applied, "skipped": [n for n, _ in skipped], "at": now.strftime("%Y-%m-%d %H:%M (UTC+8)")}
gate.report("applied=%s skipped=%s" % (applied, ", ".join("#%s (%s)" % s for s in skipped) or "[]"))
if unstamped(data) == was:
    print("no change: data.js left alone"); sys.exit(0)
out = "window.OFFICE_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n"
bad = gate.problems(out)
if bad:  # kinds only: what matched never goes into a log
    gate.report("BLOCKED: data.js would carry %s. Nothing was written." % ", ".join(bad)); sys.exit(1)
open(path, "w").write(out)
