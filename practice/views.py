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

from .models import Question, Attempt, AttemptItem
from .forms import StudentSignupForm


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


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def get_questions(request):
    """
    Returns {count, questions:[{id,type,stem_md,choices,version,tags:[...]}]}
    """
    try:
        tag = request.query_params.get("tag", "").strip()
        try:
            limit = int(request.query_params.get("limit", 1))
        except ValueError:
            limit = 1

        qs = Question.objects.all()
        if tag:
            qs = qs.filter(tags__name__iexact=tag)

        qs = qs.order_by("id")[:max(1, limit)]  # deterministic 1 question for POC

        out = []
        for q in qs:
            out.append({
                "id": q.id,
                "type": q.type,
                "stem_md": q.stem_md or "",
                "choices": q.choices or {},
                "version": q.version,
                "tags": list(q.tags.values_list("name", flat=True)),
            })

        return Response({"count": len(out), "questions": out})
    except Exception as e:
        return Response(
            {"error": str(e), "trace": traceback.format_exc()},
            status=500
        )


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

    