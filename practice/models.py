from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver

# --- LaTeX asset fields ---
content_hash      = models.CharField(max_length=64, blank=True, default="")
asset_hash        = models.CharField(max_length=64, blank=True, default="")
asset_relpath     = models.CharField(max_length=255, blank=True, default="")  # e.g. q/57/abc123.svg
asset_format      = models.CharField(max_length=8, blank=True, default="svg") # 'svg' (or 'png')
needs_asset_render = models.BooleanField(default=False)


class Classroom(models.Model):
    name = models.CharField(max_length=200)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_classes")

    def __str__(self):
        return self.name


class Enrollment(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE)
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="enrollments")

    class Meta:
        unique_together = ("classroom", "student")


class Tag(models.Model):
    name = models.CharField(max_length=120, unique=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return self.name


class Question(models.Model):
    TYPE_CHOICES = [
        ("mcq", "MCQ"),
        ("numeric", "NUMERIC"),
        ("short", "SHORT"),
        ("algebra", "ALGEBRA"),
    ]
    stem_md = models.TextField()
    type = models.CharField(max_length=12, choices=TYPE_CHOICES)
    choices = models.JSONField(null=True, blank=True)      # for MCQ
    correct = models.JSONField()                           # expected answer
    version = models.IntegerField(default=1)
    tags = models.ManyToManyField(Tag, related_name="questions")
    diagnostic_keys = models.JSONField(null=True, blank=True)  # {"A":"forgets-chain-rule"}
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Q{self.id} v{self.version}"


class Attempt(models.Model):
    assignment_title = models.CharField(max_length=200, blank=True)
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)


class AttemptItem(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="items")
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    question_version = models.IntegerField()
    submitted = models.JSONField()                         # raw answer
    is_correct = models.BooleanField()
    tags_snapshot = models.JSONField(default=list)         # list of tag names
    diag_snapshot = models.JSONField(default=list, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)


class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="studentprofile")
    sid = models.CharField(max_length=20, unique=True, blank=True)  # human-friendly Student ID, e.g. "S000123"
    date_of_birth = models.DateField(null=True, blank=True)
    grade = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    subjects = models.ManyToManyField("Tag", blank=True, related_name="students")

    def __str__(self):
        return f"{self.user.username} ({self.sid or self.user.id})"


@receiver(post_save, sender=User)
def ensure_student_profile(sender, instance, created, **kwargs):
    """
    Auto-create a StudentProfile when a User is created,
    and assign a friendly SID like 'S000123'.
    """
    if created:
        profile = StudentProfile.objects.create(user=instance)
        profile.sid = f"S{instance.id:06d}"
        profile.save()

