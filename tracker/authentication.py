"""Database-backed login challenges, independent of per-worker caches."""

import secrets
from datetime import timedelta
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.crypto import salted_hmac, constant_time_compare
from django.contrib.auth.hashers import make_password
from .models import CustomUser, LoginChallenge, RequestBudget


def digest(value):
    return salted_hmac("cp-tracker-login", value, algorithm="sha256").hexdigest()


def reserve_budget(scope, limit, seconds=3600):
    window = int(timezone.now().timestamp()) // seconds
    key = digest(scope)
    RequestBudget.objects.get_or_create(key=key, window=window)
    return (
        RequestBudget.objects.filter(key=key, window=window, used__lt=limit).update(
            used=F("used") + 1
        )
        == 1
    )


def issue_challenge(email, ip):
    if not reserve_budget("login-ip:" + ip, 20) or not reserve_budget(
        "login-email:" + email, 5
    ):
        return None
    matches = list(CustomUser.objects.filter(email__iexact=email)[:2])
    if len(matches) > 1:
        return None  # Legacy case-colliding accounts require operator reconciliation.
    user = (
        matches[0]
        if matches
        else CustomUser.objects.get_or_create(
            email=email, defaults={"password": make_password(None)}
        )[0]
    )
    now = timezone.now()
    if user.activation_locked and not user.is_active:
        return None
    # Conditional update is shared across workers; concurrent requests cannot bypass cooldown.
    allowed = (
        CustomUser.objects.filter(pk=user.pk)
        .filter(
            Q(otp_last_sent_at__isnull=True)
            | Q(otp_last_sent_at__lte=now - timedelta(seconds=60))
        )
        .update(otp_last_sent_at=now)
    )
    if not allowed:
        return None
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = LoginChallenge(user=user, expires_at=now + timedelta(minutes=5))
    challenge.code_hash = digest(challenge.pk + ":" + code)
    with transaction.atomic():
        LoginChallenge.objects.filter(user=user, consumed_at__isnull=True).update(
            consumed_at=now
        )
        challenge.save()
    return challenge, code


def reserve_cooldown(scope, seconds):
    key = digest("cooldown:" + scope)
    now_ms = int(timezone.now().timestamp() * 1000)
    RequestBudget.objects.get_or_create(key=key, window=0)
    return (
        RequestBudget.objects.filter(key=key, window=0, used__lte=now_ms).update(
            used=now_ms + int(seconds * 1000)
        )
        == 1
    )


def consume_challenge(identifier, code):
    now = timezone.now()
    with transaction.atomic():
        # This write locks the row before reading on both supported databases.
        changed = LoginChallenge.objects.filter(
            pk=identifier, consumed_at__isnull=True, expires_at__gt=now, attempts__lt=5
        ).update(attempts=F("attempts") + 1)
        if not changed:
            return None
        challenge = LoginChallenge.objects.select_related("user").get(pk=identifier)
        matches = constant_time_compare(
            challenge.code_hash, digest(identifier + ":" + code)
        )
        if matches or challenge.attempts >= 5:
            LoginChallenge.objects.filter(pk=identifier).update(
                consumed_at=now, code_hash=""
            )
        if not matches:
            return None
        user = challenge.user
        if user.activation_locked and not user.is_active:
            return None
        if not user.activation_locked:
            user.activation_locked = True
            user.is_active = True
            user.save(update_fields=["activation_locked", "is_active"])
        return user
