import os, shutil, subprocess, tempfile, textwrap
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_http_methods

# Resolve tectonic binary
TECTONIC_BIN = getattr(settings, "TECTONIC_BIN", None) \
    or os.path.join(settings.BASE_DIR, "bin", "tectonic")
if not os.path.exists(TECTONIC_BIN):
    TECTONIC_BIN = shutil.which("tectonic")

WRAPPER = r"""\documentclass[tikz,border=2pt]{standalone}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath,amssymb}
\usepackage{tikz}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\begin{document}
%s
\end{document}
"""

def _extract_body(tex: str) -> str:
    """If a full document is passed, return only the content inside \\begin{document}...\\end{document}.
       Otherwise return tex unchanged."""
    start_tag = r"\begin{document}"
    end_tag   = r"\end{document}"
    if start_tag in tex and end_tag in tex:
        start = tex.find(start_tag) + len(start_tag)
        end   = tex.rfind(end_tag)
        return tex[start:end].strip()
    return tex

def _build_tex(tex: str) -> str:
    # Enforce a sane size to avoid abuse & reverse-proxy limits
    if len(tex) > 800_000:  # ~800KB of TeX is plenty
        raise ValueError("tex too large")
    # Always wrap in our stable standalone preamble
    body = _extract_body(tex)
    return WRAPPER % body

@require_http_methods(["GET", "POST"])
def tex_pdf(request):
    # Accept POST (preferred) or GET
    tex = request.POST.get("tex") if request.method == "POST" else request.GET.get("tex")
    if not tex or not tex.strip():
        return HttpResponseBadRequest("missing tex")

    try:
        full_tex = _build_tex(tex)
    except ValueError as e:
        return HttpResponseBadRequest(str(e))

    with tempfile.TemporaryDirectory() as tmp:
        tex_path = os.path.join(tmp, "doc.tex")
        pdf_path = os.path.join(tmp, "doc.pdf")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(full_tex)

        cmd = [
            TECTONIC_BIN or "tectonic",
            "-X", "compile",
            tex_path,
            "--outdir", tmp,
            "--chatterlevel=error",
            "--keep-logs",
        ]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=60,
            )
        except Exception as e:
            return HttpResponse(str(e), status=500, content_type="text/plain")

        if not os.path.exists(pdf_path) or proc.returncode != 0:
            log = (proc.stdout or b"").decode("utf-8", "ignore")
            if len(log) > 20000:
                log = log[:20000] + "\n...\n(truncated)"
            return HttpResponse(log, status=400, content_type="text/plain")

        with open(pdf_path, "rb") as f:
            data = f.read()

    resp = HttpResponse(data, content_type="application/pdf")
    resp["Cache-Control"] = "no-store"
    return resp


