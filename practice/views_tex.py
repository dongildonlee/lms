# practice/views_tex.py
import json, os, subprocess, tempfile, textwrap, shutil
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

TEX_WRAPPER = r"""
\documentclass[tikz,border=3pt]{standalone}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath,amssymb}
\usepackage{tikz}
\usepackage{geometry}
\geometry{margin=1in}
\begin{document}
%s
\end{document}
"""

def _run_tectonic(tex_source: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tex_path = os.path.join(tmp, "doc.tex")
        pdf_path = os.path.join(tmp, "doc.pdf")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_source)
        # bin/tectonic in repo; fall back to system if not found
        bin_path = os.path.join(os.getcwd(), "bin", "tectonic")
        cmd = [bin_path if os.path.exists(bin_path) else "tectonic", "-X", "compile", tex_path, "--outdir", tmp, "--print"]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        if not os.path.exists(pdf_path):
            raise RuntimeError(proc.stdout.decode("utf-8", errors="ignore"))
        with open(pdf_path, "rb") as f:
            return f.read()

TECTONIC_BIN = getattr(settings, "TECTONIC_BIN", None) \
    or os.path.join(settings.BASE_DIR, "bin", "tectonic")
# Fallback to PATH if not in repo
if not os.path.exists(TECTONIC_BIN):
    TECTONIC_BIN = shutil.which("tectonic")

@require_GET
def tex_pdf(request):
    tex = request.GET.get("tex", "")
    if not tex or not tex.strip():
        return HttpResponseBadRequest("missing tex")

    # If a full doc was provided, compile as-is; otherwise wrap it.
    contains_docclass = "\\documentclass" in tex

    if contains_docclass:
        full_tex = tex
    else:
        full_tex = textwrap.dedent(r"""
            \documentclass{standalone}
            \usepackage[T1]{fontenc}
            \usepackage{lmodern}
            \usepackage{amsmath,amssymb}
            \usepackage{tikz}
            \begin{document}
            %s
            \end{document}
        """).strip() % tex

    with tempfile.TemporaryDirectory() as tmp:
        tex_path = os.path.join(tmp, "doc.tex")
        pdf_path = os.path.join(tmp, "doc.pdf")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(full_tex)

        try:
            run = subprocess.run(
                [TECTONIC_BIN, "-X", "compile", tex_path,
                "--outdir", tmp, "--keep-logs", "--keep-intermediates"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                check=True, timeout=40,
            )

        except subprocess.CalledProcessError as e:
            log = (e.stdout or b"").decode("utf-8", "ignore")
            return HttpResponse(log, status=400, content_type="text/plain")
        except Exception as e:
            return HttpResponse(str(e), status=500, content_type="text/plain")

        if not os.path.exists(pdf_path):
            return HttpResponse("PDF not produced", status=500, content_type="text/plain")

        with open(pdf_path, "rb") as f:
            data = f.read()

    resp = HttpResponse(data, content_type="application/pdf")
    resp["Cache-Control"] = "no-store"
    return resp

