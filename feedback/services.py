"""Yazışma iş mantığı — hem kullanıcı API'si hem yönetim paneli buradan geçer.

Durum makinesi ve bildirim tetiği tek yerde durur; iki giriş noktasının
kuralları ayrışamaz.
"""

from django.db import transaction

from . import conf
from .models import Ticket, TicketMessage


@transaction.atomic
def post_user_reply(ticket, user, body):
    """Kullanıcının yanıtı. Yanıtlanmış/kapatılmış talebi yeniden açar."""
    message = TicketMessage.objects.create(
        ticket=ticket,
        author_type=TicketMessage.Author.USER,
        author=user,
        body=body,
    )
    if ticket.status in (Ticket.Status.ANSWERED, Ticket.Status.CLOSED):
        ticket.set_status(Ticket.Status.OPEN)
    else:
        ticket.touch()
    return message


@transaction.atomic
def post_staff_reply(ticket, staff_user, body):
    """Ekibin yanıtı: mesajı yazar, durumu 'yanıtlandı'ya çeker, push tetikler."""
    message = TicketMessage.objects.create(
        ticket=ticket,
        author_type=TicketMessage.Author.STAFF,
        author=staff_user,
        body=body,
    )
    ticket.set_status(Ticket.Status.ANSWERED)

    app_name = conf.get("APP_NAME") or "Destek"
    conf.notify(
        ticket.user,
        app_name,
        "Destek talebinize yanıt verildi.",
        {"kind": "support_ticket", "ticket": ticket.pk},
    )
    return message
