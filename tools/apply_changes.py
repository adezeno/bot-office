#!/usr/bin/env python3
"""Apply open GitHub issues labelled office-change to data.js (first-name copy).
Idempotent: issues stay open until Jarvis puts the change on the Tasks page and closes them.
Name lists never live in this public repo. Jarvis's sync sets GANA_PRIVATE to his private folder,
so typed text ("next" requests) is cleaned there with the full filter. The GitHub Action has no
names, so it applies only "done" and stage moves and leaves typed text for Jarvis's next sync."""
import json, re, subprocess, sys, datetime, os
clean = None
if os.environ.get("GANA_PRIVATE"):
    sys.path.insert(0, os.environ["GANA_PRIVATE"])
    from sanitize import clean  # fails loudly if the private side is broken: nothing is half-cleaned
repo = sys.argv[1] if len(sys.argv) > 1 else "adezeno/bot-office"
path = sys.argv[2] if len(sys.argv) > 2 else "data.js"
src = open(path).read()
m = re.match(r"\s*window\.OFFICE_DATA\s*=\s*(.*?);?\s*$", src, re.S)
data = json.loads(m.group(1))
issues = json.loads(subprocess.check_output(["gh", "issue", "list", "-R", repo, "-l", "office-change", "-s", "open",
                                             "--json", "number,title,body", "-L", "100"]))
tasks = {t.get("id"): t for t in data.get("tasks", [])}
STAGES = {"Inbox","Next","Doing","Waiting On","Needs Zeno","Done"}
applied, skipped = [], []
for i in sorted(issues, key=lambda x: x["number"]):
    mm = re.search(r"```json\s*(\{.*?\})\s*```", i.get("body") or "", re.S)
    try: r = json.loads(mm.group(1))
    except Exception: skipped.append((i["number"], "no request JSON")); continue
    t = tasks.get(r.get("taskId")); a = r.get("action"); v = r.get("value")
    if not t: skipped.append((i["number"], "task not on board")); continue
    if a == "done": t["stage"] = "Done"
    elif a == "stage" and v in STAGES: t["stage"] = v
    elif a == "next" and isinstance(v, str) and v.strip():
        if not clean: skipped.append((i["number"], "typed text waits for Jarvis's sync")); continue
        t["next"] = clean(v.strip()[:300])
    else: skipped.append((i["number"], "bad action")); continue
    t["pendingJarvis"] = i["number"]; t["pendingAction"] = a; applied.append(i["number"])
now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
data["officeChanges"] = {"applied": applied, "skipped": [n for n, _ in skipped], "at": now.strftime("%Y-%m-%d %H:%M (UTC+8)")}
open(path, "w").write("window.OFFICE_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n")
print(f"applied={applied} skipped={skipped}")
