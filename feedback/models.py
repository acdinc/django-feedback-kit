from django.conf import settings
from django.db import models
from django.utils import timezone


class TransitionError(Exception):
    """Geçersiz durum geçişi — view katmanı bunu 409'a çevirir."""


class Ticket(models.Model):
    """Bir kullanıcının açtığı destek kaydı (istek / şikayet / hata / soru).

    Kayıt bir YAZIŞMA dizisidir: ilk mesajı kullanıcı açar, ekip panelden
    cevaplar, kullanıcı uygulama içinden devam edebilir.
    """

    class Kind(models.TextChoices):
        BUG = "bug", "Hata"
        REQUEST = "request", "İstek"
        COMPLAINT = "complaint", "Şikayet"
        QUESTION = "question", "Soru"

    class Status(models.TextChoices):
        OPEN = "open", "Açık"
        IN_PROGRESS = "in_progress", "İnceleniyor"
        ANSWERED = "answered", "Yanıtlandı"
        CLOSED = "closed", "Kapatıldı"

    # Panelde "işim var" sayacına giren durumlar
    ACTIVE_STATUSES = (Status.OPEN, Status.IN_PROGRESS)

    # Durum makinesi: kimin hangi geçişi yapabileceği view katmanında,
    # hangi geçişin ANLAMLI olduğu burada tanımlıdır.
    ALLOWED_TRANSITIONS = {
        Status.OPEN: {Status.IN_PROGRESS, Status.ANSWERED, Status.CLOSED},
        Status.IN_PROGRESS: {Status.OPEN, Status.ANSWERED, Status.CLOSED},
        Status.ANSWERED: {Status.OPEN, Status.IN_PROGRESS, Status.CLOSED},
        Status.CLOSED: {Status.OPEN, Status.IN_PROGRESS},
    }

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="feedback_tickets"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.QUESTION)
    subject = models.CharField(max_length=120)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)

    # İstemcinin otomatik doldurduğu tanılama verisi — kullanıcı yazmaz.
    # Hassas veri TAŞIMAZ: sürüm/model/dil dışında bir şey kabul edilmez.
    app_version = models.CharField(max_length=32, blank=True)
    os_version = models.CharField(max_length=32, blank=True)
    device_model = models.CharField(max_length=48, blank=True)
    locale = models.CharField(max_length=16, blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    # Son hareket (yeni mesaj / durum değişikliği) — panel bu alana göre sıralar
    updated_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-updated_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        return f"#{self.pk} {self.subject}"

    def touch(self):
        self.updated_at = timezone.now()
        self.save(update_fields=["updated_at"])

    def set_status(self, new_status):
        """Durum geçişi — geçersizse TransitionError.

        Aynı duruma geçiş sessizce yok sayılır (idempotent): panelde iki kez
        tıklamak hata vermemeli.
        """
        if new_status == self.status:
            return
        if new_status not in self.ALLOWED_TRANSITIONS.get(self.status, set()):
            raise TransitionError(f"{self.status} → {new_status} geçişi geçersiz")
        self.status = new_status
        self.updated_at = timezone.now()
        self.save(update_fields=["status", "updated_at"])


class TicketMessage(models.Model):
    """Yazışmanın tek bir satırı. Append-only: düzenlenmez, silinmez.

    Şikayet kayıtları sonradan değiştirilebilir olmamalı (hem kullanıcı hem
    ekip tarafı için delil niteliği taşır). Tek istisna `read_at`.
    """

    class Author(models.TextChoices):
        USER = "user", "Kullanıcı"
        STAFF = "staff", "Ekip"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    author_type = models.CharField(max_length=8, choices=Author.choices)
    # Yazan kişi; hesap silinirse yazışma kaybolmasın diye SET_NULL.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    body = models.TextField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    # Kullanıcının EKİP mesajını okuduğu an (uygulamadaki rozet için)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_author_type_display()} @ {self.created_at:%Y-%m-%d %H:%M}"

    def save(self, *args, update_fields=None, **kwargs):
        if self.pk is not None:
            if update_fields is None or set(update_fields) != {"read_at"}:
                raise PermissionError("Destek mesajı değiştirilemez (append-only).")
            return super().save(*args, update_fields=update_fields, **kwargs)
        self.created_at = timezone.now()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Destek mesajı silinemez (append-only).")
