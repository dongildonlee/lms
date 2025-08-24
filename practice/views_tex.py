# practice/views_tex.py
import os, shutil, subprocess, tempfile, textwrap, json
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

TECTONIC_BIN = getattr(settings, "TECTONIC_BIN", None) or os.path.join(settings.BASE_DIR, "bin", "tectonic")
if not os.path.exists(TECTONIC_BIN):
    TECTONIC_BIN = shutil.which("tectonic")

STANDALONE_WRAPPER = r"""\documentclass{standalone}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath,amssymb}
\usepackage{tikz}
\begin{document}
%s
\end{document}
"""

# practice/views_tex.py
import os, shutil, subprocess, tempfile, textwrap, json, re
# …existing imports…

BODY_RE = re.compile(r"\\begin\{document\}(.*?)\\end\{document\}", re.S)

@csrf_exempt
@require_http_methods(["GET","POST"])
def tex_pdf(request):
    # Read TeX from GET ?tex=... or POST JSON {"tex": "..."}
    tex = ""
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

    tex = tex.replace("\r\n", "\n").replace("\r", "\n")

    # If caller sent a full doc, compile only the document body as 'standalone'
    if "\\documentclass" in tex:
        # make sure begin/end exist so the regex will work
        if "\\begin{document}" not in tex:
            tex += "\n\\begin{document}\n"
        if "\\end{document}" not in tex:
            tex += "\n\\end{document}\n"

        m = BODY_RE.search(tex)
        if m:
            body = m.group(1)
            full_tex = STANDALONE_WRAPPER % body
        else:
            # fallback: compile as-is (will be a full page)
            full_tex = tex
    else:
        full_tex = STANDALONE_WRAPPER % tex

    with tempfile.TemporaryDirectory() as tmp:
        tex_path = os.path.join(tmp, "doc.tex")
        pdf_path = os.path.join(tmp, "doc.pdf")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(full_tex)
        try:
            run = subprocess.run(
                [TECTONIC_BIN, "--keep-intermediates", "-o", tmp, tex_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True, timeout=45,
            )
        except subprocess.CalledProcessError as e:
            return HttpResponse((e.stdout or b"").decode("utf-8","ignore"), status=400, content_type="text/plain")
        except Exception as e:
            return HttpResponse(str(e), status=500, content_type="text/plain")

        if not os.path.exists(pdf_path):
            return HttpResponse("PDF not produced", status=500, content_type="text/plain")
        data = open(pdf_path, "rb").read()

    resp = HttpResponse(data, content_type="application/pdf")
    resp["Cache-Control"] = "no-store"
    return resp







