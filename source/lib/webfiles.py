"""webfiles - the file browser of the httpd web panel (/files).

The whole filesystem, from /: open folders, download or view files,
upload, make folders, rename, delete. Behind the same password as
the panel. Loaded only when a /files page is asked for.

    GET  /files?p=/dir          folder listing
    GET  /get?p=/file[&v=1]     download (v=1: show as text)
    POST /up?d=/dir&n=name      upload - the request body is the file
    POST /mkdir?p=/dir/new      new folder
    POST /ren?p=/old&n=newname  rename (same folder)
    POST /del?p=/path           delete a file or an empty folder

Uploads go to name.tmp and are renamed when complete, so a broken
upload never replaces a file with half of it. The browser sends the
file as the raw request body (a few lines of JavaScript), so nothing
has to parse multipart forms on the Pico. Upload size is limited only
by free flash; speed is roughly 50-150 KB/s over WiFi.

Full access means full: deleting /lib, /bin, boot.py or main.py from
here breaks A-NIX like it would from the shell (the page asks before
deleting).
"""

import os

_CHUNK = 1024
pins_link = True        # False when the panel has no pins (WEB_PINS=none)


def unquote(text):
    """%XX and + from a URL query value."""
    text = text.replace("+", " ")
    if "%" not in text:
        return text
    out = bytearray()
    i = 0
    raw = text.encode()
    while i < len(raw):
        c = raw[i]
        if c == 37 and i + 2 < len(raw):
            try:
                out.append(int(raw[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out.append(c)
        i += 1
    return out.decode("utf-8", "replace")


def quote(text):
    """Text -> safe in a URL query value."""
    out = []
    for b in text.encode():
        ch = chr(b)
        if b < 128 and (ch.isalpha() or ch.isdigit() or ch in "/-_.~"):
            out.append(ch)
        else:
            out.append("%%%02X" % b)
    return "".join(out)


def esc(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def norm(path):
    """Absolute, without . / .. / double slashes."""
    parts = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    return "/" + "/".join(parts)


def _join(folder, name):
    return norm(folder.rstrip("/") + "/" + name)


def _stat(path):
    try:
        return os.stat(path)
    except OSError:
        return None


def _is_dir(st):
    return st is not None and bool(st[0] & 0x4000)


def _send_all(cl, data):
    while data:
        n = cl.write(data)
        data = data[n or 0:]


def _reply(cl, status, ctype, body, extra=""):
    if isinstance(body, str):
        body = body.encode()
    _send_all(cl, ("HTTP/1.0 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n%s"
                   "Connection: close\r\n\r\n" % (status, ctype, len(body), extra)).encode())
    _send_all(cl, body)


def _text(cl, status, msg):
    _reply(cl, status, "text/plain; charset=utf-8", msg + "\n")


def _size(n):
    if n < 1024:
        return "%d B" % n
    if n < 1048576:
        return "%.1f KB" % (n / 1024)
    return "%.1f MB" % (n / 1048576)


_SCRIPT = """<script>
function D(x){return decodeURIComponent(x)}
function go(m,u,ask){if(ask&&!confirm(ask))return;
fetch(u,{method:m}).then(r=>r.text().then(t=>{if(!r.ok)alert(t);location.reload()}))}
function del(p,n){go('POST','/del?p='+p,'Delete '+D(n)+' ?')}
function ren(p,n){n=D(n);var v=prompt('New name for '+n,n);if(v&&v!=n)go('POST','/ren?p='+p+'&n='+encodeURIComponent(v))}
function mk(d){d=D(d);var v=prompt('New folder name');if(v)go('POST','/mkdir?p='+encodeURIComponent(d.replace(/\\/$/,'')+'/'+v))}
function up(d){d=D(d);var fs=document.getElementById('f').files,i=0,s=document.getElementById('s');
function next(){if(i>=fs.length){location.reload();return}var f=fs[i++];s.textContent='uploading '+f.name+' ('+i+'/'+fs.length+')...';
fetch('/up?d='+encodeURIComponent(d)+'&n='+encodeURIComponent(f.name),{method:'POST',body:f})
.then(r=>r.text().then(t=>{if(!r.ok){alert(t);location.reload()}else next()}))}next()}
</script>"""

_STYLE = ("<style>body{font-family:sans-serif;margin:1em}td{padding:3px 10px}"
          "tr:nth-child(even){background:#eee}a{text-decoration:none}"
          "button{margin:1px}</style>")


def _entries(path):
    """(name, is_dir, size) of a folder, folders first, by name. Uses
    os.ilistdir where it exists (no extra stat per file)."""
    out = []
    try:
        it = os.ilistdir(path)
        for e in it:
            name = e[0]
            is_dir = e[1] == 0x4000
            size = e[3] if len(e) > 3 and not is_dir else 0
            if size < 0 or (not is_dir and len(e) <= 3):
                st = _stat(_join(path, name))
                size = st[6] if st else 0
            out.append((not is_dir, name, size))
    except AttributeError:
        for name in os.listdir(path):
            st = _stat(_join(path, name))
            if st is not None:
                out.append((not _is_dir(st), name, 0 if _is_dir(st) else st[6]))
    out.sort()
    return out


def _listing(cl, path):
    """Sent piece by piece (no Content-Length - HTTP/1.0, the connection
    closing ends it), so even a big folder needs little RAM."""
    try:
        entries = _entries(path)
    except OSError as e:
        _text(cl, "404 Not Found", "can't open %s: %s" % (path, e))
        return
    try:
        st = os.statvfs(path)
        free = "%s free of %s" % (_size(st[0] * st[3]), _size(st[0] * st[2]))
    except OSError:
        free = ""
    crumbs = '<a href="/files?p=/">/</a>'
    acc = ""
    for part in [p for p in path.split("/") if p]:
        acc += "/" + part
        crumbs += ' <a href="/files?p=%s">%s</a> /' % (quote(acc), esc(part))
    q = quote(path)                     # only URL-safe characters: safe in JS too
    _send_all(cl, ("HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                   "Connection: close\r\n\r\n"
                   "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                   "<meta name='viewport' content='width=device-width'>"
                   "<title>A-NIX files %s</title>%s</head><body>%s<h2>%s</h2><p>"
                   "<input type='file' id='f' multiple> <button onclick=\"up('%s')\">upload here</button> "
                   "<button onclick=\"mk('%s')\">new folder</button> <span id='s'></span></p><table>\n"
                   % (esc(path), _STYLE,
                      "<p><a href='/'>&larr; pins</a></p>" if pins_link else "",
                      crumbs, q, q)).encode())
    if path != "/":
        _send_all(cl, ('<tr><td><a href="/files?p=%s">..</a></td><td></td><td></td></tr>\n'
                       % quote(norm(path + "/.."))).encode())
    ndirs = nfiles = 0
    for is_file, name, size in entries:
        full = quote(_join(path, name))
        qn = quote(name)
        if is_file:
            nfiles += 1
            row = ('<tr><td><a href="/get?p=%s">%s</a></td><td align="right">%s</td><td>'
                   '<a href="/get?p=%s&v=1"><button>view</button></a>'
                   % (full, esc(name), _size(size), full))
        else:
            ndirs += 1
            row = ('<tr><td>&#128193; <a href="/files?p=%s">%s/</a></td><td></td><td>'
                   % (full, esc(name)))
        row += ('<button onclick="ren(\'%s\',\'%s\')">rename</button>'
                '<button onclick="del(\'%s\',\'%s\')">delete</button></td></tr>\n'
                % (full, qn, full, qn))
        _send_all(cl, row.encode())
    _send_all(cl, ("</table><p>%d folder(s), %d file(s) - %s</p>%s</body></html>"
                   % (ndirs, nfiles, free, _SCRIPT)).encode())


def _download(cl, path, view):
    st = _stat(path)
    if st is None or _is_dir(st):
        _text(cl, "404 Not Found", "no such file: %s" % path)
        return
    name = path.rsplit("/", 1)[-1]
    if view:
        head = "Content-Type: text/plain; charset=utf-8\r\n"
    else:
        head = ("Content-Type: application/octet-stream\r\n"
                "Content-Disposition: attachment; filename=\"%s\"\r\n"
                % name.replace('"', "_").replace("\r", "_").replace("\n", "_"))
    _send_all(cl, ("HTTP/1.0 200 OK\r\n%sContent-Length: %d\r\nConnection: close\r\n\r\n"
                   % (head, st[6])).encode())
    buf = bytearray(_CHUNK)
    with open(path, "rb") as f:
        while True:
            n = f.readinto(buf)
            if not n:
                break
            _send_all(cl, memoryview(buf)[:n])


def _content_length(headers):
    for line in headers.split("\r\n")[1:]:
        if line.lower().startswith("content-length:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def _upload(cl, headers, rest, folder, name):
    if not name or "/" in name or name in (".", ".."):
        _text(cl, "400 Bad Request", "bad file name")
        return
    if not _is_dir(_stat(folder)):
        _text(cl, "404 Not Found", "no such folder: %s" % folder)
        return
    total = _content_length(headers)
    if total is None or total < 0:
        _text(cl, "411 Length Required", "upload needs a Content-Length")
        return
    try:
        st = os.statvfs(folder)
        if total > st[0] * st[3] - 8192:
            _text(cl, "507 Insufficient Storage", "not enough free flash for %s" % _size(total))
            return
    except OSError:
        pass
    path = _join(folder, name)
    tmp = path + ".tmp"
    got = 0
    try:
        with open(tmp, "wb") as out:
            if rest:
                rest = rest[:total]         # never more than Content-Length
                out.write(rest)
                got = len(rest)
            buf = bytearray(_CHUNK)
            while got < total:
                n = cl.readinto(buf, min(_CHUNK, total - got))
                if not n:
                    break
                out.write(memoryview(buf)[:n])
                got += n
        if got < total:
            raise OSError("connection lost after %d of %d bytes" % (got, total))
        try:
            os.rename(tmp, path)
        except OSError:
            os.remove(path)
            os.rename(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _text(cl, "500 Internal Server Error", "upload failed: %s" % e)
        return
    _text(cl, "200 OK", "stored %s (%d bytes)" % (path, got))


def handle(cl, route, params, headers, rest):
    """Answers one file-browser request. Returns False if the route
    isn't one of ours."""
    method = headers.split(" ", 1)[0].upper()
    p = norm(unquote(params.get("p", "/")))
    if route == "/files":
        _listing(cl, p)
    elif route == "/get":
        _download(cl, p, params.get("v") == "1")
    elif method != "POST" and route in ("/up", "/mkdir", "/ren", "/del"):
        _text(cl, "405 Method Not Allowed", "use the buttons on the page")
    elif route == "/up":
        _upload(cl, headers, rest, norm(unquote(params.get("d", "/"))),
                unquote(params.get("n", "")))
    elif route == "/mkdir":
        try:
            os.mkdir(p)
            _text(cl, "200 OK", "created %s" % p)
        except OSError as e:
            _text(cl, "500 Internal Server Error", "could not create %s: %s" % (p, e))
    elif route == "/ren":
        new = unquote(params.get("n", ""))
        if not new or "/" in new or p == "/":
            _text(cl, "400 Bad Request", "bad name")
            return True
        dst = _join(p.rsplit("/", 1)[0] or "/", new)
        if _stat(dst) is not None:
            _text(cl, "409 Conflict", "%s already exists" % dst)
            return True
        try:
            os.rename(p, dst)
            _text(cl, "200 OK", "renamed to %s" % dst)
        except OSError as e:
            _text(cl, "500 Internal Server Error", "could not rename: %s" % e)
    elif route == "/del":
        st = _stat(p)
        if p == "/" or st is None:
            _text(cl, "400 Bad Request", "nothing to delete")
            return True
        try:
            if _is_dir(st):
                os.rmdir(p)
            else:
                os.remove(p)
            _text(cl, "200 OK", "deleted %s" % p)
        except OSError as e:
            _text(cl, "500 Internal Server Error",
                  "could not delete %s: %s%s" % (p, e, " (folder not empty?)" if _is_dir(st) else ""))
    else:
        return False
    return True
