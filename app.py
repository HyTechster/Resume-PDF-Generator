"""Flask app: show the form, preview a resume, download it as a PDF."""

from __future__ import annotations

import os
import re
import secrets
from base64 import b64encode
from io import BytesIO

from flask import Flask, render_template, request, send_file
from werkzeug.datastructures import ImmutableMultiDict, MultiDict
from werkzeug.exceptions import RequestEntityTooLarge

from render import (
    ACCENTS,
    BASE_DIR,
    PAGE_SIZES,
    STYLE_OPTIONS,
    Style,
    available_templates,
    render_page_images,
    render_pdf,
)
from render_docx import DOCX_MIME, render_docx
from resume import FORM_SECTIONS, Resume, from_form, parse_markdown, validate

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

SAMPLE_MD = (BASE_DIR / "samples" / "sample.md").read_text(encoding="utf-8")
DEFAULTS = ImmutableMultiDict({"mode": "form", "template": "classic", "page_size": "A4"})
SETTING_KEYS = {"template", "page_size", *STYLE_OPTIONS}
TEMPLATE_NOTES = {
    "classic": "Serif, black on white. Safest for ATS.",
    "modern": "Clean sans with one accent colour.",
    "minimal": "Airy, small caps, thin rules.",
}


def _options() -> dict:
    """Everything the style and template controls need, shared by both pages."""
    return {
        "templates": available_templates(),
        "template_notes": TEMPLATE_NOTES,
        "page_sizes": PAGE_SIZES,
        "style_options": STYLE_OPTIONS,
        "accents": ACCENTS,
    }


def _form_page(values: MultiDict, errors: dict[str, str], status: int = 200, restore_draft: bool = False):
    return render_template(
        "index.html",
        values=values,
        errors=errors,
        restore_draft=restore_draft,
        sections=FORM_SECTIONS,
        sample_md=SAMPLE_MD,
        **_options(),
    ), status


def _read_request() -> tuple[Resume, str, str, Style, dict[str, str]]:
    form = request.form
    mode = "markdown" if form.get("mode") == "markdown" else "form"
    resume = parse_markdown(form.get("markdown", "")) if mode == "markdown" else from_form(form)
    errors = validate(resume, mode)

    template = form.get("template", "classic")
    page_size = form.get("page_size", "A4")
    if template not in available_templates():
        errors["template"] = "Please pick one of the templates."
    if page_size not in PAGE_SIZES:
        errors["page_size"] = "Please pick A4 or Letter."
    return resume, template, page_size, Style.from_form(form), errors


def download_name(name: str, ext: str) -> str:
    # \w keeps letters in any script (Chinese, Tamil, Jawi); Flask encodes non-ASCII names for the header.
    safe = re.sub(r"[^\w]+", "_", name).strip("_") or "My"
    return f"{safe}_Resume.{ext}"


def _download(ext: str):
    resume, template, page_size, style, errors = _read_request()
    if errors:
        return _form_page(request.form, errors, 400)
    if ext == "pdf":
        data, mimetype = render_pdf(resume, template, page_size, style), "application/pdf"
    else:
        data, mimetype = render_docx(resume, template, page_size, style), DOCX_MIME
    return send_file(BytesIO(data), mimetype=mimetype, as_attachment=True, download_name=download_name(resume.name, ext))


@app.get("/")
def index():
    return _form_page(DEFAULTS, {}, restore_draft=True)


@app.post("/preview")
def preview():
    resume, template, page_size, style, errors = _read_request()
    if errors:
        return _form_page(request.form, errors, 400)
    # The preview shows images of the real PDF pages, so page breaks match the download exactly.
    pages = [
        {"src": "data:image/webp;base64," + b64encode(page.data).decode(), "width": page.width // 2, "height": page.height // 2}
        for page in render_page_images(resume, template, page_size, style)
    ]
    return render_template(
        "preview.html",
        pages=pages,
        name=resume.name,
        hidden=[(k, v) for k, v in request.form.items(multi=True) if k not in SETTING_KEYS],
        values=request.form,
        **_options(),
    )


@app.post("/pdf")
def pdf():
    return _download("pdf")


@app.post("/docx")
def docx():
    return _download("docx")


@app.errorhandler(RequestEntityTooLarge)
def too_large(_):
    # The browser draft refills the form, so nothing typed is lost.
    return _form_page(
        DEFAULTS,
        {"form": "That was over 200 KB. Resumes are usually much smaller, so try trimming it down."},
        413,
        restore_draft=True,
    )
