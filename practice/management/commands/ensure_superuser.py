from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
import os

class Command(BaseCommand):
    help = "Create a superuser from env if none exists."

    def handle(self, *args, **kwargs):
        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write("Superuser exists; skipping.")
            return
        u = os.getenv("DJANGO_SUPERUSER_USERNAME", "admin")
        e = os.getenv("DJANGO_SUPERUSER_EMAIL", "admin@example.com")
        p = os.getenv("DJANGO_SUPERUSER_PASSWORD")
        if not p:
            self.stderr.write("DJANGO_SUPERUSER_PASSWORD not set; skipping.")
            return
        User.objects.create_superuser(username=u, email=e, password=p)
        self.stdout.write(f"Created superuser '{u}'.")
