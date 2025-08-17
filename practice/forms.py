# practice/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

class StudentSignupForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"autocomplete": "email"})
    )
    first_name = forms.CharField(
        required=True, max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "given-name"})
    )
    last_name = forms.CharField(
        required=True, max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "family-name"})
    )
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"})
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "username", "first_name", "last_name",
            "email", "password1", "password2", "date_of_birth"
        )

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name  = self.cleaned_data["last_name"]
        if commit:
            user.save()
            dob = self.cleaned_data.get("date_of_birth")
            if dob:
                # profile is created by your post_save signal
                user.studentprofile.date_of_birth = dob
                user.studentprofile.save(update_fields=["date_of_birth"])
        return user
