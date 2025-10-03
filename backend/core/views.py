# add near the top if you keep the legacy redirect view below
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden

def home_page(request):
    return render(request, "home.html")

def login_page(request):
    return render(request, "login.html")

def signup_page(request):
    return render(request, "signup.html")

@login_required
def dashboard(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("superuser only")
    return render(request, "dashboard.html")

# ✅ rename: investments_page -> crypto_page
@login_required
def crypto_page(request):
    return render(request, "crypto.html")

def stocks_page(request):
    return render(request, "stocks.html")

