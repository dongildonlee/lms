from django.urls import path
from . import views
from .views_tex import tex_pdf  # only pdf
from .views import log_attempt_view
from . import views_stats

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
    path("api/students/<int:student_id>/wrong-questions/", views.latest_incorrects, name="latest_incorrects"),
    path("api/students/<int:student_id>/wrong-questions/pdf", views.wrong_questions_pdf, name="wrong_questions_pdf"),
    path("api/attempts/<int:attempt_id>/views/", log_attempt_view, name="attempt_view_log"),

    # LaTeX compile endpoint (PDF only)
    path("practice/tex/pdf/", tex_pdf, name="tex_pdf"),

    path("api/stats/me/", views.student_stats_api, name="student_stats_api"),

    # Stats API for the signed-in student    
    path("api/stats/me/", views_stats.stats_me, name="stats_me"),

    path("api/attempts/<int:attempt_id>/views/", views.attempt_view_log, name="attempt_view_log"),
]




