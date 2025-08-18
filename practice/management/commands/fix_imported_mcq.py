# practice/management/commands/fix_imported_mcq.py
from django.core.management.base import BaseCommand
from practice.models import Question

class Command(BaseCommand):
    help = "Set type='mcq' for any question that has choices but was imported with a non-mcq type."

    def handle(self, *args, **kwargs):
        qs = Question.objects.exclude(choices=None).exclude(choices={}).exclude(type="mcq")
        n = 0
        for q in qs:
            q.type = "mcq"
            q.save(update_fields=["type"])
            n += 1
        self.stdout.write(self.style.SUCCESS(f"Updated {n} question(s) to type='mcq'."))
