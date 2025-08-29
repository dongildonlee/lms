# practice/views.py
from collections import OrderedDict
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login as auth_login
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, render, redirect
from django.middleware.csrf import get_token
from django.http import FileResponse, HttpResponse, HttpResponseBadRequest, Http404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET
from django.conf import settings
from django.db.models import Sum, Avg

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status, permissions

import io
import traceback
import re
import os
import tempfile
import subprocess
import shutil, logging
import hashlib

from django.db.models.functions import Random

from .models import Question, Attempt, AttemptItem, Tag, AttemptView
from .forms import StudentSignupForm
from django.template.loader import render_to_string
from pathlib import Path

import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from django.utils import timezone
from .views_tex import compile_tex_bytes


logger = logging.getLogger(__name__)

def _normalize_tex(s: str) -> str:
    if not s:
        return s
    s = re.sub(r'<br\s*/?>', ' ', s, flags=re.I)
    s = re.sub(r'\\\\(?!\[|\(|\{)', ' ', s)      # \\ -> space (not \\\[, \\\(, \\\{)
    s = re.sub(r'\s*\n+\s*', ' ', s)             # collapse newlines
    s = re.sub(r'\s{2,}', ' ', s)                # collapse multi-spaces
    return s.strip()


# --- helpers -----------------------------------------------------------------
def user_is_teacher(user):
    # Staff or member of "Teachers" group count as teachers
    return user.is_staff or user.groups.filter(name="Teachers").exists()


def evaluate_answer(q: Question, submitted: dict) -> bool:
    t = q.type
    if t == "mcq":
        return submitted.get("choice") == (q.correct or {}).get("choice")
    if t == "numeric":
        try:
            val = float(submitted.get("value"))
            true = float((q.correct or {}).get("value"))
        except (TypeError, ValueError):
            return False
        eps = float((q.correct or {}).get("tolerance", 1e-3))
        return abs(val - true) <= eps
    if t in {"short", "algebra"}:
        norm = lambda s: "".join((s or "").lower().split())
        return norm(submitted.get("text")) == norm((q.correct or {}).get("text"))
    return False

def _render_latex_pdf(tex_source: str) -> bytes:
    """
    Compile LaTeX to PDF using Tectonic.
    Tries modern '-X compile' first; falls back to legacy '<file> --outdir ...'.
    """
    exe = _tectonic_path()
    if not exe:
        raise RuntimeError("tectonic_not_found")

    with tempfile.TemporaryDirectory() as tmp:
        tex_path = os.path.join(tmp, "doc.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_source)

        env = os.environ.copy()
        env.setdefault("TEXMFHOME", os.path.join(tmp, "texmf"))

        # Try modern CLI
        cmd_modern = [exe, "-X", "compile", tex_path, "--outdir", tmp, "--synctex=0", "--keep-logs"]
        proc = subprocess.run(cmd_modern, cwd=tmp, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if proc.returncode != 0:
            # Fallback to legacy CLI
            cmd_legacy = [exe, tex_path, "--outdir", tmp, "--synctex=0", "--keep-logs"]
            proc2 = subprocess.run(cmd_legacy, cwd=tmp, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if proc2.returncode != 0:
                raise RuntimeError("tectonic_failed:\n" + proc.stdout + "\n" + proc2.stdout)

        pdf_path = os.path.join(tmp, "doc.pdf")
        with open(pdf_path, "rb") as fh:
            return fh.read()




# --- auth pages ---------------------------------------------------------------
def home(request):
    if request.user.is_authenticated:
        return redirect("practice_page")
    return redirect("login")


@csrf_protect
def register(request):
    if request.user.is_authenticated:
        return redirect("practice_page")

    if request.method == "POST":
        form = StudentSignupForm(request.POST)
        if form.is_valid():
            user = form.save()  # form.save() handles email/first/last + DOB on profile
            auth_login(request, user)
            return redirect("practice_page")
    else:
        form = StudentSignupForm()

    return render(request, "register.html", {"form": form})


# --- tiny API ----------------------------------------------------------------
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def ping(request):
    return Response({"ok": True})


# Students create attempts for themselves (must be signed in)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def create_attempt(request):
    title = request.data.get("assignment_title") or "Practice"
    attempt = Attempt.objects.create(student=request.user, assignment_title=title)
    return Response({"attempt_id": attempt.id}, status=status.HTTP_201_CREATED)


# Submit an answer: owner of the attempt OR a teacher
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def submit_attempt_item(request, attempt_id: int):
    attempt = get_object_or_404(Attempt, id=attempt_id)
    if attempt.student_id != request.user.id and not user_is_teacher(request.user):
        return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    q = get_object_or_404(Question, id=request.data.get("question_id"))
    submitted = request.data.get("answer") or {}
    is_correct = evaluate_answer(q, submitted)

    diag = []
    if q.type == "mcq" and q.diagnostic_keys:
        key = submitted.get("choice")
        if key in q.diagnostic_keys:
            diag = [q.diagnostic_keys[key]]

    item = AttemptItem.objects.create(
        attempt=attempt,
        student=attempt.student,
        question=q,
        question_version=q.version,
        submitted=submitted,
        is_correct=is_correct,
        tags_snapshot=list(q.tags.values_list("name", flat=True)),
        diag_snapshot=diag,
    )
    return Response({"is_correct": is_correct, "attempt_item_id": item.id}, status=status.HTTP_201_CREATED)


# Only me or a teacher can view my still-missed
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def latest_incorrects(request, student_id: int):
    if student_id != request.user.id and not user_is_teacher(request.user):
        return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    items = (
        AttemptItem.objects
        .filter(student_id=student_id)
        .select_related("question")
        .order_by("question_id", "created_at")  # we'll keep the last seen per question
    )

    latest_by_q = OrderedDict()
    for it in items:
        latest_by_q[it.question_id] = it

    wrong = []
    for it in latest_by_q.values():
        if not it.is_correct:
            q = it.question
            wrong.append({
                "id": q.id,
                "type": q.type,
                "stem_md": q.stem_md or "",
                "choices": q.choices or {},
                "version": q.version,
                "tags": list(q.tags.values_list("name", flat=True)),
            })

    return Response({"count": len(wrong), "questions": wrong})



def _descendant_tags_by_name(name: str):
    """Return Tag queryset including the tag named `name` and all its descendants."""
    try:
        root = Tag.objects.get(name__iexact=name)
    except Tag.DoesNotExist:
        return Tag.objects.none()

    ids = [root.id]
    stack = [root]
    while stack:
        t = stack.pop()
        children = list(Tag.objects.filter(parent=t))
        ids.extend(ch.id for ch in children)
        stack.extend(children)
    return Tag.objects.filter(id__in=ids)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def get_questions(request):
    try:
        tag = request.query_params.get("tag", "").strip()
        try:
            limit = int(request.query_params.get("limit", 1))
        except ValueError:
            limit = 1

        # --- NEW: exclude list from client (comma-separated IDs) -------------
        exclude_raw = (request.query_params.get("exclude") or "").strip()
        exclude_ids = []
        if exclude_raw:
            parts = [p.strip() for p in exclude_raw.split(",") if p.strip()]
            for p in parts[:2000]:     # cap to keep the SQL IN() sane
                try:
                    exclude_ids.append(int(p))
                except ValueError:
                    pass

        qs = Question.objects.all()

        # Student subjects (optional restriction)
        sp = getattr(request.user, "studentprofile", None)
        subjects_qs = sp.subjects.all() if sp and sp.subjects.exists() else None

        if tag:
            allowed_tags = _descendant_tags_by_name(tag)
            if subjects_qs is not None:
                # intersect with student's allowed subjects (parent or child)
                allowed_ids = list(allowed_tags.values_list("id", flat=True))
                subject_ids = list(subjects_qs.values_list("id", flat=True))
                if not set(allowed_ids) & set(subject_ids):
                    return Response({"count": 0, "questions": []})
            qs = qs.filter(tags__in=allowed_tags).distinct()
        else:
            if subjects_qs is not None:
                qs = qs.filter(tags__in=subjects_qs).distinct()

        # --- NEW: apply exclude BEFORE ordering/slicing -----------------------
        if exclude_ids:
            qs = qs.exclude(id__in=exclude_ids)

        # Random pick from remaining
        qs = qs.order_by(Random())[:max(1, limit)]

        def _norm(s: str) -> str:
            if not s: return ""
            s = re.sub(r'<br\s*/?>',' ', s, flags=re.I)
            s = re.sub(r'\\\\(?!\[|\(|\{)',' ', s)
            s = re.sub(r'\s*\n+\s*',' ', s)
            s = re.sub(r'\s{2,}',' ', s)
            return s.strip()

        out = []
        for q in qs:
            out.append({
                "id": q.id,
                "type": q.type,
                "stem_md": q.stem_md or "",   # keep raw; frontend handles TeX/HTML
                "choices": (q.choices or {}),
                "version": q.version,
                "tags": list(q.tags.values_list("name", flat=True)),
            })

        return Response({"count": len(out), "questions": out})
    except Exception as e:
        return Response({"error": str(e), "trace": traceback.format_exc()}, status=500)


# --- pages (templates) -------------------------------------------------------
@login_required
def practice_page(request):
    get_token(request)  # ensure CSRF cookie exists
    sid = getattr(getattr(request.user, "studentprofile", None), "sid", None) or f"S{request.user.id:06d}"
    return render(request, "practice/practice.html", {
        "me_id": request.user.id,
        "me_sid": sid,
        "me_name": request.user.username,
    })


@login_required
def teacher_page(request):
    get_token(request)
    return render(request, "teacher.html")


# --- PDF helpers + views -----------------------------------------------------
def _latest_wrong_questions(student_id: int):
    items = (
        AttemptItem.objects
        .filter(student_id=student_id)
        .select_related("question")
        .order_by("question_id", "created_at")
    )
    latest = OrderedDict()
    for it in items:
        latest[it.question_id] = it
    return [it.question for it in latest.values() if not it.is_correct]


def _make_pdf(student_id: int, questions):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    W, H = letter

    x = 1 * inch
    y = H - 1 * inch

    c.setFont("Helvetica-Bold", 14)
    c.drawString(x, y, f"Personalized Practice — Student {student_id}")
    y -= 0.4 * inch
    c.setFont("Helvetica", 11)

    if not questions:
        c.drawString(x, y, "No current still-missed questions.")
    else:
        for i, q in enumerate(questions, start=1):
            text = f"Q{i}. {q.stem_md}"
            # basic wrap
            max_chars = 95
            while len(text) > max_chars:
                c.drawString(x, y, text[:max_chars]); y -= 0.25 * inch
                text = text[max_chars:]
                if y < 1 * inch:
                    c.showPage(); y = H - 1 * inch; c.setFont("Helvetica", 11)
            c.drawString(x, y, text); y -= 0.35 * inch
            if y < 1 * inch:
                c.showPage(); y = H - 1 * inch; c.setFont("Helvetica", 11)

    c.showPage()
    c.save()
    pdf = buf.getvalue()
    buf.close()
    return pdf


# ----- TECTONIC (LaTeX) PATH -------------------------------------------------
TECTONIC_BIN = os.getenv("TECTONIC_BIN", "tectonic")

def _tectonic_path():
    """Return path to tectonic binary (project ./bin or PATH), or None."""
    from django.conf import settings
    local = os.path.join(settings.BASE_DIR, "bin", "tectonic")
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local
    return shutil.which("tectonic")


def _render_latex_pdf_from_template(template_name: str, ctx: dict) -> bytes:
    """
    Render a Django .tex template and compile it to PDF with Tectonic.
    Raises on failure. Callers should catch and fallback.
    """
    exe = _tectonic_path()
    if not exe:
        raise RuntimeError("tectonic_not_found")

    tex_source = render_to_string(template_name, ctx)

    with tempfile.TemporaryDirectory() as td:
        tex_path = os.path.join(td, "doc.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_source)

        env = os.environ.copy()
        env.setdefault("TEXMFHOME", os.path.join(td, "texmf"))

        # Prefer modern subcommand first; fall back to legacy syntax.
        # (No "-q" because your binary does not support it.)
        cmd_modern = [exe, "-X", "compile", tex_path, "--outdir", td, "--synctex=0", "--keep-logs"]
        proc = subprocess.run(
            cmd_modern, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=td, env=env
        )
        if proc.returncode != 0:
            cmd_legacy = [exe, tex_path, "--outdir", td, "--synctex=0", "--keep-logs"]
            proc2 = subprocess.run(
                cmd_legacy, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=td, env=env
            )
            if proc2.returncode != 0:
                raise RuntimeError(f"tectonic_failed\n{proc.stdout}\n{proc2.stdout}")

        pdf_path = os.path.join(td, "doc.pdf")
        with open(pdf_path, "rb") as fh:
            return fh.read()



def _build_latex_doc(student_id: int, questions) -> str:
    """Return a complete LaTeX document as a string."""
    sid = f"S{student_id:06d}"
    lines = [
        r"\documentclass[11pt]{article}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage{lmodern}",
        r"\usepackage{amsmath,amssymb}",
        r"\usepackage[margin=1in]{geometry}",
        r"\usepackage{enumitem}",
        r"\setlist[itemize]{leftmargin=1.4em}",
        r"\begin{document}",
        rf"\section*{{Personalized Practice --- {sid}}}",
        ""
    ]
    if not questions:
        lines.append("No current still-missed questions.")
    else:
        lines.append(r"\begin{enumerate}")
        for q in questions:
            # stems/choices already contain math like $...$ — we insert verbatim
            lines.append(r"\item " + (q.stem_md or ""))

            if isinstance(q.choices, dict) and q.choices:
                lines.append(r"\begin{itemize}")
                for k, v in q.choices.items():
                    lines.append(rf"\item \textbf{{({k})}} {v}")
                lines.append(r"\end{itemize}")

            lines.append(r"\vspace{0.8em}")
        lines.append(r"\end{enumerate}")
    lines.append(r"\end{document}")
    return "\n".join(lines)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def wrong_questions_pdf(request, student_id: int):
    # only owner or teacher
    if student_id != request.user.id and not user_is_teacher(request.user):
        return Response({"detail": "Forbidden"}, status=403)

    qs = _latest_wrong_questions(student_id)

    # Build context for the .tex template
    sid = getattr(getattr(request.user, "studentprofile", None), "sid", f"S{student_id:06d}")
    ctx = {
        "sid": sid,
        "questions": [{"stem_md": q.stem_md or "", "choices": (q.choices or {})} for q in qs],
    }

    try:
        # Render the LaTeX template to a full TeX document string
        tex = render_to_string("print/missed_problems.tex", ctx)
        # Compile to PDF with tectonic
        pdf_bytes = compile_tex_bytes(tex)
    except Exception as e:
        # Fallback to ReportLab simple PDF if LaTeX fails
        logger.exception("LaTeX PDF failed; falling back to ReportLab")
        pdf_bytes = _make_pdf(student_id, qs)

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="still_missed_student_{student_id}.pdf"'
    return resp




@login_required
def student_dashboard(request):
    sp = getattr(request.user, "studentprofile", None)

    # Allowed tags: student's assigned subjects, or all tags if none assigned yet
    allowed = sp.subjects.all() if sp and sp.subjects.exists() else Tag.objects.all()

    # Build groups: { parent_name: [child_name, ...] }
    groups_map = {}
    for t in allowed:
        if t.parent is None:
            groups_map.setdefault(t.name, [])
        else:
            groups_map.setdefault(t.parent.name, [])
            if t.name not in groups_map[t.parent.name]:
                groups_map[t.parent.name].append(t.name)

    # Turn into a list of {parent, children[]}, sorted
    groups = []
    for parent in sorted(groups_map.keys(), key=str.lower):
        children = sorted(groups_map[parent], key=str.lower)
        groups.append({"parent": parent, "children": children})

    return render(
        request,
        "dashboard.html",
        {"groups": groups, "me_sid": getattr(sp, "sid", "")},
    )


def _tectonic_path():
    """Return path to tectonic binary (./bin or PATH)."""
    local = os.path.join(settings.BASE_DIR, "bin", "tectonic")
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local
    return shutil.which("tectonic")

# Where to cache compiled images (put this under STATIC or MEDIA)
TEXCACHE_DIR = Path(settings.BASE_DIR) / "static" / "texcache"
TEXCACHE_DIR.mkdir(parents=True, exist_ok=True)

_STANDALONE_PREAMBLE = r"""
\documentclass[preview,border=2pt]{standalone}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb,mathtools}
\usepackage{booktabs}
\usepackage{tikz,pgfplots,tcolorbox}
\pgfplotsset{compat=1.18}
\begin{document}
%s
\end{document}
"""

# Heuristic: if the snippet uses environments that MathJax can't render, we want full LaTeX.
_NEEDS_FULL_LATEX_RE = re.compile(
    r"\\begin\{(tabular|array|align\*?|tcolorbox|tikzpicture|axis)\}|\\includegraphics|\\pgfplotstableread",
    re.I
)

@require_GET
def tex_svg(request):
    """
    Compile a LaTeX snippet to SVG (Overleaf-quality) using Tectonic + pdftocairo.
    GET params:
      - tex: URL-encoded LaTeX snippet (recommended for small snippets)
      - qid: optional, to pull Question.stem_md from DB instead
    Returns: image/svg+xml (or image/png fallback)
    """
    # --- NEW: light forbid regex (tectonic disables shell-escape already) ---
    _FORBID_RE = re.compile(r"\\(write|openout|input\s*\{[^}]*\}|usepackage\[.*?\]\{shellesc\})", re.I)

    tex = request.GET.get("tex")
    if not tex and (qid := request.GET.get("qid")):
        try:
            q = Question.objects.get(pk=int(qid))
        except (ValueError, Question.DoesNotExist):
            return HttpResponseBadRequest("bad qid")
        tex = q.stem_md or ""

    if not tex:
        return HttpResponseBadRequest("missing tex")

    # --- NEW: block a few risky primitives ---
    if _FORBID_RE.search(tex):
        return HttpResponse("forbidden_tex", status=400)

    # Hash for caching
    h = hashlib.sha1(tex.encode("utf-8")).hexdigest()
    svg_path = TEXCACHE_DIR / f"{h}.svg"
    png_path = TEXCACHE_DIR / f"{h}.png"

    # Serve cached if present (with long cache headers)
    if svg_path.exists():
        resp = FileResponse(open(svg_path, "rb"), content_type="image/svg+xml")
        resp["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp
    if png_path.exists():
        resp = FileResponse(open(png_path, "rb"), content_type="image/png")
        resp["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp

    exe = _tectonic_path()
    if not exe:
        return HttpResponse("tectonic_not_found", status=500)

    # Wrap in standalone document
    wrapper = _STANDALONE_PREAMBLE % tex

    try:
        with tempfile.TemporaryDirectory() as td:
            tex_file = Path(td) / "doc.tex"
            tex_file.write_text(wrapper, encoding="utf-8")

            env = os.environ.copy()
            env.setdefault("TEXMFHOME", str(Path(td) / "texmf"))

            # Compile to PDF with Tectonic (modern CLI first, fall back to legacy)
            cmd_modern = [exe, "-X", "compile", str(tex_file), "--outdir", td, "--synctex=0", "--keep-logs"]
            proc = subprocess.run(cmd_modern, cwd=td, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, timeout=30)
            if proc.returncode != 0:
                cmd_legacy = [exe, str(tex_file), "--outdir", td, "--synctex=0", "--keep-logs"]
                proc2 = subprocess.run(cmd_legacy, cwd=td, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, timeout=30)
                if proc2.returncode != 0:
                    return HttpResponse("tectonic_failed:\n"+proc.stdout+"\n"+proc2.stdout,
                                        status=422, content_type="text/plain")

            pdf = Path(td) / "doc.pdf"

            # Try PDF -> SVG via poppler (pdftocairo). One page expected due to standalone.
            svg_tmp = Path(td) / "doc.svg"
            rc = subprocess.run(["pdftocairo", "-svg", str(pdf), str(svg_tmp)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).returncode
            if rc == 0 and svg_tmp.exists():
                TEXCACHE_DIR.mkdir(parents=True, exist_ok=True)
                # --- NEW: atomic write to avoid race on concurrent requests ---
                tmp_out = svg_path.with_suffix(".svg.tmp")
                tmp_out.write_bytes(svg_tmp.read_bytes())
                tmp_out.replace(svg_path)
                resp = FileResponse(open(svg_path, "rb"), content_type="image/svg+xml")
                resp["Cache-Control"] = "public, max-age=31536000, immutable"
                return resp

            # Fallback to PNG (pdftoppm)
            png_tmp = Path(td) / "doc"
            rc = subprocess.run(["pdftoppm", "-png", "-singlefile", "-rx", "200", "-ry", "200",
                                 str(pdf), str(png_tmp)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).returncode
            png_file = png_tmp.with_suffix(".png")
            if rc == 0 and png_file.exists():
                TEXCACHE_DIR.mkdir(parents=True, exist_ok=True)
                tmp_out = png_path.with_suffix(".png.tmp")
                tmp_out.write_bytes(png_file.read_bytes())
                tmp_out.replace(png_path)
                resp = FileResponse(open(png_path, "rb"), content_type="image/png")
                resp["Cache-Control"] = "public, max-age=31536000, immutable"
                return resp

            return HttpResponse("convert_failed", status=500, content_type="text/plain")
    except subprocess.TimeoutExpired:
        return HttpResponse("latex_timeout", status=504, content_type="text/plain")

def question_asset(request, pk: int, fmt: str = "svg"):
    q = Question.objects.filter(pk=pk).first()
    if not q or not q.asset_relpath:
        raise Http404("No asset")
    # only serve correct format
    if (q.asset_format or "svg") != fmt:
        raise Http404("Format mismatch")
    abs_path = os.path.join(settings.ASSET_ROOT, q.asset_relpath)
    if not os.path.isfile(abs_path):
        raise Http404("Asset missing")
    ctype = "image/svg+xml" if fmt == "svg" else "image/png"
    return FileResponse(open(abs_path, "rb"), content_type=ctype)

@csrf_exempt
@require_POST
def log_attempt_view(request, attempt_id):
    """
    Records a view slice (in ms) for a question within an attempt.
    Safe: if AttemptView model isn't present, returns ok without saving.
    """
    try:
        data = json.loads(request.body or "{}")
        question_id = int(data.get("question_id") or 0)
        view_ms = max(0, int(data.get("view_ms") or 0))
    except Exception:
        return JsonResponse({"ok": False, "error": "bad-json"}, status=400)

    # If you don't want persistence yet, this already returns 200 OK.
    # If the model exists, we'll try to save; if it doesn't, we just no-op.
    try:
        from .models import AttemptView, Attempt, Question  # may not exist yet
        att = Attempt.objects.get(id=attempt_id)
        q   = Question.objects.get(id=question_id)
        AttemptView.objects.create(attempt=att, question=q, view_ms=view_ms)
        return JsonResponse({"ok": True, "saved": True})
    except Exception as e:
        # Swallow missing model / lookup issues so frontend never breaks
        return JsonResponse({"ok": True, "saved": False, "note": str(e)})
    

@login_required
def student_stats_page(request):
    """Renders the simple stats UI; data is fetched via /api/stats/me/."""
    return render(request, "practice/statistics.html")

@login_required
def student_stats_api(request):
    user = request.user

    # All attempts by this student
    attempt_ids = list(
        Attempt.objects.filter(student=user).values_list("id", flat=True)
    )

    # Distinct questions the student VIEWED (denominator),
    # and total ms per (attempt, question)
    # NOTE: multiple logs merge into one total per question
    viewed_pairs_qs = (
        AttemptView.objects.filter(attempt_id__in=attempt_ids)
        .values("attempt_id", "question_id")
        .annotate(total_ms=Sum("view_ms"))
    )
    viewed_pairs = [(r["attempt_id"], r["question_id"]) for r in viewed_pairs_qs]
    viewed_count = len(viewed_pairs)

    # Distinct (attempt, question) that were answered correctly at least once
    correct_pairs = set(
        AttemptItem.objects.filter(attempt_id__in=attempt_ids, is_correct=True)
        .values_list("attempt_id", "question_id")
        .distinct()
    )

    # Numerator: of the viewed questions, how many ended up correct?
    correct_viewed_count = sum(1 for pair in viewed_pairs if pair in correct_pairs)

    accuracy = (correct_viewed_count / viewed_count) if viewed_count else 0.0

    # Average view time per question (sum logs per question, then average)
    avg_view_ms = 0
    if viewed_pairs_qs.exists():
        avg_view_ms = viewed_pairs_qs.aggregate(avg=Avg("total_ms"))["avg"] or 0

    data = {
        "viewed_count": viewed_count,
        "correct_viewed_count": correct_viewed_count,
        "accuracy": accuracy,                # 0–1
        "accuracy_pct": round(accuracy * 100, 1),
        "avg_view_ms": round(avg_view_ms),   # integer ms
        "avg_view_s": round(avg_view_ms / 1000.0, 2),
    }
    return JsonResponse(data)


@csrf_exempt                 # allow sendBeacon() without CSRF header
@login_required
def attempt_view_log(request, attempt_id):
    """POST {question_id, view_ms} → create AttemptView row for this user/attempt."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        qid = int(payload.get("question_id"))
        ms  = max(0, int(payload.get("view_ms", 0)))
    except Exception:
        return HttpResponseBadRequest("bad json")

    # Verify the attempt belongs to the current user
    try:
        attempt = Attempt.objects.get(id=attempt_id, student=request.user)
    except Attempt.DoesNotExist:
        return JsonResponse({"ok": False, "error": "attempt not found"}, status=404)

    AttemptView.objects.create(
        attempt=attempt,
        question_id=qid,
        view_ms=ms,
        created_at=timezone.now(),
    )
    return JsonResponse({"ok": True, "saved": True})
