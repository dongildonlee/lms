# lms/backend/accounts/views_auth.py
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login


@csrf_exempt
def signin(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    username = (request.POST.get("username") or "").strip()
    password = (request.POST.get("password") or "")

    if not username or not password:
        return JsonResponse({"error": "username and password are required"}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"error": "invalid credentials"}, status=400)

    login(request, user)  # creates a session cookie
    return JsonResponse({"ok": True, "username": user.username})
