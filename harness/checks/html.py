"""Is this a usable, self-contained HTML page?

Self-contained matters for a local-first harness: a page that only renders when
a CDN is reachable has failed at the thing it was asked to do.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from .base import CheckResult, extract

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}
# Elements whose presence in <body> means something was actually rendered.
CONTENT = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "section", "article",
           "ul", "ol", "li", "table", "img", "svg", "canvas", "main", "header",
           "footer", "nav", "form", "button", "a", "span", "pre", "figure"}


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.unclosed: list[str] = []
        self.body_content = 0
        self.title = ""
        self._in_title = False
        self._in_body = False

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self._in_body = True
        if tag == "title":
            self._in_title = True
        if tag not in VOID:
            self.stack.append(tag)
        if self._in_body and tag in CONTENT:
            self.body_content += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.stack:
            # Unwinding to `tag` silently closes everything above it. Those are
            # the unclosed elements, and they used to vanish here: the stack
            # ended up empty and the only warning left was the doctype one,
            # which was itself a harness bug. Fixing that exposed this.
            while self.stack:
                top = self.stack.pop()
                if top == tag:
                    break
                self.unclosed.append(top)
        else:
            self.unclosed.append(tag)

    def handle_data(self, data):
        if self._in_title:
            self.title += data.strip()


def check(text: str) -> CheckResult:
    # Read the doctype off the ORIGINAL text. extract() searches root tags in
    # order and finds <html first, slicing the doctype off before this check
    # could see it, so every well-formed page was warned for a missing doctype.
    had_doctype = bool(re.search(r"<!doctype\s+html", text, re.I))
    src = extract(text, ("html", "!doctype"))
    if not src.strip():
        return CheckResult(False, "no HTML found in output")

    p = _Parser()
    try:
        p.feed(src)
        p.close()
    except Exception as exc:  # noqa: BLE001 - parser can raise anything
        return CheckResult(False, f"HTML parse error: {exc}")

    warnings: list[str] = []
    if not had_doctype:
        warnings.append("missing doctype: triggers quirks mode")
    left_open = p.unclosed + p.stack
    if left_open:
        warnings.append(f"unclosed tags: {', '.join(left_open[:5])}")
    if re.search(r'(?:src|href)\s*=\s*["\']https?://', src, re.I):
        warnings.append("external resource: page is not self-contained")

    if p.body_content == 0:
        return CheckResult(False, "body renders nothing", warnings,
                           has_title=bool(p.title))

    return CheckResult(True, "", warnings, shape_count=p.body_content,
                       has_title=bool(p.title))


#: The keys a web case's `structure` assertion may carry. #603.
STRUCTURE_KEYS = {"title", "headings", "tables", "nav", "sections", "lists", "dl", "articles", "form",
                  "self_contained"}
#: Attributes the browser fetches on any element; an <a> or <area> href is a link, not a load, and <link href> is.
_LOADS = ("src", "data", "poster", "srcset", "background")
_SILENT = {"script", "style", "template"}


class _Node:
    __slots__ = ("tag", "attrs", "kids", "parent")

    def __init__(self, tag: str, attrs: dict, parent=None):
        self.tag, self.attrs, self.kids, self.parent = tag, attrs, [], parent

    def walk(self):
        for k in self.kids:
            if isinstance(k, _Node):
                yield k
                yield from k.walk()

    def all(self, *tags):
        return [n for n in self.walk() if n.tag in tags]

    def text(self, skip=()) -> str:
        out = []
        for k in self.kids:
            if isinstance(k, str):
                out.append(k)
            elif k.tag not in _SILENT and k.tag not in skip:
                out.append(" " + k.text(skip) + " ")
        return " ".join("".join(out).split())


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.at = _Node("#root", {})

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.at)
        self.at.kids.append(node)
        if tag not in VOID:
            self.at = node

    def handle_startendtag(self, tag, attrs):
        self.at.kids.append(_Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.at))

    def handle_endtag(self, tag):
        n = self.at
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.at = n.parent

    def handle_data(self, data):
        self.at.kids.append(data)


def validate_structure(spec) -> None:
    """Refuse a structure assertion with a key the checker cannot read."""
    if not isinstance(spec, dict):
        raise ValueError("structure must be a mapping")
    unknown = set(spec) - STRUCTURE_KEYS
    if unknown:
        raise ValueError(f"unknown structure key(s): {', '.join(sorted(unknown))}")


def _tree(text: str) -> _Node:
    t = _Tree()
    t.feed(extract(text, ("html", "!doctype")) or text)
    t.close()
    return t.root


def _own(li: _Node) -> str:
    return li.text(skip=("ul", "ol"))


def _items(lst: _Node) -> list:
    out = []
    for li in (k for k in lst.kids if isinstance(k, _Node) and k.tag == "li"):
        sub = [n for n in li.kids if isinstance(n, _Node) and n.tag in ("ul", "ol")]
        out.append([_own(li), _items(sub[0])] if sub else _own(li))
    return out


def _table(t: _Node) -> tuple[str, list, list]:
    cap = next((c.text() for c in t.all("caption")), "")
    rows = [[c.text() for c in tr.kids if isinstance(c, _Node) and c.tag in ("td", "th")]
            for tr in t.all("tr")]
    heads = [tr for tr in t.all("tr") if tr.all("th") and not tr.all("td")]
    head = [c.text() for c in heads[0].kids if isinstance(c, _Node) and c.tag == "th"] if heads else []
    body = [r for tr, r in zip(t.all("tr"), rows) if tr not in heads]
    return cap, head, body


def _label_of(root: _Node, el: _Node) -> str:
    if el.attrs.get("id"):
        for lab in root.all("label"):
            if lab.attrs.get("for") == el.attrs["id"]:
                return lab.text()
    n = el.parent
    while n is not None:
        if n.tag == "label":
            return n.text(skip=("textarea", "select"))
        n = n.parent
    return el.attrs.get("aria-label", "")


def _form(root: _Node, want: dict) -> str:
    controls = root.all("input", "textarea", "select")
    for f in want.get("fields", []):
        el = next((c for c in controls if c.attrs.get("name") == f["name"]), None)
        if el is None:
            return f"no form control named {f['name']!r}"
        kind = el.tag if el.tag != "input" else el.attrs.get("type", "text").lower() or "text"
        if kind != f["type"]:
            return f"control {f['name']!r} is type {kind!r}, asked {f['type']!r}"
        if ("required" in el.attrs) != bool(f["required"]):
            return f"control {f['name']!r} required is {'required' in el.attrs}, asked {bool(f['required'])}"
        if _label_of(root, el) != f["label"]:
            return f"control {f['name']!r} is labelled {_label_of(root, el)!r}, asked {f['label']!r}"
    submits = [b.text() for b in root.all("button") if b.attrs.get("type", "submit").lower() == "submit"]
    submits += [i.attrs.get("value", "") for i in root.all("input") if i.attrs.get("type", "").lower() == "submit"]
    if want.get("submit") and want["submit"] not in submits:
        return f"no submit button reading {want['submit']!r} (found {submits})"
    return ""


def _remote(url: str) -> bool:
    return bool(re.match(r"\s*(?:https?:)?//", url or "", re.I))


def structure(text: str, spec: dict) -> str:
    """'' when the page has every asserted property, else the first one it misses."""
    root = _tree(text)
    if "title" in spec:
        got = next((t.text() for t in root.all("title")), "")
        if got != spec["title"]:
            return f"title is {got!r}, asked {spec['title']!r}"
    if "headings" in spec:
        got = [[int(h.tag[1]), h.text()] for h in root.all("h1", "h2", "h3")]
        if got != [list(h) for h in spec["headings"]]:
            return f"headings are {got}, asked {spec['headings']}"
    for want in spec.get("tables", []):
        tables = [_table(t) for t in root.all("table")]
        hit = [t for t in tables if t[0] == want.get("caption", t[0])]
        if not hit:
            return f"no table captioned {want.get('caption')!r} (found {[t[0] for t in tables]})"
        _, head, body = hit[0]
        if head != want["head"]:
            return f"table {want.get('caption')!r} header is {head}, asked {want['head']}"
        for i, (g, w) in enumerate(zip(body + [None] * len(want["rows"]), want["rows"]), 1):
            if g != w:
                return f"table {want.get('caption')!r} row {i} is {g}, asked {w}"
        if len(body) != len(want["rows"]):
            return f"table {want.get('caption')!r} has {len(body)} rows, asked {len(want['rows'])}"
    if "nav" in spec:
        navs = [[[a.text(), a.attrs.get("href", "")] for a in n.all("a")] for n in root.all("nav")]
        if [list(x) for x in spec["nav"]] not in navs:
            return f"nav links are {navs}, asked {spec['nav']}"
    for sid, heading in (spec.get("sections") or {}).items():
        el = next((n for n in root.walk() if n.attrs.get("id") == sid), None)
        if el is None:
            return f"no element with id {sid!r}"
        if heading not in [h.text() for h in el.all("h1", "h2", "h3")]:
            return f"element {sid!r} has no heading {heading!r}"
    for want in spec.get("lists", []):
        tag = "ol" if want["ordered"] else "ul"
        got = [_items(n) for n in root.all(tag) if not (n.parent and n.parent.tag == "li")]
        if want["items"] not in got:
            return f"no {tag} list with items {want['items']} (found {got})"
    if "dl" in spec:
        pairs = [[[t.text() for t in d.all("dt")], [x.text() for x in d.all("dd")]] for d in root.all("dl")]
        want = [[t for t, _ in spec["dl"]], [x for _, x in spec["dl"]]]
        if want not in pairs:
            return f"no definition list {spec['dl']} (found {pairs})"
    if "articles" in spec:
        got = [[next((h.text() for h in a.all("h2", "h3")), ""), next((p.text() for p in a.all("p")), "")]
               for a in root.all("article")]
        if got != [list(x) for x in spec["articles"]]:
            return f"articles are {got}, asked {spec['articles']}"
    if "form" in spec:
        missed = _form(root, spec["form"])
        if missed:
            return missed
    if spec.get("self_contained"):
        for n in root.walk():
            names = _LOADS + (("href",) if n.tag == "link" else ())
            far = [n.attrs[a] for a in names if _remote(n.attrs.get(a, ""))]
            if far:
                return f"not self-contained: <{n.tag}> loads {far[0]}"
        for s in root.all("style"):
            if re.search(r"(?:url\(|@import)\s*['\"]?(?:https?:)?//", s.text(), re.I):
                return "not self-contained: a style loads a remote url"
    return ""
