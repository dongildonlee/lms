# practice/admin.py
from django.contrib import admin
from .models import (
    Tag,
    StudentProfile,
    Classroom,
    Enrollment,
    Question,
    Attempt,
    AttemptItem,
    AttemptView,
)

# --- Tags --------------------------------------------------------------------
@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

# --- Students / Classes ------------------------------------------------------
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

# --- Questions ---------------------------------------------------------------
@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display  = ("id", "type", "version", "created_by", "created_at")
    list_filter   = ("type", "tags")
    search_fields = ("stem_md",)

# --- AttemptItem -------------------------------------------------------------
@admin.register(AttemptItem)
class AttemptItemAdmin(admin.ModelAdmin):
    list_display = ("id", "attempt", "student", "question", "is_correct", "created_at")
    list_filter  = ("is_correct",)
    search_fields = ("attempt__id", "question__id", "attempt__student__username")

# --- AttemptView (inline + standalone) --------------------------------------
class AttemptViewInline(admin.TabularInline):
    model = AttemptView
    extra = 0
    fields = ("question", "view_ms", "created_at")
    readonly_fields = ("question", "view_ms", "created_at")
    can_delete = False
    ordering = ("-created_at",)

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

# --- Attempt (single registration; includes inline) --------------------------
@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display  = ("id", "student", "assignment_title", "started_at", "completed_at")
    search_fields = ("student__username", "assignment_title")
    list_filter   = ("started_at", "completed_at")
    inlines       = [AttemptViewInline]


