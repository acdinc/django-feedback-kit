"""Yönetim paneli — Django template ile /support/.

Erişim: yalnızca `is_staff` kullanıcılar. `staff_member_required` giriş yapmamış
ziyaretçiyi Django admin girişine yönlendirir; böylece panel için ayrı bir
kimlik doğrulama yazmaya gerek kalmaz (admin girişi tek doğruluk kaynağı).
"""

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from . import services, stats
from .models import Ticket, TicketMessage
from .serializers import MAX_BODY_LENGTH

PAGE_SIZE = 20


@staff_member_required
def overview(request):
    """İstatistik kartları + en son hareket gören açık talepler."""
    recent = (
        Ticket.objects.filter(status__in=Ticket.ACTIVE_STATUSES)
        .select_related("user")
        .prefetch_related("messages")
        .order_by("-updated_at")[:10]
    )
    return render(
        request,
        "feedback/dashboard/overview.html",
        {
            "app_name": stats.conf.get("APP_NAME") or "Destek",
            "cards": stats.all_stats(),
            "recent": recent,
            "kinds": Ticket.Kind.choices,
            "statuses": Ticket.Status.choices,
        },
    )


@staff_member_required
def ticket_list(request):
    """Filtrelenebilir talep listesi (durum + kategori)."""
    tickets = Ticket.objects.select_related("user").prefetch_related("messages")

    status = request.GET.get("status") or ""
    kind = request.GET.get("kind") or ""
    query = (request.GET.get("q") or "").strip()

    if status in Ticket.Status.values:
        tickets = tickets.filter(status=status)
    if kind in Ticket.Kind.values:
        tickets = tickets.filter(kind=kind)
    if query:
        tickets = tickets.filter(subject__icontains=query)

    tickets = tickets.order_by("-updated_at")
    page = Paginator(tickets, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(
        request,
        "feedback/dashboard/ticket_list.html",
        {
            "app_name": stats.conf.get("APP_NAME") or "Destek",
            "page": page,
            "kinds": Ticket.Kind.choices,
            "statuses": Ticket.Status.choices,
            "cur_status": status,
            "cur_kind": kind,
            "query": query,
        },
    )


@staff_member_required
def ticket_detail(request, pk):
    """Yazışma görünümü + cevap kutusu + durum değiştirme.

    POST'ta 'action' alanı:
      - reply  → ekip yanıtı (durum 'yanıtlandı' + kullanıcıya push)
      - status → durum geçişi (geçersizse uyarı)
    """
    ticket = get_object_or_404(
        Ticket.objects.select_related("user").prefetch_related("messages"), pk=pk
    )

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "reply":
            body = (request.POST.get("body") or "").strip()
            if not body:
                messages.error(request, "Boş yanıt gönderilemez.")
            elif len(body) > MAX_BODY_LENGTH:
                messages.error(request, "Yanıt çok uzun.")
            else:
                services.post_staff_reply(ticket, request.user, body)
                messages.success(request, "Yanıt gönderildi, kullanıcıya bildirim iletildi.")

        elif action == "status":
            new_status = request.POST.get("status")
            if new_status in Ticket.Status.values:
                try:
                    ticket.set_status(new_status)
                    messages.success(request, "Durum güncellendi.")
                except Exception:
                    messages.error(request, "Bu durum geçişi geçersiz.")
            else:
                messages.error(request, "Geçersiz durum.")

        return redirect("feedback-dashboard-detail", pk=ticket.pk)

    return render(
        request,
        "feedback/dashboard/ticket_detail.html",
        {
            "app_name": stats.conf.get("APP_NAME") or "Destek",
            "ticket": ticket,
            "conversation": ticket.messages.all(),
            "statuses": Ticket.Status.choices,
            "author_user": TicketMessage.Author.USER,
        },
    )
