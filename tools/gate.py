#!/usr/bin/env python3
"""Request gate for the office's automation. Public and name-free: the GitHub Action, Jarvis's hourly sync and his
list of waiting requests all go through it.
- Owner only: a request counts when GitHub says the owner opened it (user.login adezeno, author_association OWNER).
  Look-alike issues from anyone else are never applied.
- Pause switch: a PAUSE file (at the repo root, or in Jarvis's folder; any case, any extension) or an open issue
  labelled pause-bots stops every round and workflow before it does anything; they report "paused: true". A lookup
  that fails stops them too.
- Masks: mask() is the page's publicSafe() run again on this side, since a request typed or edited on GitHub never
  went through the page. problems() is the name-free half of the private hook's check, with the same patterns, so
  whatever the hook passes passes here. It names kinds only: matched text never reaches a log.
Command line (Jarvis's sync.sh and pending_changes.sh):
  gate.py paused OWNER/REPO [ROOT...]    prints "paused: false" (exit 0) or "paused: true (why)" (exit 3)
  gate.py requests OWNER/REPO [ROOT...]  prints the owner's open office-change requests as JSON (number, title, body,
                                         createdAt), with "paused: ..." and "ignored #N" on stderr; [] and exit 3 when
                                         paused. Exit 1 when GitHub can't be asked: nothing may run unchecked."""
import json, os, re, subprocess, sys

OWNER = "adezeno"
REQUEST_LABEL, PAUSE_LABEL, PAUSE_FILE = "office-change", "pause-bots", "PAUSE"


def owner_request(issue):
    """True only when GitHub reports the owner as the author (a REST issue: user.login and author_association)."""
    return (issue.get("user") or {}).get("login") == OWNER and issue.get("author_association") == "OWNER"


# ---------- masks: the page's publicSafe(), with JavaScript's regex meaning ----------
# JavaScript's \w, \d and \b are ASCII-only (re.ASCII); its \s is this set, wider than Python's ASCII \s
_SP = "\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_SP_CHARS = "\t\n\v\f\r \u00a0\u1680\u2028\u2029\u202f\u205f\u3000\ufeff" + "".join(map(chr, range(0x2000, 0x200b)))
S, NS = "[%s]" % _SP, "[^%s]" % _SP
_A = re.ASCII
_MASKS = [(re.compile(p, f), r) for p, f, r in (
    (r"[\w.+-]+@[\w-]+\.[\w.]+", _A, "[email]"),
    (r"\b\d{6}-?\d{2}-?\d{4}\b", _A, "[ID]"),
    (r"(^|[^\w])(?:\+?6?0)1\d[-%s]?\d{3,4}[-%s]?\d{4}\b" % (_SP, _SP), _A, r"\1[phone]"),
    (r"\b(?:MY|P|C-?)?\d{8,}\b", _A, "[ID]"),
    (r"\bMY\d{5,}\b", _A, "[ID]"),
    (r"(?:RM|US\$|USD|\$)%s?\d[\d,]*(?:\.\d+)?(?:%s?(?:k|K|mil|million)\b)?" % (S, S), _A, "RM[amt]"),
    (r"\b(gh[pousr]_\w{20,}|sk-[\w-]{16,}|xox[abp]-[\w-]+|AKIA\w{12,})", _A, "[secret]"),
    (r"(password|passcode|pin|otp)%s*[:=]?%s*%s+" % (S, S, NS), _A | re.I, r"\1 [secret]"),
    (r"\b([A-Z][a-z]+)%s+(?:Bin|Binti|bin|binti|Bt|A/L|A/P)%s+[A-Z][a-z]+(?:%s+[A-Z][a-z]+)?" % (S, S, S), _A, r"\1"),
    (r"\b([A-Z][a-z]+)%s+(?:Chong|Lim|Tan|Wong|Lee|Ng|Hong|Kee|Soh|Chaw)\b" % S, _A, r"\1"),
    (r"https?://cursor\.com/%s+" % NS, _A, "[private link]"),
)]


def full_names(data):
    """The page's FULL_RE names: each multi-word name in data.js's clientNames and deal clients, trimmed, once,
    longest first (index.html, "client names")."""
    seen = {}
    deals = [d.get("client") for d in data.get("deals") or [] if isinstance(d, dict)]
    for n in list(data.get("clientNames") or []) + deals:
        n = str(n).strip(_SP_CHARS) if n else ""
        if n and re.search(S, n):
            seen.setdefault(n)
    return sorted(seen, key=len, reverse=True)


def mask(text, names=()):
    """The page's publicSafe(): the given full names cut to their first word (firstNames), then emails, IC numbers,
    phones, IDs, amounts, secrets, Malay full names, common surnames and private links, in the page's order."""
    s = "" if text is None else str(text)
    names = sorted(names, key=len, reverse=True)
    if names:
        full = re.compile(r"\b(?:%s)\b" % "|".join(map(re.escape, names)), _A)
        s = full.sub(lambda m: re.split(S + "+", m.group(0))[0], s)
    for p, r in _MASKS:
        s = p.sub(r, s)
    return s


# ---------- checks: the name-free half of the private hook's check(), same patterns and flags ----------
_CHECKS = [(re.compile(p), kind) for p, kind in (
    (r"[\w.+-]+@[\w-]+\.[\w.]+", "email"),
    (r"\b\d{6}-?\d{2}-?\d{4}\b", "IC number"),
    (r"(?<!\w)(?:\+?6?0)1\d[-\s]?\d{3,4}[-\s]?\d{4}\b", "phone"),
    (r"\b(?:MY|P|C-?|JE-?)?\d{8,}\b", "ID or account number"),
    (r"\bMY\d{5,}\b", "ID or account number"),
    (r"\b[A-Z][a-z]+\s+(?:Bin|Binti)\s+[A-Z][a-z]+", "full name"),
    (r"cursor\.com/canvas|arenaDraft|arenaReadme|/home/bo[x]", "private link or path"),  # [x]: no self-match in the hook's scan
)]


def problems(text):
    """What the hook's name-free checks find in text, as kinds ("phone", "email"...), never the matched text."""
    return sorted({kind for p, kind in _CHECKS if p.search(text)})


# ---------- GitHub: the pause switch and the requests ----------
def gh_list(path):
    """Every item of a GitHub REST list, through gh (GH_TOKEN in the Action, gh's login on Jarvis's machine)."""
    r = subprocess.run(["gh", "api", "--paginate", path, "--jq", ".[]"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("gh api %s failed: %s" % (path.split("?")[0], (r.stderr or "").strip()[:200]))
    return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]


_PAUSE_NAME = re.compile(r"pause(?:\.\w+)?", re.I)   # PAUSE, pause, Pause.txt, PAUSE.md


def paused(repo, roots=(".",)):
    """Why the bots are paused, or None: a PAUSE file in one of roots (the repo checkout, Jarvis's folder) or at the
    repo root on GitHub, or an open issue or pull request labelled pause-bots. A failed lookup raises."""
    for root in roots:
        if root and os.path.isdir(root):
            hit = sorted(n for n in os.listdir(root) if _PAUSE_NAME.fullmatch(n))
            if hit:
                return "a %s file in %s" % (hit[0], root)
    if any(_PAUSE_NAME.fullmatch(x.get("name") or "") for x in gh_list("repos/%s/contents/" % repo)):
        return "a %s file at the root of %s" % (PAUSE_FILE, repo)
    for i in gh_list("repos/%s/issues?state=open&labels=%s&per_page=100" % (repo, PAUSE_LABEL)):
        return "the %s label on #%s" % (PAUSE_LABEL, i.get("number"))
    return None


def requests(repo):
    """The owner's open office-change requests, oldest first, and the numbers of the open ones that are ignored:
    look-alikes from any other account, and pull requests."""
    mine, ignored = [], []
    for i in gh_list("repos/%s/issues?state=open&labels=%s&per_page=100" % (repo, REQUEST_LABEL)):
        (mine if owner_request(i) and not i.get("pull_request") else ignored).append(i)
    return sorted(mine, key=lambda i: i.get("number") or 0), sorted(i.get("number") or 0 for i in ignored)


def report(line):
    """A status line for the log, and for the run's summary page when this runs in GitHub Actions."""
    print(line, flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(line + "\n\n")


def main(argv):
    if len(argv) < 3 or argv[1] not in ("paused", "requests"):
        sys.stderr.write("usage: gate.py paused|requests OWNER/REPO [ROOT...]\n")
        return 2
    cmd, repo, roots = argv[1], argv[2], argv[3:] or ["."]
    try:
        why = paused(repo, roots)
        if cmd == "paused":
            print("paused: true (%s)" % why if why else "paused: false")
            return 3 if why else 0
        if why:
            sys.stderr.write("paused: true (%s). Apply nothing this round.\n" % why)
            print("[]")
            return 3
        mine, ignored = requests(repo)
    except (RuntimeError, OSError, ValueError) as e:
        sys.stderr.write("The request gate couldn't check GitHub, so nothing may run: %s\n" % e)
        return 1
    sys.stderr.write("paused: false\n" + "".join("ignored #%s: not the owner's request\n" % n for n in ignored))
    print(json.dumps([{"number": i.get("number"), "title": i.get("title"), "body": i.get("body"),
                       "createdAt": i.get("created_at")} for i in mine], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
