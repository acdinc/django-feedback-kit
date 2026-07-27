# django-feedback-kit

iOS uygulamalarının backend'lerine takılan **istek / şikayet / hata bildirimi**
modülü. Tek bir Django app'i; projeye özel hiçbir import içermez, tüm bağlantı
noktaları `settings.FEEDBACK` üzerinden enjekte edilir.

Durum: **v0.3.0 — kullanıcı API'si + staff panel + Telegram (bildirim & cevap).**

## Kurulum

```bash
pip install "django-feedback-kit @ git+https://github.com/<kullanici>/django-feedback-kit@v0.1.0"
```

`settings.py`:

```python
INSTALLED_APPS += ["feedback"]

FEEDBACK = {
    "APP_NAME": "Coparoo",
    # (user, title, body, data) imzalı fonksiyon — ekip cevabı yazınca çağrılır.
    # Tanımsız bırakılırsa bildirim gönderilmez, modül yine çalışır.
    "NOTIFIER": "apps.notifications.service.notify_user",
    "MAX_OPEN_TICKETS": 5,     # aynı anda açık talep sınırı
    "CREATE_RATE": "10/hour",  # kullanıcı başına talep açma hızı
    "REPLY_RATE": "60/hour",   # kullanıcı başına yanıt yazma hızı
}
```

İki grup URL bağlanır — biri mobil istemci için (API kökünün altına), biri
yönetim paneli için (proje kökünün altına):

```python
# config/api.py  (DRF router'ının olduğu yer)
path("support/", include("feedback.urls_api")),        # → /api/support/tickets/

# config/urls.py  (proje kökü)
path("support/", include("feedback.urls_dashboard")),  # → /support/  (staff paneli)
```

Sonra `manage.py migrate`.

## Yönetim paneli (`/support/`)

Staff kullanıcılar için Django template paneli — ayrı frontend/deploy yok,
backend ile aynı sunucuda çalışır. Erişim `staff_member_required` ile Django
admin girişine bağlıdır (ayrı kimlik doğrulama yok).

- **Özet** (`/support/`): istatistik kartları + bekleyen talepler.
- **Talepler** (`/support/tickets/`): durum/tür/konu filtreli liste, sayfalama.
- **Detay** (`/support/tickets/<id>/`): cihaz meta verisi, yazışma, cevap kutusu
  (durum 'yanıtlandı' + kullanıcıya push) ve durum değiştirme.

İstatistik kartları iki kaynaktan gelir: modülün her projede aynı hesapladığı
**çekirdek talep sayıları** (açık talep, son 7 gün, toplam, ort. ilk yanıt) ve
projeye özel **enjekte edilen kartlar** (`FEEDBACK["DASHBOARD_STATS"]`):

```python
# config/feedback_stats.py
def dashboard_stats():
    return [
        {"label": "Toplam kullanıcı", "value": User.objects.count()},
        {"label": "Premium aile", "value": 87, "hint": "aktif abonelik"},
    ]

# settings.py
FEEDBACK["DASHBOARD_STATS"] = "config.feedback_stats.dashboard_stats"
```

## Uçlar

| Metot | Yol | Ne yapar |
|---|---|---|
| `GET` | `/api/support/tickets/` | Kullanıcının talepleri (cursor sayfalama, `unread_count`, `last_message`) |
| `POST` | `/api/support/tickets/` | Yeni talep: `kind`, `subject`, `body` + cihaz meta verisi |
| `GET` | `/api/support/tickets/{id}/` | Talep + tüm yazışma |
| `POST` | `/api/support/tickets/{id}/reply/` | Kullanıcının yanıtı (yanıtlanmış/kapalı talebi yeniden açar) |
| `POST` | `/api/support/tickets/{id}/mark-read/` | Ekip mesajlarını okundu işaretler |

`kind`: `bug` · `request` · `complaint` · `question`
`status`: `open` → `in_progress` → `answered` → `closed`

Örnek oluşturma gövdesi:

```json
{
  "kind": "complaint",
  "subject": "Bildirimler gelmiyor",
  "body": "Üç gündür hiç bildirim almıyorum.",
  "app_version": "1.2.0",
  "os_version": "18.2",
  "device_model": "iPhone15,2",
  "locale": "tr-TR"
}
```

Cihaz alanlarını istemci otomatik doldurur; kullanıcı yazmaz. Bu alanlar
yalnızca sürüm/model/dil taşır — kişisel veri konmaz.

## Tasarım kararları

- **Queryset izolasyonu:** tüm uçlar `user=request.user` ile daraltılır;
  başkasının talebi 404 döner (IDOR). `user` alanı istemciden yazılamaz.
- **Append-only yazışma:** `TicketMessage` düzenlenemez/silinemez; tek istisna
  `read_at`. Şikayet kaydı sonradan değiştirilemesin diye.
- **Silme yok:** talep ve mesajlar için DELETE ucu açılmamıştır.
- **Kötüye kullanım freni:** kullanıcı başına hız sınırı + açık talep sayısı
  sınırı. Oranlar DRF'nin global sözlüğüne değil `FEEDBACK`e yazılır; kuran
  proje ayarı unutursa throttle sessizce kapanmaz.
- **Bildirim izole:** push başarısız olursa yazışma etkilenmez (hata loglanır).
- **Kendi sayfalaması:** modül `CursorPagination`'ı kendi taşır, projenin DRF
  varsayılanına bağımlı değildir.

## Telegram (yönetici bildirimi + Telegram'dan cevap)

Yeni talep gelince yöneticinin Telegram sohbetine mesaj düşer; o mesaja **reply**
yazınca cevap talebe ekip mesajı olarak işlenir (durum "yanıtlandı" + kullanıcıya
push). Üç ayar da tanımlı değilse Telegram tümüyle kapalıdır.

```python
FEEDBACK.update({
    "TELEGRAM_BOT_TOKEN": os.environ["TELEGRAM_BOT_TOKEN"],
    "TELEGRAM_CHAT_ID": os.environ["TELEGRAM_CHAT_ID"],
    "TELEGRAM_WEBHOOK_SECRET": os.environ["TELEGRAM_WEBHOOK_SECRET"],
})
```

Kurulum:
1. @BotFather'dan bot oluştur → token.
2. Bota bir mesaj at, sonra `https://api.telegram.org/bot<token>/getUpdates`
   çıktısındaki `chat.id`'yi al.
3. Rastgele bir `TELEGRAM_WEBHOOK_SECRET` üret; üç değeri sunucu env'ine koy.
4. Webhook'u kaydet (secret ile):
   ```
   curl "https://api.telegram.org/bot<token>/setWebhook" \
     -d url="https://<host>/api/support/telegram/webhook/" \
     -d secret_token="<TELEGRAM_WEBHOOK_SECRET>"
   ```

Güvenlik: webhook JWT değil — Telegram'ın `secret_token`'ı ile doğrulanır; sır
tanımsızsa uç 404 (fail-closed), uyuşmazsa 403. Yalnızca yapılandırılmış sohbetten
gelen, bir bot mesajına yanıt olan metinler işlenir. Gizlilik: Telegram'a yalnızca
destek talebinin kendi içeriği taşınır (yönetici cevap yazabilmek için görür).

## Test

```bash
manage.py test feedback
```

Projenin `manage.py test` çıktısına dahil etmek için proje köküne şu dosyayı
koyun (`tests_feedback.py`):

```python
from feedback.tests import *            # noqa  (API testleri)
from feedback.tests_dashboard import *  # noqa  (panel testleri; URL include gerektirir)
from feedback.tests_telegram import *   # noqa  (Telegram testleri)
```
