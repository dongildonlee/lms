from django.urls import path
from . import views

urlpatterns = [
    # API: health & questions
    path("api/ping", views.ping, name="ping"),
    path("api/questions/", views.get_questions, name="get_questions"),

    # API: attempts
    path("api/attempts/", views.create_attempt, name="create_attempt"),
    path("api/attempts/<int:attempt_id>/items/", views.submit_attempt_item, name="submit_attempt_item"),

    # API: student reports
    path("api/students/<int:student_id>/wrong-questions/", views.latest_incorrects, name="latest_incorrects"),
    path("api/students/<int:student_id>/wrong-questions/pdf", views.wrong_questions_pdf, name="wrong_questions_pdf"),

    # Debug PDFs
    #path("api/test-pdf", views.test_pdf, name="test_pdf"),
    #path("api/test-pdf-plain", views.test_pdf_plain, name="test_pdf_plain"),

    # Pages
    path("practice/", views.practice_page, name="practice_page"),
    path("teacher/", views.teacher_page, name="teacher_page"),

    # Signup page
    path("accounts/register/", views.register, name="register"),
]


