# practice/views_tex.py
import os, re, tempfile, subprocess, textwrap
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required

# Minimal standalone doc so the page is tightly cropped
TEX_WRAPPER = r"""
\documentclass[tikz,border=2pt]{standalone}
\usepackage{amsmath,amssymb}
\usepackage{booktabs,array}
\usepackage{tikz}
\usepackage{pgfplots}
\pgfplotsset{compat=1.17}
\begin{document}
%s
\end{document}
"""

_FORBIDDEN = re.compile(
    r"(\\write18|\\input|\\include|\\openout|\\read|\\usepackage\{shellesc\}|\\immediate\\write|\\catcode)"
)

def _safe_wrap(snippet: str) -> str:
    # very basic guardrails
    if not snippet or len(snippet) > 50_000:
        raise ValueError("empty or too large")
    if _FORBIDDEN.search(snippet):
        raise ValueError("forbidden TeX primitive")
    return TEX_WRAPPER % snippet

@login_required
@require_GET
def tex_pdf(request):
    """Compile ?tex=... to a single-page PDF and return it."""
    raw = request.GET.get("tex", "")
    try:
        doc = _safe_wrap(raw)
    except ValueError as e:
        return HttpResponseBadRequest(str(e))

    # where your vendored binary lives (you already added this)
    tectonic = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "bin", "tectonic"))
    if not os.path.exists(tectonic):
        return HttpResponseBadRequest("tectonic_not_found")

    with tempfile.TemporaryDirectory() as td:
        tex_path = os.path.join(td, "doc.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(doc)

        # Run tectonic → PDF
        proc = subprocess.run(
            [tectonic, "--keep-logs", "--synctex=0", "-o", td, tex_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20
        )
        if proc.returncode != 0:
            msg = proc.stdout.decode("utf-8", "ignore")
            return HttpResponseBadRequest("tectonic_failed\n" + msg)

        pdf_path = os.path.join(td, "doc.pdf")
        with open(pdf_path, "rb") as f:
            pdf = f.read()

    resp = HttpResponse(pdf, content_type="application/pdf")
    # Cache so repeated views are cheap
    resp["Cache-Control"] = "public, max-age=3600"
    return resp
