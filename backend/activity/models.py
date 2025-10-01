from django.db import models
from django.contrib.auth.models import User

class LoginEvent(models.Model):
    ACTIONS = [('login', 'Login'), ('logout', 'Logout')]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='login_events')
    action = models.CharField(max_length=10, choices=ACTIONS)
    at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} {self.action} @ {self.at:%Y-%m-%d %H:%M:%S}"
