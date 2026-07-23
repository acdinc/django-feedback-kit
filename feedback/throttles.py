"""Kullanıcı başına hız sınırları.

Oranlar projenin `DEFAULT_THROTTLE_RATES` sözlüğünden DEĞİL, `FEEDBACK`
ayarından okunur — böylece modülü kuran proje DRF ayarlarına dokunmak zorunda
kalmaz (dokunmayı unutursa da throttle sessizce devre dışı kalmaz).
"""

from rest_framework.throttling import SimpleRateThrottle

from . import conf


class _UserScopedThrottle(SimpleRateThrottle):
    rate_key = ""

    def get_rate(self):
        return conf.get(self.rate_key)

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None  # kimliksiz istek zaten 401 alacak
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


class CreateTicketThrottle(_UserScopedThrottle):
    scope = "feedback_create"
    rate_key = "CREATE_RATE"


class ReplyThrottle(_UserScopedThrottle):
    scope = "feedback_reply"
    rate_key = "REPLY_RATE"
