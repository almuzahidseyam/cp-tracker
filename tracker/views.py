from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import UserHandle, Platform
from .services import update_user_handle_stats

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
        handles = UserHandle.objects.filter(user=request.user)
        success_count = 0
        for handle in handles:
            if update_user_handle_stats(handle):
                success_count += 1
        messages.success(request, f"Refreshed stats for {success_count} handle(s).")
    return redirect('dashboard')

from django.contrib.auth import login, logout
from django.core.mail import send_mail
from .models import CustomUser

def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        if email:
            user, created = CustomUser.objects.get_or_create(email=email)
            otp = user.generate_otp()
            # Send Email
            send_mail(
                'Your CP Tracker Login Code',
                f'Your verification code is: {otp}',
                'noreply@cptracker.com',
                [email],
                fail_silently=False,
            )
            request.session['auth_email'] = email
            messages.info(request, f"OTP sent to {email}")
            return redirect('verify_otp')
    return render(request, 'tracker/login.html')

def verify_otp_view(request):
    email = request.session.get('auth_email')
    if not email:
        return redirect('login')
        
    if request.method == 'POST':
        otp = request.POST.get('otp')
        try:
            user = CustomUser.objects.get(email=email)
            if user.otp_code == otp:
                user.is_active = True
                user.save()
                login(request, user)
                if 'auth_email' in request.session:
                    del request.session['auth_email']
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
