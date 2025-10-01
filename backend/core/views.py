from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.contrib.auth.decorators import login_required


def home_page(request):
    return render(request, "home.html")


def login_page(request):
    return render(request, "login.html")


def signup_page(request):
    return render(request, "signup.html")


@login_required
def dashboard(request):
    # Only superusers can access this page
    if not request.user.is_superuser:
        return HttpResponseForbidden("superuser only")
    # will look for frontend/dashboard.html
    return render(request, "dashboard.html")


@login_required
def investments_page(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superuser only")
    return render(request, "investments.html")
