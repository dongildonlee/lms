# lms/practice/views_stats.py
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Sum, Max
from .models import AttemptView, AttemptItem, Question, Tag

@login_required
def stats_me(request):
    user = request.user

    # Per-question totals (ms)
    q_views = (
        AttemptView.objects
        .filter(attempt__student=user)
        .values('question_id')
        .annotate(total_ms=Sum('view_ms'))
    )
    per_q_ms = {row['question_id']: (row['total_ms'] or 0) for row in q_views}
    viewed_qids = list(per_q_ms.keys())

    # Latest correctness per question
    latest_rows = (
        AttemptItem.objects
        .filter(attempt__student=user, question_id__in=viewed_qids)
        .values('question_id')
        .annotate(latest_at=Max('created_at'))
    )
    latest_map = {}
    if latest_rows:
        latest_pairs = {(r['question_id'], r['latest_at']) for r in latest_rows}
        fetched = (
            AttemptItem.objects
            .filter(attempt__student=user, question_id__in=[qid for qid, _ in latest_pairs])
            .order_by('question_id', '-created_at')
        )
        seen = set()
        for it in fetched:
            if it.question_id in seen:
                continue
            if (it.question_id, it.created_at) in latest_pairs:
                latest_map[it.question_id] = it
                seen.add(it.question_id)

    # ---- Grouping (cover 100% of viewed questions) -------------------------
    groups: dict[int, dict] = {}

    def _touch(tag: Tag):
        d = groups.get(tag.id)
        if not d:
            groups[tag.id] = d = {'label': tag.name, 'viewed': 0, 'correct': 0, 'total_ms': 0}
        return d

    OTHER_KEY = -1
    def _touch_other():
        d = groups.get(OTHER_KEY)
        if not d:
            groups[OTHER_KEY] = d = {'label': 'Other', 'viewed': 0, 'correct': 0, 'total_ms': 0}
        return d

    q_tags = (
        Question.objects
        .filter(id__in=viewed_qids)
        .prefetch_related('tags')
        .only('id')
    )

    for q in q_tags:
        it = latest_map.get(q.id)
        was_correct = bool(getattr(it, 'is_correct', False))
        ms = per_q_ms.get(q.id, 0)

        # choose exactly ONE child tag if present; otherwise bucket into Other
        child_tags = [t for t in q.tags.all() if t.parent_id]
        if child_tags:
            chosen = min(child_tags, key=lambda t: t.id)  # deterministic
            d = _touch(chosen)
        else:
            d = _touch_other()

        d['viewed'] += 1
        d['total_ms'] += ms
        if was_correct:
            d['correct'] += 1

    # Compose breakdown and compute overall from the SAME pool
    breakdown = []
    for d in groups.values():
        if d['viewed'] <= 0:
            continue
        breakdown.append({
            "label": d['label'],
            "viewed_count": d['viewed'],
            "correct_viewed_count": d['correct'],
            "accuracy_pct": round((d['correct'] * 100.0) / d['viewed']),
            "avg_view_s": round((d['total_ms'] / d['viewed']) / 1000.0, 2),
        })
    breakdown.sort(key=lambda x: x['label'].lower())

    overall_viewed   = sum(b['viewed_count'] for b in breakdown)
    overall_correct  = sum(b['correct_viewed_count'] for b in breakdown)
    overall_total_ms = sum((b['avg_view_s'] * 1000.0) * b['viewed_count'] for b in breakdown)

    if overall_viewed:
        accuracy_pct = round((overall_correct * 100.0) / overall_viewed)
        avg_view_s   = round((overall_total_ms / overall_viewed) / 1000.0, 2)
    else:
        accuracy_pct = 0
        avg_view_s   = 0.0

    return JsonResponse({
        "ok": True,
        "viewed_count": overall_viewed,
        "correct_viewed_count": overall_correct,
        "accuracy_pct": accuracy_pct,
        "avg_view_s": avg_view_s,
        "breakdown": breakdown,
    })






