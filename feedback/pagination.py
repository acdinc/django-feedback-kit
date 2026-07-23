from rest_framework.pagination import CursorPagination


class TicketCursorPagination(CursorPagination):
    """Modül kendi sayfalamasını taşır — kuran projenin DRF ayarına bağımlı olmaz
    (DRF'nin varsayılanı '-created' alanını arar, bizde alan 'created_at')."""

    ordering = "-created_at"
    page_size = 25
