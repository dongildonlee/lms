from django.urls import path
from . import views
from .views_tex import tex_pdf, tex_svg   # import both if they live there

urlpatterns = [
    # Pages
    path("practice/", views.practice_page, name="practice"),
    path("dashboard/", views.student_dashboard, name="student_dashboard"),
    path("teacher/", views.teacher_page, name="teacher_page"),
    path("accounts/register/", views.register, name="register"),

    # APIs
    path("api/ping", views.ping, name="ping"),
    path("api/questions/", views.get_questions, name="get_questions"),
    path("api/attempts/", views.create_attempt, name="create_attempt"),
    path("api/attempts/<int:attempt_id>/items/", views.submit_attempt_item, name="submit_attempt_item"),
    path("api/students/<int:student_id>/wrong-questions/", views.latest_incorrects, name="latest_incorrects"),
    path("api/students/<int:student_id>/wrong-questions/pdf", views.wrong_questions_pdf, name="wrong_questions_pdf"),

    # LaTeX endpoints
    path("tex/svg/", tex_svg, name="tex_svg"),      # point to wherever it’s implemented
    path("practice/tex/pdf/", tex_pdf, name="tex_pdf"),

    # REMOVE this unless you actually have the view
    # path("assets/q/<int:pk>.<str:fmt>", views.question_asset, name="question_asset"),
]



