from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('settings/', views.settings_view, name='settings'),
    path('handle/delete/<int:handle_id>/', views.delete_handle, name='delete_handle'),
    path('refresh/', views.refresh_stats, name='refresh_stats'),

    path('login/', views.login_view, name='login'),
    path('verify/', views.verify_otp_view, name='verify_otp'),
    path('logout/', views.logout_view, name='logout'),

    path('leaderboard/', views.leaderboard_view, name='leaderboard'),
    path('friend/toggle/<int:user_id>/', views.toggle_friend, name='toggle_friend'),
    path('api/cron/refresh/', views.cron_refresh, name='cron_refresh'),
]
