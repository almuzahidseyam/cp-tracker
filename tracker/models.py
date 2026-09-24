from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
import random
import string

class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
            
        return self.create_user(email, password, **extra_fields)

class CustomUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150, unique=True, blank=True, null=True)
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=False)  # False until OTP verification
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    # OTP tracking fields
    otp_code = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email

    def generate_otp(self):
        self.otp_code = ''.join(random.choices(string.digits, k=6))
        self.otp_created_at = timezone.now()
        self.save()
        return self.otp_code

class Platform(models.TextChoices):
    CODEFORCES = 'CF', 'Codeforces'
    CODECHEF = 'CC', 'CodeChef'
    ATCODER = 'AC', 'AtCoder'
    LEETCODE = 'LC', 'LeetCode'

class UserHandle(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='handles')
    platform = models.CharField(max_length=2, choices=Platform.choices)
    handle = models.CharField(max_length=100)
    total_solves = models.IntegerField(default=0)
    current_streak = models.IntegerField(default=0)
    max_streak = models.IntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'platform')

    def __str__(self):
        return f"{self.user.email} - {self.platform}: {self.handle}"


class Friendship(models.Model):
    follower = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='following_set')
    followed = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='follower_set')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'followed')

    def __str__(self):
        return f"{self.follower.email} follows {self.followed.email}"
