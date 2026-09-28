"""Resume + template name -> HTML -> PDF bytes. Everything stays in memory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import pypdfium2 as pdfium
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from weasyprint import HTML
from weasyprint.urls import URLFetcher

from resume import Resume

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "resume_templates"
STATIC_DIR = BASE_DIR / "static"
PAGE_SIZES = ("A4", "Letter")

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)


# Formal colours only. "default" keeps the template's own accent.
ACCENTS: dict[str, str] = {
    "default": "",
    "black": "#1c1c1a",
    "navy": "#1f3a5f",
    "teal": "#0d6b62",
    "forest": "#2e5a3c",
    "burgundy": "#74202f",
    "slate": "#44546a",
}
# Field -> allowed values. The first value is the default.
STYLE_OPTIONS: dict[str, tuple[str, ...]] = {
    "accent": tuple(ACCENTS),
    "header_align": ("default", "left", "center", "right"),
    "title_align": ("default", "left", "center"),
    "body_align": ("left", "justify"),
    "dates": ("right", "below"),
}


@dataclass
class Style:
    accent: str = "default"
    header_align: str = "default"
    title_align: str = "default"
    body_align: str = "left"
    dates: str = "right"

    @classmethod
    def from_form(cls, form: Mapping[str, str]) -> Style:
        """Anything not on the whitelist falls back to the default, so user input never reaches the CSS."""
        return cls(**{
            key: form.get(key) if form.get(key) in allowed else allowed[0]
            for key, allowed in STYLE_OPTIONS.items()
        })

    def css(self) -> str:
        rules = []
        if self.accent != "default":
            rules.append(f"body {{ --accent: {ACCENTS[self.accent]}; }}")
        if self.header_align != "default":
            rules.append(f".head {{ text-align: {self.header_align}; }}")
        if self.title_align != "default":
            rules.append(f".section-title {{ text-align: {self.title_align}; }}")
        if self.body_align == "justify":
            rules.append(".section-body p, .section-body li { text-align: justify; }")
        if self.dates == "below":
            rules.append(".entry-head { display: block; } .entry-date { display: block; max-width: none; text-align: left; margin-top: 0.5pt; }")
        return "\n".join(rules)


def available_templates() -> list[str]:
    """Whitelist: every folder in resume_templates/ that has a resume.html."""
    return sorted(p.name for p in TEMPLATES_DIR.iterdir() if (p / "resume.html").is_file())


def render_html(resume: Resume, template: str, page_size: str = "A4", style: Style | None = None) -> str:
    if template not in available_templates():
        raise ValueError(f"Unknown template: {template!r}")
    if page_size not in PAGE_SIZES:
        raise ValueError(f"Unknown page size: {page_size!r}")

    css = (TEMPLATES_DIR / "shared.css").read_text(encoding="utf-8")
    css += (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    css += "\n" + (style or Style()).css()
    if page_size != "A4":
        css += f"\n@page {{ size: {page_size}; }}\n"

    return _env.get_template(f"{template}/resume.html").render(resume=resume, css=Markup(css))


class LocalStaticFetcher(URLFetcher):
    """Only serve files from static/. Remote URLs, data: URLs and other paths are refused (no SSRF)."""

    def fetch(self, url, headers=None):
        parsed = urlparse(url)
        if parsed.scheme == "file":
            path = Path(url2pathname(unquote(parsed.path))).resolve()
            if path.is_relative_to(STATIC_DIR) and path.is_file():
                return super().fetch(url, headers)
        raise ValueError(f"Blocked resource: {url}")


def render_pdf(resume: Resume, template: str, page_size: str = "A4", style: Style | None = None) -> bytes:
    html = render_html(resume, template, page_size, style)
    return HTML(
        string=html,
        base_url=BASE_DIR.as_uri() + "/",
        url_fetcher=LocalStaticFetcher(),
    ).write_pdf()


@dataclass
class PageImage:
    data: bytes
    width: int
    height: int


def render_page_images(
    resume: Resume,
    template: str,
    page_size: str = "A4",
    style: Style | None = None,
    width_px: int = 1588,
    fmt: str = "WEBP",
) -> list[PageImage]:
    """Render the real PDF and return one image per page, so the preview shows exact page breaks.

    1588px is twice the on-screen sheet width (794px), which keeps text sharp on high-density screens.
    """
    pdf = pdfium.PdfDocument(render_pdf(resume, template, page_size, style))
    try:
        pages = []
        for page in pdf:
            image = page.render(scale=width_px / page.get_width()).to_pil()
            buffer = BytesIO()
            if fmt == "WEBP":
                image.save(buffer, fmt, quality=85)
            else:
                image.save(buffer, fmt, optimize=True)
            pages.append(PageImage(buffer.getvalue(), image.width, image.height))
        return pages
    finally:
        pdf.close()
