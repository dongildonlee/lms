import hashlib, json
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.conf import settings
from .models import Question

def _compute_content_hash(q: Question) -> str:
    payload = {
        "stem_md": q.stem_md or "",
        "choices": q.choices or {},
        "type": q.type or "",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

@receiver(pre_save, sender=Question)
def set_content_hash(sender, instance: Question, **kwargs):
    instance.content_hash = _compute_content_hash(instance)

@receiver(post_save, sender=Question)
def flag_render_needed(sender, instance, created, **kwargs):
    """
    Compatibility guard: only run if the asset fields exist AND the feature flag is on.
    Prevents AttributeError while we haven't migrated the Question model yet.
    """
    if not getattr(settings, "ENABLE_LATEX_ASSETS", False):
        return
    needed = ("asset_hash", "content_hash", "needs_asset_render")
    if not all(hasattr(instance, n) for n in needed):
        return

    try:
        payload = (instance.stem_md or "") + "||" + json.dumps(instance.choices or {}, sort_keys=True)
        new_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        # Update hashes/flags without re-triggering expensive work
        updates = {}
        if getattr(instance, "content_hash") != new_hash:
            updates["content_hash"] = new_hash
        if getattr(instance, "asset_hash") != new_hash:
            updates["needs_asset_render"] = True
        if updates:
            Question.objects.filter(pk=instance.pk).update(**updates)
    except Exception:
        # Never block a save on import
        return
