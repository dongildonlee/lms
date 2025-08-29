# practice/views_stats.py
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Sum
from .models import AttemptView, AttemptItem, Question, Tag

@login_required
def stats_me(request):
    user = request.user

    # 1) Collect total view time (ms) per question
    q_views = (AttemptView.objects
               .filter(attempt__student=user)
               .values('question_id')
               .annotate(total_ms=Sum('view_ms')))

    viewed_count = q_views.count()
    q_ids = [row['question_id'] for row in q_views]
    total_ms = sum((row['total_ms'] or 0) for row in q_views)

    # Convert to seconds for the API (fixes the ms→s display bug)
    avg_view_s = round((total_ms / viewed_count) / 1000.0, 2) if viewed_count else 0.0

    # 2) Latest correctness per question (most recent AttemptItem)
    items = (AttemptItem.objects
             .filter(attempt__student=user, question_id__in=q_ids)
             .order_by('question_id', '-created_at'))

    latest_correct_by_q = {}
    for it in items:
        qid = it.question_id
        if qid not in latest_correct_by_q:
            latest_correct_by_q[qid] = bool(getattr(it, 'is_correct', False))

    correct = sum(1 for qid in q_ids if latest_correct_by_q.get(qid, False))
    accuracy_pct = round((correct * 100.0) / viewed_count) if viewed_count else 0

    # 3) Per-subject breakdown
    # Determine the student's "subject" tags (if they have a profile)
    sp = getattr(user, "studentprofile", None)
    subject_ids = set(sp.subjects.values_list('id', flat=True)) if sp and sp.subjects.exists() else set()

    # Prefetch tags for the viewed questions
    q_by_id = {q.id: q for q in Question.objects.filter(id__in=q_ids).prefetch_related('tags')}

    # Build: for each question, pick a primary subject tag to group by
    # Rule: if the question has any tag in student's subjects, pick the first of those.
    # Else: fall back to the first tag on the question, else bucket as "Other".
    def primary_tag_for(q: Question):
        tlist = list(q.tags.all())
        if not tlist:
            return ("_other", "Other")
        if subject_ids:
            for t in tlist:
                if t.id in subject_ids:
                    return (f"tag:{t.id}", t.name)
        # fallback to first tag
        t = tlist[0]
        return (f"tag:{t.id}", t.name)

    # Make a quick dict for view_ms per qid
    view_ms_by_q = {row['question_id']: (row['total_ms'] or 0) for row in q_views}

    # Tally per subject
    buckets = {}  # key -> {name, viewed_count, correct_count, total_ms}
    for qid in q_ids:
        q = q_by_id.get(qid)
        if not q:
            key, name = ("_other", "Other")
        else:
            key, name = primary_tag_for(q)

        b = buckets.setdefault(key, {"name": name, "viewed_count": 0, "correct_count": 0, "total_ms": 0})
        b["viewed_count"] += 1
        b["total_ms"] += view_ms_by_q.get(qid, 0)
        if latest_correct_by_q.get(qid, False):
            b["correct_count"] += 1

    # Compute per-subject derived fields
    breakdown = []
    for key, b in buckets.items():
        vc = b["viewed_count"] or 0
        cc = b["correct_count"] or 0
        tms = b["total_ms"] or 0
        breakdown.append({
            "name": b["name"],
            "viewed_count": vc,
            "correct_viewed_count": cc,
            "accuracy_pct": round((cc * 100.0) / vc) if vc else 0,
            "avg_view_s": round((tms / vc) / 1000.0, 2) if vc else 0.0,
        })

    # Sort breakdown by most viewed
    breakdown.sort(key=lambda x: (-x["viewed_count"], x["name"].lower()))

    return JsonResponse({
        "ok": True,
        "viewed_count": viewed_count,                # unique questions viewed
        "correct_viewed_count": correct,             # of those, latest answer was correct
        "accuracy_pct": accuracy_pct,                # 0–100 integer
        "avg_view_s": avg_view_s,                    # average seconds per question
        "breakdown": breakdown,                      # per-subject rows
    })

