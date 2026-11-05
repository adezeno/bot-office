#!/usr/bin/env python3
"""My Pages on the public office: the names go on the site, the links only to Zeno's own devices. Public and
name-free: Jarvis's hourly sync runs it with his private Pages list, which never leaves his side.
- pages.json gets each Page's id (p01, p02, ... in list order), icon, name and group. Never a link.
- owner.lock.json gets the links, sealed with the owner password from the GT_OWNER_PASSWORD environment variable:
  PBKDF2-SHA256 (600,000 rounds) makes the key, AES-GCM-256 seals {"v": 1, "pages": {id: {name, url}}}. The Desk PC
  opens it once per device and keeps the key there, so Pages open on Zeno's unlocked devices only.
- No password (unset, empty, or shorter than 16 characters, since the sealed file stays public for good): the file is
  {"v": 1, "set": false} and the office runs in visitor mode, with the tiles locked and no Unlock form.
- The salt stays while the password does, so unlocked devices stay unlocked. The file is rewritten only when the
  links or the password change; a new password locks every device until it is unlocked again.
Command line (Jarvis's sync.sh):
  owner_key.py build PRIVATE_LIST SITE_DIR   writes SITE_DIR/pages.json and SITE_DIR/owner.lock.json and prints one
                                             line, never the password or a link. Exit 1, writing nothing, when the
                                             list can't be used or the links can't be sealed."""
import base64, hashlib, json, os, sys, tempfile

PASSWORD_ENV, MIN_PASSWORD = "GT_OWNER_PASSWORD", 16
KDF, ROUNDS = "PBKDF2-SHA256", 600000
PLACEHOLDER = {"v": 1, "set": False}


class Problem(Exception):
    pass


def entries(path):
    """the private list as [{id, icon, name, group, url}]: url None when the Page has no link yet"""
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
        if url in (None, ""):
            url = None
        elif not (isinstance(url, str) and url.startswith("https://") and len(url) > 8 and not any(c.isspace() for c in url)):
            raise Problem("%s: its link isn't a plain https:// link, so nothing was written" % name)
        out.append({"id": "p%02d" % i, "icon": str(p.get("icon") or ""), "name": name, "group": str(p.get("group") or ""),
                    "url": url})
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


def _write(path, text):
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
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
    return True


def build(private_list, site, password):
    """write pages.json and owner.lock.json under site; returns the line to print"""
    es = entries(private_list)
    lock_path = os.path.join(site, "owner.lock.json")
    n, linked = len(es), sum(1 for e in es if e["url"])
    if not password or len(password) < MIN_PASSWORD:
        lock = json.dumps(PLACEHOLDER, indent=1)
        why = ("%s isn't set" % PASSWORD_ENV) if not password else (
            "%s is shorter than %d characters, so it wasn't used (the sealed file stays public for good, and a short "
            "password can be guessed offline)" % (PASSWORD_ENV, MIN_PASSWORD))
        line = "owner key: %s. The office stays in visitor mode: tiles locked, no Unlock form (%d Pages)." % (why, n)
    else:
        try:
            import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
        except ImportError:
            raise Problem("the Python package cryptography isn't installed here, so the links can't be sealed")
        plain = bundle(es)
        try:
            with open(lock_path, encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError):
            old = None
        was = open_lock(old, password) if isinstance(old, dict) else None
        if was == plain:
            lock, how = None, "unchanged"
        else:
            salt = base64.b64decode(old["salt"]) if was is not None else None
            lock = json.dumps(seal(plain, password, salt), indent=1)
            how = "links changed" if was is not None else "new password or first seal: devices unlock again"
        line = "owner key: %d Pages, %d links sealed in owner.lock.json (%s)." % (n, linked, how)
    _write(os.path.join(site, "pages.json"), pages_json(es))
    if lock is not None:
        _write(lock_path, lock)
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
