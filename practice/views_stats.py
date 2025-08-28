# practice/views_stats.py
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse

from .models import AttemptView, AttemptItem

@login_required
def stats_me(request):
    user = request.user

    # All view logs for this user → per-question totals
    q_views = (AttemptView.objects
               .filter(attempt__student=user)
               .values('question_id')
               .annotate(total_ms=Sum('view_ms')))

    viewed_count = q_views.count()
    q_ids = [row['question_id'] for row in q_views]
    total_ms = sum((row['total_ms'] or 0) for row in q_views)
    avg_view_s = round((total_ms / viewed_count) / 1000.0, 2) if viewed_count else 0.0

    # Correctness: take the user's MOST RECENT AttemptItem per question
    # (order by question then -created_at, keep first per question)
    items = (AttemptItem.objects
             .filter(attempt__student=user, question_id__in=q_ids)
             .order_by('question_id', '-created_at'))

    seen = set()
    correct = 0
    for it in items:
        if it.question_id in seen:
            continue
        seen.add(it.question_id)
        if getattr(it, 'is_correct', False):
            correct += 1

    accuracy_pct = round((correct * 100.0) / viewed_count) if viewed_count else 0

    return JsonResponse({
        "ok": True,
        "viewed_count": viewed_count,                # unique questions viewed
        "correct_viewed_count": correct,             # of those, latest answer was correct
        "accuracy_pct": accuracy_pct,                # 0–100 integer
        "avg_view_s": avg_view_s,                    # average seconds per question
    })
