"""Panel istatistikleri.

Çekirdek (talep) istatistiklerini modül kendi hesaplar. Projeye özel sayılar
(kullanıcı, premium, aile…) her projenin kendi veritabanında olduğundan, onlar
`FEEDBACK["DASHBOARD_STATS"]` ile enjekte edilen bir fonksiyondan gelir:

    def dashboard_stats():
        return [
            {"label": "Toplam kullanıcı", "value": 1240},
            {"label": "Premium aile", "value": 87, "hint": "aktif abonelik"},
        ]

Fonksiyon yoksa panel yalnızca çekirdek talep istatistiklerini gösterir.
"""

from datetime import timedelta

from django.utils import timezone
from django.utils.module_loading import import_string

from . import conf
from .models import Ticket, TicketMessage


def _format_duration(delta):
    """timedelta → insan okuyabilir kısa metin ('3 sa', '2 gün', '18 dk')."""
    if delta is None:
        return "—"
    seconds = int(delta.total_seconds())
    if seconds < 3600:
        return f"{max(1, seconds // 60)} dk"
    if seconds < 86400:
        return f"{seconds // 3600} sa"
    return f"{seconds // 86400} gün"


def core_ticket_stats():
    """Modülün her projede aynı hesapladığı talep istatistikleri."""
    now = timezone.now()
    last_7 = now - timedelta(days=7)
    last_30 = now - timedelta(days=30)

    tickets = Ticket.objects.all()
    open_count = tickets.filter(status__in=Ticket.ACTIVE_STATUSES).count()
    week_count = tickets.filter(created_at__gte=last_7).count()
    total = tickets.count()

    # Ortalama ilk yanıt süresi: son 30 günde açılıp EKİP yanıtı almış
    # talepler üzerinden (talep açılışı → ilk ekip mesajı).
    deltas = []
    recent = tickets.filter(created_at__gte=last_30).prefetch_related("messages")
    for ticket in recent:
        staff_times = [
            m.created_at
            for m in ticket.messages.all()
            if m.author_type == TicketMessage.Author.STAFF
        ]
        if staff_times:
            deltas.append(min(staff_times) - ticket.created_at)
    avg_response = sum(deltas, timedelta()) / len(deltas) if deltas else None

    return [
        {"label": "Açık talep", "value": open_count, "hint": "yanıt bekliyor", "accent": True},
        {"label": "Son 7 gün", "value": week_count, "hint": "yeni talep"},
        {"label": "Toplam talep", "value": total},
        {"label": "Ort. ilk yanıt", "value": _format_duration(avg_response), "hint": "son 30 gün"},
    ]


def project_stats():
    """Projeye özel kartlar (enjekte edilen fonksiyondan). Hata panelı çökertmez."""
    target = conf.get("DASHBOARD_STATS")
    if not target:
        return []
    try:
        fn = import_string(target) if isinstance(target, str) else target
        return list(fn()) or []
    except Exception:  # pragma: no cover - proje tarafı hatası panelı düşürmesin
        return []


def all_stats():
    return core_ticket_stats() + project_stats()
