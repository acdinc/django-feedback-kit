"""Kullanıcıya (mobil istemciye) açık uçlar.

Projede şöyle bağlanır — genelde API kökünün altına:

    path("support/", include("feedback.urls_api")),

Sonuç: /api/support/tickets/ , /api/support/tickets/<id>/reply/ …
Ayrıca Telegram webhook'u: /api/support/telegram/webhook/ (JWT değil, secret'lı).
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import TicketViewSet
from .views_telegram import TelegramWebhookView

router = SimpleRouter()
router.register("tickets", TicketViewSet, basename="feedback-ticket")

urlpatterns = router.urls + [
    path("telegram/webhook/", TelegramWebhookView.as_view(), name="feedback-telegram-webhook"),
]
