from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import CustomUser, BankDeposit, Transaction, ParentStudent, RFIDCard, Notification, CanteenItem

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('username', 'email', 'role', 'school_name', 'profile_picture_preview')
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Info', {'fields': ('role', 'school_name', 'fcm_token', 'profile_picture')}),
    )

    def profile_picture_preview(self, obj):
        if obj.profile_picture:
            return format_html('<img src="{}" width="50" height="50" style="border-radius:50%;" />', obj.profile_picture.url)
        return "No Image"

    profile_picture_preview.short_description = 'Profile Picture'

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(BankDeposit),
admin.site.register(Transaction),
admin.site.register(ParentStudent),
admin.site.register(RFIDCard),
admin.site.register(Notification),
admin.site.register(CanteenItem)

