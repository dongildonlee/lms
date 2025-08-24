# practice/views_tex.py
import os, shutil, subprocess, tempfile, textwrap
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

# Resolve tectonic binary (vendored first, PATH fallback)
TECTONIC_BIN = getattr(settings, "TECTONIC_BIN", None) or os.path.join(settings.BASE_DIR, "bin", "tectonic")
if not os.path.exists(TECTONIC_BIN):
    TECTONIC_BIN = shutil.which("tectonic")

# Minimal wrapper when the snippet is not a full document
SNIPPET_WRAPPER = r"""
\documentclass[tikz,border=3pt]{standalone}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath,amssymb}
\usepackage{tikz}
\begin{document}
%s
\end{document}
""".lstrip()

def _compile_pdf(tex_source: str) -> bytes:
    if not TECTONIC_BIN:
        return HttpResponse("tectonic_not_found", status=500, content_type="text/plain")
    with tempfile.TemporaryDirectory() as tmp:
        tex_path = os.path.join(tmp, "doc.tex")
        pdf_path = os.path.join(tmp, "doc.pdf")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_source)

        try:
            run = subprocess.run(
                [TECTONIC_BIN, "--keep-intermediates", "-o", tmp, tex_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=45,
            )
        except subprocess.CalledProcessError as e:
            log = (e.stdout or b"").decode("utf-8", "ignore")
            return HttpResponse(log, status=400, content_type="text/plain")
        except Exception as e:
            return HttpResponse(str(e), status=500, content_type="text/plain")

        if not os.path.exists(pdf_path):
            return HttpResponse("PDF not produced", status=500, content_type="text/plain")

        with open(pdf_path, "rb") as f:
            return f.read()

@csrf_exempt
@require_http_methods(["GET", "POST"])
def tex_pdf(request):
    """
    Compile TeX to PDF.
    - If 'tex' contains \documentclass, compile as-is.
    - Otherwise wrap it in a tiny standalone preamble (TikZ-capable).
    Accepts:
      * POST: x-www-form-urlencoded or multipart (field 'tex')
      * GET : query param 'tex'
    """
    tex = ""
    if request.method == "POST":
        tex = request.POST.get("tex", "")
        if not tex and request.body and request.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
            # Safety: in case framework parsing failed
            tex = request.body.decode("utf-8", "ignore")
            # crude extraction
            if tex.startswith("tex="):
                tex = tex[4:]
    else:
        tex = request.GET.get("tex", "")

    if not tex or not tex.strip():
        return HttpResponseBadRequest("missing tex")

    # Full document or snippet?
    contains_docclass = "\\documentclass" in tex
    full_tex = tex if contains_docclass else (SNIPPET_WRAPPER % tex)

    pdf_or_resp = _compile_pdf(full_tex)
    if isinstance(pdf_or_resp, HttpResponse):
        return pdf_or_resp

    resp = HttpResponse(pdf_or_resp, content_type="application/pdf")
    resp["Cache-Control"] = "no-store"
    return resp



