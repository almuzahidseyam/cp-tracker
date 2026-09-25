from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import UserHandle, Platform, RecentSubmission, CustomUser, Friendship
from .services import update_user_handle_stats
from django.db.models import Sum, Q
import concurrent.futures

@login_required
def dashboard(request):
    handles = UserHandle.objects.filter(user=request.user)
    total_solves = sum(h.total_solves for h in handles)
    best_streak = max([h.current_streak for h in handles], default=0)
    
    context = {
        'handles': handles,
        'total_solves': total_solves,
        'best_streak': best_streak
    }
    
    recent_submissions = RecentSubmission.objects.filter(handle__user=request.user).order_by('-timestamp')[:20]
    context['recent_submissions'] = recent_submissions
    
    return render(request, 'tracker/dashboard.html', context)

@login_required
def settings_view(request):
    if request.method == 'POST':
        platform = request.POST.get('platform')
        handle = request.POST.get('handle')
        if platform and handle:
            obj, created = UserHandle.objects.update_or_create(
                user=request.user, 
                platform=platform, 
                defaults={'handle': handle}
            )
            # Fetch immediate stats upon saving
            success = update_user_handle_stats(obj)
            if success:
                messages.success(request, f"Successfully linked {platform} handle: {handle}")
            else:
                messages.warning(request, f"Linked handle {handle}, but failed to fetch stats immediately.")
            return redirect('dashboard')
            
    return render(request, 'tracker/settings.html')

@login_required
def refresh_stats(request):
    if request.method == 'POST':
        handles = list(UserHandle.objects.filter(user=request.user))
        success_count = 0
        
        # Run API fetches in parallel to avoid Vercel 10s Serverless timeout
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(update_user_handle_stats, handles)
            success_count = sum(1 for res in results if res)
            
        messages.success(request, f"Refreshed stats for {success_count} handle(s).")
    return redirect('dashboard')

from django.contrib.auth import login, logout
from django.core.mail import send_mail

def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        if email:
            user, created = CustomUser.objects.get_or_create(email=email)
            otp = user.generate_otp()
            # Send Email
            send_mail(
                'Your CP Tracker Login Code',
                f'Your verification code is: {otp}\nThis code will expire in 5 minutes.',
                'noreply@cptracker.com',
                [email],
                fail_silently=False,
            )
            request.session['login_email'] = email
            messages.info(request, f"OTP sent to {email}")
            return redirect('verify_otp')
    return render(request, 'tracker/login.html')

def verify_otp_view(request):
    email = request.session.get('login_email')
    if not email:
        return redirect('login')
        
    if request.method == 'POST':
        otp = request.POST.get('otp')
        try:
            user = CustomUser.objects.get(email=email)
            
            # Check OTP Expiry (5 minutes = 300 seconds)
            time_diff = (timezone.now() - user.otp_created_at).total_seconds()
            if time_diff > 300:
                messages.error(request, "OTP has expired. Please request a new one.")
                return redirect('login')
                
            if user.otp_code == otp:
                user.is_active = True
                user.save()
                login(request, user)
                if 'login_email' in request.session:
                    del request.session['login_email']
                messages.success(request, "Successfully logged in!")
                return redirect('dashboard')
            else:
                messages.error(request, "Invalid OTP code.")
        except CustomUser.DoesNotExist:
            return redirect('login')
            
    return render(request, 'tracker/verify_otp.html', {'email': email})

def logout_view(request):
    if request.method == 'POST':
        logout(request)
    return redirect('login')

@login_required
def leaderboard_view(request):
    search_query = request.GET.get('q', '')
    users = CustomUser.objects.all()
    
    if search_query:
        users = users.filter(email__icontains=search_query).exclude(id=request.user.id)
        search_results = []
        following_ids = set(request.user.following_set.values_list('followed_id', flat=True))
        for u in users:
            search_results.append({
                'user': u,
                'is_following': u.id in following_ids
            })
    else:
        search_results = None

    # Fix N+1 Query Problem: single optimized SQL query to get followed users + self and sum their handles
    leaderboard_users = CustomUser.objects.filter(
        Q(follower_set__follower=request.user) | Q(id=request.user.id)
    ).annotate(total_solves_sum=Sum('handles__total_solves')).distinct()

    leaderboard_data = []
    for u in leaderboard_users:
        leaderboard_data.append({
            'user': u,
            'total_solves': u.total_solves_sum or 0
        })
    
    # Sort by total_solves descending
    leaderboard_data.sort(key=lambda x: x['total_solves'], reverse=True)

    return render(request, 'tracker/leaderboard.html', {
        'leaderboard_data': leaderboard_data,
        'search_results': search_results,
        'search_query': search_query
    })

@login_required
def toggle_friend(request, user_id):
    if request.method == 'POST':
        try:
            target_user = CustomUser.objects.get(id=user_id)
            if target_user != request.user:
                friendship, created = Friendship.objects.get_or_create(follower=request.user, followed=target_user)
                if not created:
                    friendship.delete()
                    messages.success(request, f"Removed {target_user.email} from your leaderboard.")
                else:
                    messages.success(request, f"Added {target_user.email} to your leaderboard!")
        except CustomUser.DoesNotExist:
            messages.error(request, "User not found.")
    return redirect('leaderboard')

@login_required
def delete_handle(request, handle_id):
    if request.method == 'POST':
        try:
            handle = UserHandle.objects.get(id=handle_id, user=request.user)
            platform = handle.get_platform_display()
            handle.delete()
            messages.success(request, f"Successfully removed {platform} handle.")
        except UserHandle.DoesNotExist:
            messages.error(request, "Handle not found.")
    return redirect('dashboard')

from django.http import JsonResponse
import os

def cron_refresh(request):
    token = request.GET.get('token')
    # Use environment variable for the secret, fallback to dummy for local
    expected_token = os.environ.get('CRON_SECRET', 'my-super-secret-cron-token')
    
    if token != expected_token:
        return JsonResponse({'error': 'Unauthorized'}, status=401)
        
    handles = list(UserHandle.objects.all())
    success_count = 0
    
    # Using ThreadPoolExecutor to prevent Vercel 10s timeout while fetching multiple handles
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(update_user_handle_stats, handles)
        success_count = sum(1 for res in results if res)
        
    return JsonResponse({'status': 'success', 'refreshed_count': success_count, 'total_handles': len(handles)})
