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
def flag_render_needed(sender, instance: Question, created, **kwargs):
    # If content changed since last render, queue a re-render
    if instance.asset_hash != instance.content_hash and not instance.needs_asset_render:
        Question.objects.filter(pk=instance.pk).update(needs_asset_render=True)
