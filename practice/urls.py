# practice/urls.py
from django.urls import path
from . import views
from .views_tex import tex_pdf
from .views_stats import stats_me   # <-- use the stats view you showed

urlpatterns = [
    # Pages
    path("practice/", views.practice_page, name="practice"),
    path("dashboard/", views.student_dashboard, name="student_dashboard"),
    path("teacher/", views.teacher_page, name="teacher_page"),
    path("accounts/register/", views.register, name="register"),
    path("statistics/", views.student_stats_page, name="student_stats_page"),

    # APIs
    path("api/ping", views.ping, name="ping"),
    path("api/questions/", views.get_questions, name="get_questions"),
    path("api/attempts/", views.create_attempt, name="create_attempt"),
    path("api/attempts/<int:attempt_id>/items/", views.submit_attempt_item, name="submit_attempt_item"),
    path("api/attempts/<int:attempt_id>/views/", views.attempt_view_log, name="attempt_view_log"),  # <-- one definition only

    path("api/students/<int:student_id>/wrong-questions/", views.latest_incorrects, name="latest_incorrects"),
    path("api/students/<int:student_id>/wrong-questions/pdf", views.wrong_questions_pdf, name="wrong_questions_pdf"),

    # LaTeX compile endpoint (PDF only)
    path("practice/tex/pdf/", tex_pdf, name="tex_pdf"),

    # Stats API (single, correct one)
    path("api/stats/me/", stats_me, name="stats_me"),
]





