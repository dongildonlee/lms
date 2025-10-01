from django.shortcuts import render
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.contrib.auth import get_user_model
# allow POST from your static HTML
from django.views.decorators.csrf import csrf_exempt

# Create your views here.


@csrf_exempt
def signup(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST only')

    username = (request.POST.get('username') or '').strip()
    password = (request.POST.get('password') or '').strip()
    password2 = (request.POST.get('password') or '').strip()

    if not username or not password:
        return HttpResponseBadRequest("username and password are required")

    if password != password2:
        return JsonResponse({"error": "passwords do not match"}, status=400)

    User = get_user_model()

    # reject duplicates
    if User.objects.filter(username=username).exists():
        return JsonResponse({"error": "username already taken"}, status=400)

    # create the user (default Django user model)
    user = User.objects.create_user(username=username, password=password)

    return JsonResponse({"id": user.id, "username": user.username}, status=201)
