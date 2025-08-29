# practice/api.py
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Attempt, Question, AttemptViewLog  # you'll add AttemptViewLog below

@method_decorator(csrf_exempt, name="dispatch")  # allows sendBeacon without CSRF header
class AttemptViewLogAPI(APIView):
    def post(self, request, attempt_id):
        try:
            attempt = Attempt.objects.get(id=attempt_id)
        except Attempt.DoesNotExist:
            return Response({"error": "attempt not found"}, status=status.HTTP_404_NOT_FOUND)

        qid = request.data.get("question_id")
        ms  = request.data.get("view_ms")
        if qid is None or ms is None:
            return Response({"error": "question_id and view_ms required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            question = Question.objects.get(id=qid)
        except Question.DoesNotExist:
            return Response({"error": "question not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            ms = max(0, int(ms))
        except (TypeError, ValueError):
            return Response({"error": "view_ms must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        AttemptViewLog.objects.create(attempt=attempt, question=question, view_ms=ms)
        return Response({"ok": True}, status=status.HTTP_201_CREATED)
