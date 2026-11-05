#!/usr/bin/env python3
"""My Pages on the public office: the names go on the site, the links only to Zeno's own devices. Public and
name-free: Jarvis's hourly sync runs it with his private Pages list, which never leaves his side.
- pages.json gets each Page's id (p01, p02, ... in list order), icon, name and group. Never a link.
- owner.lock.json gets the links, sealed with the owner password from the GT_OWNER_PASSWORD environment variable:
  PBKDF2-SHA256 (600,000 rounds) makes the key, AES-GCM-256 seals {"v": 1, "pages": {id: {name, url}}}. The Desk PC
  opens it once per device and keeps the key there, so Pages open on Zeno's unlocked devices only.
- No password (unset, empty, or shorter than 16 characters, since the sealed file stays public for good): the file is
  {"v": 1, "set": false} and the office runs in visitor mode, with the tiles locked and no Unlock form.
- The salt stays while the password does, so unlocked devices stay unlocked, even after rounds run without the
  password: the last seal is also kept next to the private list (owner.lock.last.json). The file is rewritten only
  when the links or the password change; a new password locks every device until it is unlocked again.
- A Page whose link isn't a plain https:// link (an app link, say) keeps a locked tile, and the line names it.
Command line (Jarvis's sync.sh):
  owner_key.py build PRIVATE_LIST SITE_DIR   writes SITE_DIR/pages.json and SITE_DIR/owner.lock.json and prints one
                                             line, never the password or a link. Exit 1, writing nothing, when the
                                             list can't be read or the links can't be sealed."""
import base64, hashlib, json, os, sys, tempfile

PASSWORD_ENV, MIN_PASSWORD = "GT_OWNER_PASSWORD", 16
KDF, ROUNDS = "PBKDF2-SHA256", 600000
PLACEHOLDER = {"v": 1, "set": False}
KEPT = "owner.lock.last.json"   # the last seal, next to the private list: never published


class Problem(Exception):
    pass


def https(url):
    return isinstance(url, str) and url.startswith("https://") and len(url) > 8 and not any(c.isspace() for c in url)


def entries(path):
    """the private list as [{id, icon, name, group, url, odd}]: url None when the Page has no link the Desk PC can
    open (odd: it has one, but not a plain https:// link)"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise Problem("can't read the private Pages list (%s)" % type(e).__name__)
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list):
        raise Problem('the private Pages list has no "pages" list')
    out = []
    for i, p in enumerate(pages, 1):
        name = p.get("name") if isinstance(p, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise Problem("Page %d in the private list has no name" % i)
        url = p.get("url")
        odd = url not in (None, "") and not https(url)
        out.append({"id": "p%02d" % i, "icon": str(p.get("icon") or ""), "name": name, "group": str(p.get("group") or ""),
                    "url": url if https(url) else None, "odd": odd})
    return out


def pages_json(es):
    return json.dumps({"pages": [{k: e[k] for k in ("id", "icon", "name", "group")} for e in es]}, ensure_ascii=False, indent=1)


def bundle(es):
    return json.dumps({"v": 1, "pages": {e["id"]: {"name": e["name"], "url": e["url"]} for e in es if e["url"]}},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _key(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ROUNDS, 32)


def seal(plain, password, salt=None):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, iv = salt or os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(password, salt)).encrypt(iv, plain, None)   # the tag rides at the end, as WebCrypto expects
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return {"v": 1, "kdf": KDF, "iter": ROUNDS, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def open_lock(lock, password):
    """what a sealed lock holds, or None when this password doesn't open it or it isn't one"""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        if lock.get("v") != 1 or lock.get("kdf") != KDF or lock.get("iter") != ROUNDS:
            return None
        salt, iv, ct = (base64.b64decode(lock[k], validate=True) for k in ("salt", "iv", "ct"))
        return AESGCM(_key(password, salt)).decrypt(iv, ct, None)
    except (AttributeError, KeyError, TypeError, ValueError, InvalidTag):
        return None


def _read_lock(path):
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
        return j if isinstance(j, dict) else None
    except (OSError, ValueError):
        return None


def _write(path, text, mode=0o644):
    """write only when the bytes change, through a temporary file, so a reader never sees half a file"""
    data = text.encode("utf-8")
    try:
        with open(path, "rb") as f:
            if f.read() == data:
                return False
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=".owner-key-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
    return True


def build(private_list, site, password):
    """write pages.json and owner.lock.json under site; returns the line to print"""
    es = entries(private_list)
    lock_path = os.path.join(site, "owner.lock.json")
    kept_path = os.path.join(os.path.dirname(os.path.abspath(private_list)), KEPT)
    n, linked = len(es), sum(1 for e in es if e["url"])
    odd = [e["name"] for e in es if e["odd"]]
    left = " Left locked (no plain https:// link): %s." % ", ".join(odd) if odd else ""
    if not password or len(password) < MIN_PASSWORD:
        lock = json.dumps(PLACEHOLDER, indent=1)
        why = ("%s isn't set" % PASSWORD_ENV) if not password else (
            "%s is shorter than %d characters, so it wasn't used (the sealed file stays public for good, and a short "
            "password can be guessed offline)" % (PASSWORD_ENV, MIN_PASSWORD))
        line = "owner key: %s. The office stays in visitor mode: tiles locked, no Unlock form (%d Pages).%s" % (why, n, left)
    else:
        try:
            import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
        except ImportError:
            raise Problem("the Python package cryptography isn't installed here, so the links can't be sealed")
        plain = bundle(es)
        old, kept = _read_lock(lock_path), _read_lock(kept_path)
        was = open_lock(old, password) if old else None
        if was is None and kept and open_lock(kept, password) is not None:
            old, how = kept, "sealed again with the kept salt: unlocked devices stay unlocked"   # after visitor rounds
        elif was is not None:
            how = "links changed"
        else:
            old, how = None, "new password or first seal: devices unlock again"
        if was == plain:
            lock, how = None, "unchanged"
        else:
            lock = json.dumps(seal(plain, password, base64.b64decode(old["salt"]) if old else None), indent=1)
        line = "owner key: %d Pages, %d links sealed in owner.lock.json (%s).%s" % (n, linked, how, left)
    _write(os.path.join(site, "pages.json"), pages_json(es))
    if lock is not None:
        _write(lock_path, lock)
    if password and len(password) >= MIN_PASSWORD:
        try:
            with open(lock_path, encoding="utf-8") as f:
                _write(kept_path, f.read(), 0o600)
        except OSError as e:
            line += " (No private copy of the seal was kept: %s.)" % type(e).__name__
    return line


def main(argv):
    if len(argv) != 4 or argv[1] != "build":
        sys.stderr.write("usage: owner_key.py build PRIVATE_LIST SITE_DIR\n")
        return 2
    try:
        print(build(argv[2], argv[3], os.environ.get(PASSWORD_ENV) or ""))
    except Problem as e:
        print("owner key: BLOCKED: %s." % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
