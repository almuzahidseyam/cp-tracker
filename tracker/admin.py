from django.contrib import admin

from .models import CustomUser


@admin.register(CustomUser)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("email", "is_active", "is_staff", "activation_locked")
    search_fields = ("email",)
    fields = (
        "email",
        "username",
        "is_active",
        "is_staff",
        "is_superuser",
        "activation_locked",
        "date_joined",
        "last_login",
    )
    readonly_fields = ("activation_locked", "date_joined", "last_login")

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        obj.activation_locked = True
        super().save_model(request, obj, form, change)
