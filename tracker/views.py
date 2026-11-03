from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import UserHandle, Platform, RecentSubmission, CustomUser, Friendship
from .services import (
    update_user_handle_stats,
    fetch_handle_stats,
    apply_handle_stats,
)
from django.db.models import Sum, Q
import hmac
from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import transaction
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from .authentication import issue_challenge, consume_challenge, reserve_budget
from .models import LoginChallenge
import re


@login_required
def dashboard(request):
    handles = list(UserHandle.objects.filter(user=request.user))

    # Render saved snapshots; visiting the dashboard never starts upstream API work.
    for handle in handles:
        if handle.platform == "CF":
            handle.cf_rating = handle.rating or 0
            handle.cf_rank = handle.rank or "Unrated / unavailable"
        elif handle.platform == "LC":
            handle.lc_rating = handle.rating or 0
            handle.lc_rank = handle.rank or "Unrated / unavailable"

    total_solves = sum(h.total_solves for h in handles)

    context = {
        "handles": handles,
        "total_solves": total_solves,
    }

    recent_submissions = (
        RecentSubmission.objects.filter(handle__user=request.user)
        .select_related("handle")
        .order_by("-timestamp")[:20]
    )
    context["recent_submissions"] = recent_submissions

    return render(request, "tracker/dashboard.html", context)


@login_required
def settings_view(request):
    if request.method == "POST":
        platform = request.POST.get("platform", "")
        handle = request.POST.get("handle", "").strip()
        if platform not in Platform.values or not re.fullmatch(
            r"[A-Za-z0-9_.-]{1,50}", handle
        ):
            messages.error(
                request,
                "Choose a supported platform and a valid handle (letters, digits, underscore, dot or hyphen).",
            )
            return redirect("settings")
        if not reserve_budget("handle-update:" + str(request.user.pk), 10):
            messages.error(request, "Too many handle updates. Try again later.")
            return redirect("settings")
        stats = fetch_handle_stats(platform, handle)
        if stats is None:
            messages.error(
                request,
                "The platform could not confirm this handle. Your previous handle and statistics were kept.",
            )
            return redirect("settings")
        with transaction.atomic():
            # Serialize same-account updates after the network fetch, not while waiting on it.
            CustomUser.objects.select_for_update().get(pk=request.user.pk)
            obj, _ = UserHandle.objects.get_or_create(
                user=request.user, platform=platform, defaults={"handle": handle}
            )
            obj.handle = handle
            apply_handle_stats(obj, stats)
        messages.success(
            request,
            "Handle and statistics updated. This checks a public profile, not ownership of that external account.",
        )
        return redirect("dashboard")
    return render(request, "tracker/settings.html")


@login_required
def refresh_stats(request):
    if request.method == "POST":
        handles = list(UserHandle.objects.filter(user=request.user))
        if not reserve_budget("refresh:" + str(request.user.pk), 5):
            messages.error(request, "Refresh limit reached. Try again later.")
            return redirect("dashboard")
        success_count = sum(
            bool(update_user_handle_stats(handle)) for handle in handles
        )
        messages.info(
            request,
            f"Updated {success_count} of {len(handles)} handles. Unavailable sources keep their previous statistics.",
        )
    return redirect("dashboard")


from django.contrib.auth import login, logout
from django.core.mail import send_mail


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        try:
            validate_email(email)
            if len(email) > 254:
                raise ValidationError("Too long")
        except ValidationError:
            messages.error(request, "Enter a valid email address.")
            return render(request, "tracker/login.html", status=400)
        if not settings.EMAIL_LOGIN_ENABLED:
            messages.error(
                request, "Email login is not configured. Contact the site operator."
            )
            return render(request, "tracker/login.html", status=503)
        issued = issue_challenge(email, request.META.get("REMOTE_ADDR", "unknown"))
        if issued is None:
            messages.error(
                request,
                "A code cannot be sent right now. Wait before requesting another, or contact the operator if your account is disabled.",
            )
            return render(request, "tracker/login.html", status=429)
        challenge, code = issued
        try:
            delivered = send_mail(
                "Your CP Tracker login code",
                f"Your code is {code}. It expires in 5 minutes and can be used once. If you did not request it, ignore this email.",
                settings.DEFAULT_FROM_EMAIL,
                [challenge.user.email],
                fail_silently=False,
            )
            if delivered != 1:
                raise RuntimeError("Delivery unconfirmed")
        except Exception:
            LoginChallenge.objects.filter(pk=challenge.pk).update(
                consumed_at=timezone.now(), code_hash=""
            )
            request.session.pop("login_challenge", None)
            messages.error(
                request, "The email could not be sent. Please try again later."
            )
            return render(request, "tracker/login.html", status=503)
        request.session["login_challenge"] = challenge.pk
        request.session["login_email"] = challenge.user.email
        return redirect("verify_otp")
    return render(request, "tracker/login.html")


@require_http_methods(["GET", "POST"])
def verify_otp_view(request):
    identifier = request.session.get("login_challenge")
    if not identifier:
        return redirect("login")
    if request.method == "POST":
        user = consume_challenge(identifier, request.POST.get("otp", "").strip()[:64])
        if user:
            request.session.pop("login_challenge", None)
            request.session.pop("login_email", None)
            login(request, user)
            messages.success(request, "Signed in successfully.")
            return redirect("dashboard")
        messages.error(
            request,
            "The code is incorrect, expired or used. A code allows at most five attempts.",
        )
        if not LoginChallenge.objects.filter(
            pk=identifier, consumed_at__isnull=True, expires_at__gt=timezone.now()
        ).exists():
            request.session.pop("login_challenge", None)
            request.session.pop("login_email", None)
            return redirect("login")
    return render(
        request,
        "tracker/verify_otp.html",
        {"email": request.session.get("login_email", "")},
    )


def logout_view(request):
    if request.method == "POST":
        logout(request)
    return redirect("login")


@login_required
def leaderboard_view(request):
    search_query = request.GET.get("q", "")
    users = CustomUser.objects.filter(is_active=True)

    if search_query:
        users = users.filter(email__iexact=search_query.strip()).exclude(
            id=request.user.id
        )[:20]
        search_results = []
        following_ids = set(
            request.user.following_set.values_list("followed_id", flat=True)
        )
        for u in users:
            search_results.append({"user": u, "is_following": u.id in following_ids})
    else:
        search_results = None

    # Fix N+1 Query Problem: single optimized SQL query to get followed users + self and sum their handles
    leaderboard_users = (
        CustomUser.objects.filter(
            Q(id__in=request.user.following_set.values("followed_id"))
            | Q(id=request.user.id)
        )
        .annotate(total_solves_sum=Sum("handles__total_solves"))
        .distinct()
    )

    leaderboard_data = []
    for u in leaderboard_users:
        leaderboard_data.append({"user": u, "total_solves": u.total_solves_sum or 0})

    # Sort by total_solves descending
    leaderboard_data.sort(key=lambda x: x["total_solves"], reverse=True)

    return render(
        request,
        "tracker/leaderboard.html",
        {
            "leaderboard_data": leaderboard_data,
            "search_results": search_results,
            "search_query": search_query,
        },
    )


@login_required
def toggle_friend(request, user_id):
    if request.method == "POST":
        try:
            target_user = CustomUser.objects.get(id=user_id)
            if target_user != request.user:
                friendship, created = Friendship.objects.get_or_create(
                    follower=request.user, followed=target_user
                )
                if not created:
                    friendship.delete()
                    messages.success(
                        request, f"Removed {target_user.email} from your leaderboard."
                    )
                else:
                    messages.success(
                        request, f"Added {target_user.email} to your leaderboard!"
                    )
        except CustomUser.DoesNotExist:
            messages.error(request, "User not found.")
    return redirect("leaderboard")


@login_required
def delete_handle(request, handle_id):
    if request.method == "POST":
        try:
            handle = UserHandle.objects.get(id=handle_id, user=request.user)
            platform = handle.get_platform_display()
            handle.delete()
            messages.success(request, f"Successfully removed {platform} handle.")
        except UserHandle.DoesNotExist:
            messages.error(request, "Handle not found.")
    return redirect("dashboard")


from django.http import JsonResponse


@csrf_exempt
@require_http_methods(["GET", "POST"])
def cron_refresh(request):
    expected = settings.CRON_SECRET
    supplied = request.headers.get("Authorization", "")
    if len(expected) < 32 or not expected.isascii():
        return JsonResponse(
            {"error": "Scheduled refresh is not configured."}, status=503
        )
    if not supplied.isascii() or not hmac.compare_digest(
        supplied, "Bearer " + expected
    ):
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        after = int(request.GET.get("after", "0"))
        if after < 0:
            raise ValueError()
    except ValueError:
        return JsonResponse({"error": "Invalid cursor."}, status=400)
    if not reserve_budget("cron-batch", 1, 60):
        return JsonResponse(
            {"error": "Wait before starting another refresh batch."}, status=429
        )
    handles = list(UserHandle.objects.filter(pk__gt=after).order_by("pk")[:20])
    # Sequential writes work on SQLite and avoid unbounded per-request threads.
    successes = sum(bool(update_user_handle_stats(handle)) for handle in handles)
    next_cursor = (
        handles[-1].pk
        if handles and UserHandle.objects.filter(pk__gt=handles[-1].pk).exists()
        else None
    )
    return JsonResponse(
        {
            "refreshed_count": successes,
            "total_handles": len(handles),
            "next_cursor": next_cursor,
        }
    )
