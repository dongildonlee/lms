# practice/views.py
from collections import OrderedDict
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login as auth_login
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, render, redirect
from django.middleware.csrf import get_token
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_protect

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status, permissions

import io
import traceback

from .models import Question, Attempt, AttemptItem, Tag
from .forms import StudentSignupForm
from django.db.models.functions import Random
import re

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


# --- auth pages ---------------------------------------------------------------
def home(request):
    if request.user.is_authenticated:
        return redirect("practice_page")
    return redirect("login")


@csrf_protect
# def register(request):
#     if request.user.is_authenticated:
#         return redirect("practice_page")

#     if request.method == "POST":
#         form = StudentSignupForm(request.POST)
#         if form.is_valid():
#             user = form.save(commit=False)
#             # ensure fields are saved on the built-in User:
#             user.email = form.cleaned_data["email"]
#             user.first_name = form.cleaned_data["first_name"]
#             user.last_name = form.cleaned_data["last_name"]
#             user.save()  # triggers StudentProfile signal

#             # optional: date of birth on the profile
#             dob = form.cleaned_data.get("date_of_birth")
#             if dob and hasattr(user, "studentprofile"):
#                 user.studentprofile.date_of_birth = dob
#                 user.studentprofile.save()

#             auth_login(request, user)
#             return redirect("practice_page")
#         else:
#             # print errors to the server console to debug quickly
#             from pprint import pprint
#             print("\nREGISTER ERRORS =====================")
#             pprint(form.errors.get_json_data())
#             print("=====================================\n")
#     else:
#         form = StudentSignupForm()

#     return render(request, "register.html", {"form": form})
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

def _normalize_tex(s: str) -> str:
    """Flatten TeX linebreaks/newlines to make sentences render on one line in HTML/MathJax."""
    if not s:
        return ""
    s = re.sub(r'<br\s*/?>', ' ', s, flags=re.I)      # <br> -> space
    s = re.sub(r'\\\\(?!\[|\(|\{)', ' ', s)           # TeX \\ -> space (but keep \\\[, \\\(, \\\{)
    s = re.sub(r'\s*\n+\s*', ' ', s)                  # collapse newlines
    s = re.sub(r'\s{2,}', ' ', s)                     # collapse multi-spaces
    return s.strip()

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
                    # not allowed: return no questions
                    return Response({"count": 0, "questions": []})
            qs = qs.filter(tags__in=allowed_tags).distinct()
        else:
            # No tag given: restrict to student's subjects if they have any
            if subjects_qs is not None:
                qs = qs.filter(tags__in=subjects_qs).distinct()

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
                "stem_md": _norm(q.stem_md or ""),
                "choices": {k: _norm(v) for k, v in (q.choices or {}).items()},
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
    return render(request, "practice.html", {
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

    # Correct two-value assignment:
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
            # simple wrap
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



@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def wrong_questions_pdf(request, student_id: int):
    # only the owner or a teacher can view
    if student_id != request.user.id and not user_is_teacher(request.user):
        return Response({"detail": "Forbidden"}, status=403)

    qs = _latest_wrong_questions(student_id)
    pdf_bytes = _make_pdf(student_id, qs)

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="still_missed_student_{student_id}.pdf"'
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