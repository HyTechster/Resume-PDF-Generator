"""Turn form fields or a Markdown document into one Resume shape."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from markdown_it import MarkdownIt

# Raw HTML off: anything like <script> in user input comes out as escaped text.
# Images off: resumes here are text only, and nothing should point at remote files.
# Headings off: `##` and `###` are handled by the parser below, so a stray `# x` stays plain text
# instead of becoming a giant heading inside a section.
_md = MarkdownIt("commonmark", {"html": False}).disable(["image", "heading", "lheading"])

# (key, title, kind). "entries" are repeatable cards, "skills" are label + items rows.
FORM_SECTIONS: list[tuple[str, str, str]] = [
    ("summary", "Summary", "text"),
    ("experience", "Experience", "entries"),
    ("education", "Education", "entries"),
    ("projects", "Projects", "entries"),
    ("skills", "Skills", "skills"),
    ("certifications", "Certifications", "entries"),
]
ENTRY_FIELDS = ("title", "org", "location", "dates", "details")

_ENTRY_SPLIT = re.compile(r"^(?=### )", re.MULTILINE)
_DATE_LINE = re.compile(r"^\s*(?:\*([^*]+)\*|_([^_]+)_)\s*$")
# Only 1-2 digit list numbers, so a line like "2024. Won the hackathon" keeps its year.
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+")


@dataclass
class Section:
    title: str
    html: str


@dataclass
class Resume:
    name: str
    headline: str = ""
    contacts: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


def _inline(text: str) -> str:
    return _md.renderInline(text.strip())


def entry_html(title_html: str, date_html: str, rest_html: str) -> str:
    """One entry: heading with the date on the same line, then the details. Same markup for both modes."""
    title = f"<h3>{title_html}</h3>" if title_html else ""
    date = f'<span class="entry-date">{date_html}</span>' if date_html else ""
    head = f'<div class="entry-head">{title}{date}</div>' if title or date else ""
    return f'<div class="entry">{head}{rest_html}</div>'


def render_markdown(text: str) -> str:
    """Render a section body. Each `###` entry is wrapped, and an italic line under it becomes the date."""
    parts = [p for p in _ENTRY_SPLIT.split(text.strip()) if p.strip()]
    html = []
    for part in parts:
        if not part.startswith("### "):
            html.append(_md.render(part))
            continue
        heading, _, rest = part.partition("\n")
        lines = rest.strip("\n").split("\n")
        date_html = ""
        if lines and (m := _DATE_LINE.match(lines[0])):
            date_html = _inline(m[1] or m[2])
            lines = lines[1:]
        rest = "\n".join(lines)
        html.append(entry_html(_inline(heading[4:]), date_html, _md.render(rest) if rest.strip() else ""))
    return "".join(html)


def _section(title: str, body: str) -> Section | None:
    title, body = title.strip(), body.strip()
    if not title or not body:
        return None
    return Section(title=title, html=render_markdown(body))


def split_contacts(line: str) -> list[str]:
    return [c.strip() for c in re.split(r"[|\n]", line) if c.strip()]


def parse_markdown(text: str) -> Resume:
    """First `#` is the name, then headline, then `|`-separated contacts, then `##` sections."""
    lines = text.replace("\r\n", "\n").split("\n")
    name, header, i = "", [], 0

    while i < len(lines) and not lines[i].startswith("## "):
        line = lines[i].strip()
        if not name and line.startswith("# "):
            name = line[2:].strip()
        elif name and line:
            header.append(line)
        i += 1

    headline, contacts = "", []
    if header and "|" not in header[0]:
        headline = header.pop(0)
    if header:
        contacts = split_contacts(" | ".join(header))

    sections: list[Section] = []
    title, body = "", []
    for line in lines[i:]:
        if line.startswith("## "):
            if s := _section(title, "\n".join(body)):
                sections.append(s)
            title, body = line[3:], []
        else:
            body.append(line)
    if s := _section(title, "\n".join(body)):
        sections.append(s)

    return Resume(name=name, headline=headline, contacts=contacts, sections=sections)


# Form mode

def _getlist(form: Mapping, key: str) -> list[str]:
    if hasattr(form, "getlist"):
        return [(v or "").strip() for v in form.getlist(key)]
    value = form.get(key)
    if value is None:
        return []
    return [(v or "").strip() for v in (value if isinstance(value, (list, tuple)) else [value])]


def _rows(form: Mapping, key: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    """Zip repeated fields (experience_title, experience_org, ...) into one dict per row."""
    columns = {f: _getlist(form, f"{key}_{f}") for f in fields}
    count = max((len(c) for c in columns.values()), default=0)
    return [{f: (c[i] if i < len(c) else "") for f, c in columns.items()} for i in range(count)]


def _bullets(text: str) -> str:
    items = [_BULLET.sub("", line).strip() for line in text.splitlines()]
    items = [i for i in items if i]
    return "<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>" if items else ""


def _entries_html(rows: list[dict[str, str]]) -> str:
    html = []
    for row in rows:
        if not any(row.values()):
            continue
        sub = ", ".join(v for v in (row["org"], row["location"]) if v)
        rest = (f"<p>{_inline(sub)}</p>" if sub else "") + _bullets(row["details"])
        html.append(entry_html(_inline(row["title"]), _inline(row["dates"]), rest))
    return "".join(html)


def _skills_html(rows: list[dict[str, str]]) -> str:
    items = []
    for row in rows:
        if not row["items"]:
            continue
        label = f"<strong>{_inline(row['label'])}:</strong> " if row["label"] else ""
        items.append(f"<li>{label}{_inline(row['items'])}</li>")
    return f"<ul>{''.join(items)}</ul>" if items else ""


def from_form(form: Mapping) -> Resume:
    get = lambda key: (_getlist(form, key) or [""])[0]  # noqa: E731
    contacts = [get("email"), get("phone"), get("location")]
    contacts += [c.strip() for c in re.split(r"[,\n]", get("links")) if c.strip()]

    sections = []
    for key, title, kind in FORM_SECTIONS:
        if kind == "text":
            html = _md.render(get(key)) if get(key) else ""
        elif kind == "skills":
            html = _skills_html(_rows(form, key, ("label", "items")))
        else:
            html = _entries_html(_rows(form, key, ENTRY_FIELDS))
        if html:
            sections.append(Section(title=title, html=html))

    return Resume(
        name=get("name"),
        headline=get("headline"),
        contacts=[c for c in contacts if c],
        sections=sections,
    )


def validate(resume: Resume, mode: str) -> dict[str, str]:
    """Return field -> message. Empty dict means good to render."""
    errors: dict[str, str] = {}
    if mode == "markdown":
        if not resume.name:
            errors["markdown"] = "Start with your name on a line like: # Nurul Aisyah"
        elif not resume.sections:
            errors["markdown"] = "Add at least one section, starting with ## (for example ## Experience)."
    else:
        if not resume.name:
            errors["name"] = "Please add your full name."
        if not resume.sections:
            errors["sections"] = "Fill in at least one section, like Experience or Education."
    return errors
