from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Todo, Profile


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]


class TodoForm(forms.ModelForm):
    class Meta:
        model = Todo
        fields = ["title", "description", "completed"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "input",
                "placeholder": "What needs to be done?"
            }),
            "description": forms.Textarea(attrs={
                "class": "input",
                "rows": 3,
                "placeholder": "Add details..."
            }),
            "completed": forms.CheckboxInput(attrs={
                "class": "checkbox"
            }),
        }


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["avatar"]
        widgets = {
            "avatar": forms.FileInput(attrs={
                "class": "input",
                "accept": "image/*",
            }),
        }
