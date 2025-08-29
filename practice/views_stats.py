# practice/views_stats.py
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Sum
from .models import AttemptView, AttemptItem, Question, Tag

@login_required
def stats_me(request):
    user = request.user

    # ---- Per-question total viewing time (ms) for this user -----------------
    q_views = (
        AttemptView.objects
        .filter(attempt__student=user)
        .values('question_id')
        .annotate(total_ms=Sum('view_ms'))
    )
    per_q_ms = {row['question_id']: (row['total_ms'] or 0) for row in q_views}
    viewed_qids = list(per_q_ms.keys())
    viewed_count = len(viewed_qids)

    # Average seconds per unique question
    avg_view_s = 0.0
    if viewed_count:
        total_ms = sum(per_q_ms.values())
        avg_view_s = round((total_ms / viewed_count) / 1000.0, 2)  # convert ms→s

    # ---- Correctness: MOST RECENT AttemptItem per question ------------------
    items = (
        AttemptItem.objects
        .filter(attempt__student=user, question_id__in=viewed_qids)
        .order_by('question_id', '-created_at')
        .values('question_id', 'is_correct')
    )
    latest_map = {}  # question_id -> bool (most recent is_correct)
    for it in items:
        qid = it['question_id']
        if qid not in latest_map:            # first seen per question is newest
            latest_map[qid] = bool(it['is_correct'])

    correct = sum(1 for ok in latest_map.values() if ok)
    accuracy_pct = round((correct * 100.0) / viewed_count) if viewed_count else 0

    # ---- Per-subject breakdown (use child tags as slices) -------------------
    q_tags = (
        Question.objects
        .filter(id__in=viewed_qids)
        .prefetch_related('tags')
        .only('id')
    )

    groups = {}  # tag_id -> {'label','viewed','correct','total_ms'}

    def _touch(tag: Tag):
        if tag.id not in groups:
            groups[tag.id] = {'label': tag.name, 'viewed': 0, 'correct': 0, 'total_ms': 0}
        return groups[tag.id]

    for q in q_tags:
        was_correct = bool(latest_map.get(q.id, False))
        ms = per_q_ms.get(q.id, 0)
        for t in q.tags.all():
            if t.parent_id:                   # treat child tags as subjects
                d = _touch(t)
                d['viewed'] += 1
                d['total_ms'] += ms
                if was_correct:
                    d['correct'] += 1

    breakdown = []
    for d in groups.values():
        if d['viewed'] <= 0:
            continue
        breakdown.append({
            "label": d['label'],
            "viewed_count": d['viewed'],
            "correct_viewed_count": d['correct'],
            "accuracy_pct": round((d['correct'] * 100.0) / d['viewed']),
            "avg_view_s": round((d['total_ms'] / d['viewed']) / 1000.0, 2),  # ms→s
        })
    breakdown.sort(key=lambda x: x['label'].lower())

    return JsonResponse({
        "ok": True,
        "viewed_count": viewed_count,
        "correct_viewed_count": correct,
        "accuracy_pct": accuracy_pct,
        "avg_view_s": avg_view_s,
        "breakdown": breakdown,
    })


