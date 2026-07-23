"""Paketin projeye bakan TEK yüzü.

Bu modül dışında hiçbir dosya projeye ait bir şey import etmez — böylece aynı
app her projeye (coparents, nailcare, triplogger…) değiştirilmeden kurulabilir.
Projeye özel her davranış `settings.FEEDBACK` sözlüğünden gelir.

    FEEDBACK = {
        "APP_NAME": "Coparoo",
        "NOTIFIER": "apps.notifications.service.notify_user",
        "MAX_OPEN_TICKETS": 5,
    }
"""

import logging

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

DEFAULTS = {
    # Panelde ve bildirim başlığında görünen uygulama adı.
    "APP_NAME": "",
    # (user, title, body, data) imzalı çağrılabilir ya da noktalı yolu.
    # Tanımsızsa bildirim gönderilmez (modül yine de çalışır).
    "NOTIFIER": None,
    # Kullanıcı başına talep açma hızı — spam/kötüye kullanım freni.
    "CREATE_RATE": "10/hour",
    # Kullanıcı başına yanıt yazma hızı.
    "REPLY_RATE": "60/hour",
    # Aynı anda açık kalabilecek talep sayısı. Aşılırsa yeni talep 400 döner;
    # amaç aynı kullanıcının 50 talep açıp paneli boğmasını engellemek.
    "MAX_OPEN_TICKETS": 5,
}


def get(key):
    if key not in DEFAULTS:
        raise KeyError(f"Bilinmeyen FEEDBACK ayarı: {key}")
    return getattr(settings, "FEEDBACK", {}).get(key, DEFAULTS[key])


def notify(user, title, body, data=None):
    """Projenin kendi bildirim altyapısına köprü.

    Bildirim gönderilememesi destek yazışmasını BOZMAMALI: hata yutulur ama
    loglanır. (Ekip cevabı veritabanına yazılmıştır; kullanıcı uygulamayı
    açtığında zaten görür — push yalnızca hızlandırıcıdır.)
    """
    target = get("NOTIFIER")
    if not target:
        return
    try:
        fn = import_string(target) if isinstance(target, str) else target
        fn(user, title, body, data or {})
    except Exception:  # pragma: no cover - altyapı hatası
        logger.exception("feedback: bildirim gönderilemedi (ticket akışı etkilenmedi)")
