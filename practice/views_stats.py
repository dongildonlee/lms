# practice/views_stats.py
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Sum
from .models import AttemptView, AttemptItem, Question, Tag

@login_required
def stats_me(request):
    user = request.user

    # ---- Per-question total viewing time (ms) for this user -----------------
    # { question_id: total_ms }
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
        avg_view_s = round((total_ms / viewed_count) / 1000.0, 2)  # seconds

    # ---- Correctness: only the MOST RECENT AttemptItem per question ---------
    # We pull the latest created_at per (question) and then check is_correct.
    latest_items = (
        AttemptItem.objects
        .filter(attempt__student=user, question_id__in=viewed_qids)
        .values('question_id')
        .annotate(latest_at=Max('created_at'))
    )

    latest_map = {}  # {question_id: AttemptItem}
    if latest_items:
        # build (question_id, latest_at) pairs
        pairs = [(row['question_id'], row['latest_at']) for row in latest_items]
        # fetch those exact items
        fetched = (
            AttemptItem.objects
            .filter(attempt__student=user)
            .filter(
                # match any (question_id, created_at) in pairs
                # (we do it in two steps because Django doesn't let us filter
                # by a list of tuples directly)
                # tiny helper map for lookups:
                question_id__in=[qid for qid, _ in pairs]
            )
            .order_by('question_id', '-created_at')
        )
        # Keep only the most recent per question
        seen = set()
        for it in fetched:
            if it.question_id in seen:
                continue
            # check match
            for qid, ts in pairs:
                if qid == it.question_id and it.created_at == ts:
                    latest_map[it.question_id] = it
                    seen.add(it.question_id)
                    break

    correct = sum(1 for qid, it in latest_map.items() if getattr(it, 'is_correct', False))
    accuracy_pct = round((correct * 100.0) / viewed_count) if viewed_count else 0

    # ---- Per-subject breakdown (immediate children under each root) ---------
    # For every viewed question, look at its tags; if a tag has a parent, we
    # treat that tag (child) as a "subject slice" (e.g., RV, means and SD).
    # You can tailor this if your taxonomy differs.
    q_tags = (
        Question.objects
        .filter(id__in=viewed_qids)
        .prefetch_related('tags')
        .only('id')
    )

    # group accumulators: {tag_id: {'label', 'viewed', 'correct', 'total_ms'}}
    groups = {}

    def _touch(tag: Tag):
        d = groups.get(tag.id)
        if not d:
            groups[tag.id] = d = {
                'label': tag.name,
                'viewed': 0,
                'correct': 0,
                'total_ms': 0
            }
        return d

    for q in q_tags:
        # compute if latest answer (if any) was correct
        it = latest_map.get(q.id)
        was_correct = bool(getattr(it, 'is_correct', False))
        ms = per_q_ms.get(q.id, 0)

        for t in q.tags.all():
            # choose "child" subjects under any root (parent exists)
            if t.parent_id:
                d = _touch(t)
                d['viewed'] += 1
                d['total_ms'] += ms
                if was_correct:
                    d['correct'] += 1

    breakdown = []
    for tag_id, d in groups.items():
        if d['viewed'] <= 0:
            continue
        breakdown.append({
            "label": d['label'],
            "viewed_count": d['viewed'],
            "correct_viewed_count": d['correct'],
            "accuracy_pct": round((d['correct'] * 100.0) / d['viewed']),
            "avg_view_s": round((d['total_ms'] / d['viewed']) / 1000.0, 2),
        })

    # Sort breakdown by label for stable UI
    breakdown.sort(key=lambda x: x['label'].lower())

    return JsonResponse({
        "ok": True,
        "viewed_count": viewed_count,
        "correct_viewed_count": correct,
        "accuracy_pct": accuracy_pct,     # 0–100 integer
        "avg_view_s": avg_view_s,         # seconds (already converted)
        "breakdown": breakdown            # per-subject slices (seconds too)
    })

