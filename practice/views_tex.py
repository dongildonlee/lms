# practice/views_tex.py
import os
import re
import json
import shutil
import subprocess
import tempfile
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

# --- Locate tectonic ---------------------------------------------------------
TECTONIC_BIN = getattr(settings, "TECTONIC_BIN", None) or os.path.join(
    settings.BASE_DIR, "bin", "tectonic"
)
if not os.path.exists(TECTONIC_BIN):
    TECTONIC_BIN = shutil.which("tectonic")  # fall back to PATH

# Minimal wrapper so figures/equations compile as a tight page
STANDALONE_WRAPPER = r"""\documentclass{standalone}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath,amssymb}
\usepackage{tikz}
\begin{document}
%s
\end{document}
"""

BODY_RE = re.compile(r"\\begin\{document\}(.*?)\\end\{document\}", re.S)


# ---------------------------------------------------------------------------
# Public helper: compile a TeX string to PDF bytes (used by teacher packet too)
# ---------------------------------------------------------------------------
def compile_tex_bytes(tex: str) -> bytes:
    """
    Compile a LaTeX string to PDF bytes using tectonic.
    - If it's a full document (contains \documentclass), compile AS-IS.
    - If it's a snippet, wrap it with a minimal standalone preamble.
    Raises RuntimeError with a readable log on failure.
    """
    if not tex or not tex.strip():
        raise RuntimeError("missing tex")
    if not TECTONIC_BIN:
        raise RuntimeError("tectonic binary not found")

    tex = tex.replace("\r\n", "\n").replace("\r", "\n")

    if "\\documentclass" in tex:
        full_tex = tex  # compile as-is (teacher packet with your own preamble)
    else:
        full_tex = STANDALONE_WRAPPER % tex  # snippet → standalone

    with tempfile.TemporaryDirectory() as tmp:
        tex_path = os.path.join(tmp, "doc.tex")
        pdf_path = os.path.join(tmp, "doc.pdf")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(full_tex)

        try:
            subprocess.run(
                [TECTONIC_BIN, "--keep-intermediates", "-o", tmp, tex_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                check=True, timeout=60,
            )
        except subprocess.CalledProcessError as e:
            log = (e.stdout or b"").decode("utf-8", "ignore")
            raise RuntimeError(log or "tectonic failed")
        except Exception as e:
            raise RuntimeError(str(e))

        if not os.path.exists(pdf_path):
            raise RuntimeError("PDF not produced")

        with open(pdf_path, "rb") as f:
            return f.read()



# ---------------------------------------------------------------------------
# Existing endpoint: POST/GET TeX -> PDF (used by practice page)
# ---------------------------------------------------------------------------
@csrf_exempt
@require_http_methods(["GET", "POST"])
def tex_pdf(request):
    # Read TeX from GET ?tex=... or POST JSON {"tex":"..."}
    if request.method == "GET":
        tex = request.GET.get("tex", "") or ""
    else:
        try:
            payload = json.loads(request.body.decode("utf-8"))
            tex = payload.get("tex", "") or ""
        except Exception:
            return HttpResponseBadRequest("invalid json")

    if not tex.strip():
        return HttpResponseBadRequest("missing tex")

    try:
        pdf_bytes = compile_tex_bytes(tex)
    except RuntimeError as e:
        # Return tectonic log as plain text for easy debugging in the UI
        return HttpResponse(str(e), status=400, content_type="text/plain")

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Cache-Control"] = "no-store"
    return resp








