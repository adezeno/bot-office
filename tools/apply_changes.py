#!/usr/bin/env python3
"""Apply open GitHub issues labelled office-change to data.js (first-name copy).
Idempotent: issues stay open until Jarvis puts the change on the Tasks page and closes them.
Name lists never live in this public repo. Jarvis's sync sets GANA_PRIVATE to his private folder,
so the full filter (with names) cleans the text there. The GitHub Action has no names and masks
patterns only; the page already masks requests, and the next Jarvis sync re-cleans data.js."""
import json, re, subprocess, sys, datetime, os
if os.environ.get("GANA_PRIVATE"):
    sys.path.insert(0, os.environ["GANA_PRIVATE"])
    from sanitize import clean  # fails loudly if the private side is broken: nothing is half-cleaned
else:
    PAT = [
     (re.compile(r"\b([A-Z][a-z]+)\s+(?:Bin|Binti|bin|binti|Bt|A/L|A/P)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"), r"\1"),
     (re.compile(r"\b([A-Z][a-z]+)\s+(?:Chong|Lim|Tan|Wong|Lee|Ng|Hong|Kee|Soh|Chaw)\b"), r"\1"),
     (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email]"),
     (re.compile(r"\b\d{6}-?\d{2}-?\d{4}\b"), "[ID]"),
     (re.compile(r"(?<!\w)(?:\+?6?0)1\d[-\s]?\d{3,4}[-\s]?\d{4}\b"), "[phone]"),
     (re.compile(r"\b(?:MY|P|C-?|JE-?)?\d{8,}\b"), "[ID]"),
     (re.compile(r"\bMY\d{5,}\b"), "[ID]"),
     (re.compile(r"(?:RM|US\$|USD|\$)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|K|mil|million)\b)?"), "RM[amt]"),
     (re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?(?:k|K)\b"), "[amt]"),
     (re.compile(r"(?i)\b(smoker|non-smoker|arrears|diagnos\w*|medical history|illness)\b"), "[private]"),
     (re.compile(r"/(?:home|workspace|cursor)/\S+"), "[path]"),
     (re.compile(r"https?://cursor\.com/\S+"), "[private link]"),
     (re.compile(r"(?i)\b(gh[pousr]_\w{20,}|sk-[\w-]{16,}|xox[abp]-[\w-]+|AKIA\w{12,}|password\s*[:=]\s*\S+)"), "[secret]"),
    ]
    def clean(x):
        x = x.replace("Bot Office", "the Gana Teguh office")
        for p, r in PAT: x = p.sub(r, x)
        return x
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
    elif a == "next" and isinstance(v, str) and v.strip(): t["next"] = clean(v.strip()[:300])
    else: skipped.append((i["number"], "bad action")); continue
    t["pendingJarvis"] = i["number"]; t["pendingAction"] = a; applied.append(i["number"])
now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
data["officeChanges"] = {"applied": applied, "skipped": [n for n, _ in skipped], "at": now.strftime("%Y-%m-%d %H:%M (UTC+8)")}
open(path, "w").write("window.OFFICE_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n")
print(f"applied={applied} skipped={skipped}")
