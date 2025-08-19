from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import Classroom, Enrollment, Tag, Question, Attempt, AttemptItem, StudentProfile

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "sid", "grade")
    search_fields = ("sid", "user__username", "user__email")
    filter_horizontal = ("subjects",)  # nice dual-list UI to pick subjects
    
# Inline profile on the User page for convenience
class StudentProfileInline(admin.StackedInline):
    model = StudentProfile
    can_delete = False


class UserAdmin(BaseUserAdmin):
    inlines = [StudentProfileInline]


# Replace default User admin with one that shows the inline
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# Your app models
admin.site.register(Classroom)
admin.site.register(Enrollment)
admin.site.register(Tag)
admin.site.register(Question)
admin.site.register(Attempt)
admin.site.register(AttemptItem)


