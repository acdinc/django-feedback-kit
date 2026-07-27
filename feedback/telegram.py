"""Telegram entegrasyonu — yönetici bildirimi + Telegram'dan cevap.

Akış:
  1. Yeni talep açılınca `notify_new_ticket` bota mesaj gönderir ve mesaj
     kimliğini talebe bağlar (TelegramLink).
  2. Yönetici o mesaja REPLY yazar; Telegram webhook'u `process_update`'i
     çağırır; reply hedefi TelegramLink'ten talebe çözülür ve cevap
     `services.post_staff_reply` ile eklenir (durum 'yanıtlandı' + kullanıcıya
     push). Böylece iki giriş noktası (panel + Telegram) aynı kuralları paylaşır.

Bağımlılık eklemez: HTTP çağrıları stdlib `urllib` iledir. Ağ hataları yutulur
ve loglanır — Telegram'ın erişilemez olması talep akışını BOZMAZ.
"""

import json
import logging
import urllib.error
import urllib.request

from . import conf, services
from .models import TelegramLink, TicketMessage

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"
_PREVIEW_LIMIT = 1500


def enabled():
    return bool(conf.get("TELEGRAM_BOT_TOKEN") and conf.get("TELEGRAM_CHAT_ID"))


def _call(method, payload):
    """Telegram Bot API çağrısı. Sözlük döner; hata durumunda fırlatır."""
    url = _API.format(token=conf.get("TELEGRAM_BOT_TOKEN"), method=method)
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def notify_new_ticket(ticket):
    """Yeni talebi yöneticinin sohbetine gönderir ve mesajı talebe bağlar.

    GİZLİLİK NOTU: talep metni (kullanıcının yazdığı) buraya taşınır — yönetici
    cevap yazabilmek için içeriği görmek zorundadır. Telegram üçüncü taraf bir
    servistir; yalnızca destek talebinin kendi içeriği gider, başka kullanıcı/
    aile verisi değil. Kanal projenin bilinçli tercihidir (env ile açılır).
    """
    if not enabled():
        return
    first = ticket.messages.first()
    body = first.body if first else ""
    app = conf.get("APP_NAME") or "Destek"
    text = (
        f"🆕 {app} · {ticket.get_kind_display()}\n"
        f"#{ticket.pk} — {ticket.subject}\n\n"
        f"{body[:_PREVIEW_LIMIT]}\n\n"
        f"↩️ Bu mesaja YANIT yazarsan kullanıcıya iletilir."
    )
    try:
        result = _call("sendMessage", {"chat_id": conf.get("TELEGRAM_CHAT_ID"), "text": text})
        if result.get("ok"):
            message = result["result"]
            TelegramLink.objects.create(
                ticket=ticket,
                chat_id=str(message["chat"]["id"]),
                message_id=message["message_id"],
            )
    except Exception:  # pragma: no cover - ağ/altyapı hatası akışı bozmamalı
        logger.exception("feedback: Telegram bildirimi gönderilemedi (talep etkilenmedi)")


def process_update(update):
    """Gelen webhook güncellemesini işler.

    Yalnızca YAPILANDIRILMIŞ sohbetteki, bir bot mesajına YANIT olan metin
    mesajları kabul edilir; gerisi sessizce yok sayılır (yabancı sohbet, komut,
    tanınmayan reply). Dönüş: işlendiyse ilgili Ticket, yoksa None.
    """
    message = update.get("message") or {}
    reply_to = message.get("reply_to_message")
    text = (message.get("text") or "").strip()
    chat_id = str((message.get("chat") or {}).get("id", ""))

    if not reply_to or not text:
        return None
    if chat_id != str(conf.get("TELEGRAM_CHAT_ID")):
        return None  # yalnızca yapılandırılmış sohbetten yanıt kabul edilir

    link = (
        TelegramLink.objects.select_related("ticket")
        .filter(chat_id=chat_id, message_id=reply_to.get("message_id"))
        .first()
    )
    if link is None:
        return None

    # Yazar None: Telegram'dan gelen ekip cevabı belirli bir Django kullanıcısına
    # bağlanmaz (author SET_NULL) — panelde "Ekip" olarak görünür.
    services.post_staff_reply(link.ticket, None, text)
    _confirm(chat_id, message.get("message_id"))
    return link.ticket


def _confirm(chat_id, reply_to_message_id):
    try:
        _call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "reply_to_message_id": reply_to_message_id,
                "text": "✅ Yanıt kullanıcıya iletildi.",
            },
        )
    except Exception:  # pragma: no cover
        logger.exception("feedback: Telegram onayı gönderilemedi")


# Yeni mesajın yazar tipini burada da kullanılabilir tutmak için (test kolaylığı)
STAFF = TicketMessage.Author.STAFF
