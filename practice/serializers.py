from rest_framework import serializers
from .models import Question, Attempt, AttemptItem

class QuestionSerializer(serializers.ModelSerializer):
    tags = serializers.SerializerMethodField()

    class Meta:
        model = Question
        fields = ["id", "type", "stem_md", "choices", "version", "tags"]

    def get_tags(self, obj):
        return list(obj.tags.values_list("name", flat=True))

class AttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attempt
        fields = ["id", "student", "assignment_title", "started_at", "completed_at"]

class AttemptItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttemptItem
        fields = ["id", "attempt", "student", "question", "submitted",
                  "is_correct", "tags_snapshot", "created_at"]
