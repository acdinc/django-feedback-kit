"""Telegram webhook ucu — Telegram'dan gelen güncellemeleri alır.

Güvenlik:
  - Kimlik doğrulama JWT DEĞİL (Telegram bunu yapamaz): auth kapatılır,
    doğrulama Telegram'ın `secret_token`'ı iledir.
  - Sır tanımsızsa uç TAMAMEN KAPALIDIR (404, fail-closed) — yapılandırılmamış
    kurulumda sahte istekle cevap enjekte edilmesin.
  - Sır uyuşmazsa 403. Telegram tekrar denemesin diye işlenen istek 200 döner.
"""

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import conf, telegram

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


class TelegramWebhookView(APIView):
    # Proje varsayılanı JWT + IsAuthenticated'ı bilinçli olarak devre dışı bırak:
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        secret = conf.get("TELEGRAM_WEBHOOK_SECRET")
        if not secret:
            return Response(status=404)  # fail-closed: yapılandırılmamış
        if request.headers.get(SECRET_HEADER) != secret:
            return Response(status=403)

        telegram.process_update(request.data or {})
        # Her zaman 200: aksi halde Telegram aynı güncellemeyi tekrar tekrar yollar.
        return Response({"ok": True})
