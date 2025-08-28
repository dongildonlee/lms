from django.contrib import admin
from .models import AttemptView

from .models import (
    Tag, StudentProfile, Classroom, Enrollment, Question, Attempt, AttemptItem
)

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "sid", "grade")
    search_fields = ("sid", "user__username", "user__email")
    filter_horizontal = ("subjects",)

@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ("name", "owner")
    search_fields = ("name", "owner__username")

@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("classroom", "student")
    search_fields = ("classroom__name", "student__username")

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "type", "version", "created_by", "created_at")
    list_filter = ("type", "tags")
    search_fields = ("stem_md",)

@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "assignment_title", "started_at", "completed_at")
    search_fields = ("student__username", "assignment_title")

@admin.register(AttemptItem)
class AttemptItemAdmin(admin.ModelAdmin):
    list_display = ("id", "attempt", "student", "question", "is_correct", "created_at")
    list_filter = ("is_correct",)

@admin.register(AttemptView)
class AttemptViewAdmin(admin.ModelAdmin):
    list_display  = ("id", "attempt", "question", "view_ms", "created_at")
    ordering      = ("-created_at",)
    list_filter   = ("created_at",)
    search_fields = (
        "attempt__id",
        "question__id",
        "attempt__student__username",
        "attempt__student__email",
    )

# (optional) show per-question view logs inside each Attempt page
class AttemptViewInline(admin.TabularInline):
    model = AttemptView
    extra = 0
    readonly_fields = ("question", "view_ms", "created_at")

@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    inlines = [AttemptViewInline]

