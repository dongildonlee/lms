# practice/views_stats.py
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Sum, Max
from .models import AttemptView, AttemptItem, Question, Tag

@login_required
def stats_me(request):
    user = request.user

    # --- 1) Per-question total viewing time (ms) -----------------------------
    q_views = (
        AttemptView.objects
        .filter(attempt__student=user)
        .values('question_id')
        .annotate(total_ms=Sum('view_ms'))
    )
    per_q_ms = {row['question_id']: (row['total_ms'] or 0) for row in q_views}
    all_qids = set(per_q_ms.keys())

    # --- 2) Restrict to child subjects under the student's subjects ----------
    sp = getattr(user, "studentprofile", None)
    subj_roots = list(sp.subjects.all()) if sp and sp.subjects.exists() else []
    if subj_roots:
        child_tags_qs = Tag.objects.filter(parent__in=subj_roots)
    else:
        # fallback: consider any tag that has a parent as a "child subject"
        child_tags_qs = Tag.objects.filter(parent__isnull=False)

    child_tag_ids = set(child_tags_qs.values_list('id', flat=True))

    # Only questions that have at least one of those child tags
    q_tags = (
        Question.objects
        .filter(id__in=all_qids, tags__in=child_tags_qs)
        .prefetch_related('tags')
        .only('id')
        .distinct()
    )

    # --- 3) Latest correctness per question (on the filtered set) -----------
    latest_items = (
        AttemptItem.objects
        .filter(attempt__student=user, question_id__in=q_tags.values_list('id', flat=True))
        .values('question_id')
        .annotate(latest_at=Max('created_at'))
    )
    latest_map = {}
    if latest_items:
        pairs = {(row['question_id'], row['latest_at']) for row in latest_items}
        fetched = (
            AttemptItem.objects
            .filter(attempt__student=user,
                    question_id__in=[qid for (qid, _) in pairs])
            .order_by('question_id', '-created_at')
        )
        seen = set()
        for it in fetched:
            if it.question_id in seen:
                continue
            if (it.question_id, it.created_at) in pairs:
                latest_map[it.question_id] = it
                seen.add(it.question_id)

    # --- 4) Build groups; count each question in at most ONE child subject ---
    groups = {}   # tag_id -> {label, viewed, correct, total_ms}
    subject_qids = set()  # for overall calc to match breakdown exactly

    def _bucket(tag: Tag):
        d = groups.get(tag.id)
        if not d:
            groups[tag.id] = d = {'label': tag.name, 'viewed': 0, 'correct': 0, 'total_ms': 0}
        return d

    for q in q_tags:
        # pick exactly one child subject for this question (first match)
        child = next((t for t in q.tags.all() if t.id in child_tag_ids), None)
        if not child:
            continue
        subject_qids.add(q.id)
        ms = per_q_ms.get(q.id, 0)
        d = _bucket(child)
        d['viewed'] += 1
        d['total_ms'] += ms
        if getattr(latest_map.get(q.id), 'is_correct', False):
            d['correct'] += 1

    # --- 5) Overall computed from the SAME subset ----------------------------
    viewed_count = len(subject_qids)
    total_ms = sum(per_q_ms.get(qid, 0) for qid in subject_qids)
    avg_view_s = round((total_ms / viewed_count) / 1000.0, 2) if viewed_count else 0.0

    correct_total = sum(1 for qid in subject_qids
                        if getattr(latest_map.get(qid), 'is_correct', False))
    accuracy_pct = round((correct_total * 100.0) / viewed_count) if viewed_count else 0

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
    breakdown.sort(key=lambda x: x['label'].lower())

    return JsonResponse({
        "ok": True,
        "viewed_count": viewed_count,
        "correct_viewed_count": correct_total,
        "accuracy_pct": accuracy_pct,
        "avg_view_s": avg_view_s,
        "breakdown": breakdown,
    })



