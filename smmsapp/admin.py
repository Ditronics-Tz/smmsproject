from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import CustomUser, BankDeposit, Transaction, ParentStudent, RFIDCard, Notification, CanteenItem, ScanSession, ScannedData, School, LedgerEntry, Reversal, Reconciliation, ReplacementLink, PasswordResetToken, AuditLog

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('username','first_name', 'last_name', 'email','role','mobile_number', 'profile_picture_preview')
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Info', {'fields': ('middle_name', 'role', 'school', 'fcm_token', 'profile_picture', 'gender', 'mobile_number', 'parent_type')}),
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
admin.site.register(CanteenItem),
admin.site.register(ScannedData),
admin.site.register(ScanSession),
admin.site.register(School)
admin.site.register(LedgerEntry)
admin.site.register(Reversal)
admin.site.register(Reconciliation)
admin.site.register(ReplacementLink)
admin.site.register(PasswordResetToken)
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp','actor','action','object_repr','ip_address','path')
    list_filter = ('action','timestamp')
    search_fields = ('object_repr','actor__username')
    readonly_fields = ('timestamp','actor','action','content_type','object_id','object_repr','before','after','ip_address','path','user_agent')

