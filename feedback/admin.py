from django.contrib import admin

from .models import Ticket, TicketMessage


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0
    readonly_fields = ["author_type", "author", "body", "created_at", "read_at"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        # Cevap yazma yeri yönetim panelidir (durum makinesi + push orada işler)
        return False


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ["id", "subject", "kind", "status", "user", "created_at", "updated_at"]
    list_filter = ["status", "kind", "created_at"]
    search_fields = ["subject", "messages__body", "user__email"]
    readonly_fields = ["user", "created_at", "updated_at", "app_version", "os_version",
                       "device_model", "locale"]
    inlines = [TicketMessageInline]


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    """Append-only garantisi adminde de geçerli."""

    list_display = ["ticket", "author_type", "created_at", "read_at"]
    list_filter = ["author_type"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False
