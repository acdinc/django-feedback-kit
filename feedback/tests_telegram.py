"""Telegram entegrasyonu testleri — gerçek HTTP'ye çıkmadan (_call monkeypatch).

Odak: giden bildirimin talebe bağlanması, webhook güvenliği (fail-closed +
secret), ve Telegram'dan gelen yanıtın doğru talebe ekip cevabı olarak
işlenmesi (yabancı sohbet / tanınmayan reply reddi dahil)."""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from . import telegram
from .models import Ticket, TelegramLink, TicketMessage

User = get_user_model()

TG = {
    "APP_NAME": "TestApp",
    "NOTIFIER": "feedback.tests_telegram.noop_notifier",
    "TELEGRAM_BOT_TOKEN": "bot-token",
    "TELEGRAM_CHAT_ID": "555",
    "TELEGRAM_WEBHOOK_SECRET": "shh",
}

notified = []


def noop_notifier(user, title, body, data=None):
    notified.append((user.pk, title, body, data))


class FakeTelegram:
    """telegram._call yerine geçer: çağrıları kaydeder, sahte message_id döner."""

    def __init__(self):
        self.calls = []
        self.next_message_id = 1000

    def __call__(self, method, payload):
        self.calls.append((method, payload))
        self.next_message_id += 1
        return {
            "ok": True,
            "result": {
                "message_id": self.next_message_id,
                "chat": {"id": int(payload["chat_id"])},
            },
        }


def make_user(name, **extra):
    field = User.USERNAME_FIELD
    return User.objects.create_user(
        **{field: f"{name}@test.com", "password": "parola-123456", **extra}
    )


def make_ticket(user, subject="Bildirim gelmiyor", body="Hiç bildirim almıyorum."):
    ticket = Ticket.objects.create(user=user, subject=subject, kind=Ticket.Kind.COMPLAINT)
    TicketMessage.objects.create(
        ticket=ticket, author_type=TicketMessage.Author.USER, author=user, body=body
    )
    return ticket


@override_settings(FEEDBACK=TG)
class TelegramOutboundTests(TestCase):
    def setUp(self):
        notified.clear()
        self.fake = FakeTelegram()
        self._orig = telegram._call
        telegram._call = self.fake

    def tearDown(self):
        telegram._call = self._orig

    def test_new_ticket_notifies_and_links(self):
        user = make_user("k")
        ticket = make_ticket(user)

        telegram.notify_new_ticket(ticket)

        # Tek sendMessage çağrısı, konu + içerik metinde
        self.assertEqual(len(self.fake.calls), 1)
        method, payload = self.fake.calls[0]
        self.assertEqual(method, "sendMessage")
        self.assertEqual(str(payload["chat_id"]), "555")
        self.assertIn("Bildirim gelmiyor", payload["text"])
        self.assertIn("Hiç bildirim almıyorum.", payload["text"])
        # Eşleme kaydı oluştu
        link = TelegramLink.objects.get(ticket=ticket)
        self.assertEqual(link.chat_id, "555")
        self.assertEqual(link.message_id, 1001)

    @override_settings(FEEDBACK={"APP_NAME": "TestApp"})  # token yok
    def test_disabled_when_unconfigured(self):
        ticket = make_ticket(make_user("k2"))
        telegram.notify_new_ticket(ticket)
        self.assertEqual(len(self.fake.calls), 0)
        self.assertFalse(TelegramLink.objects.exists())


@override_settings(FEEDBACK=TG)
class TelegramWebhookTests(TestCase):
    def setUp(self):
        notified.clear()
        self.fake = FakeTelegram()
        self._orig = telegram._call
        telegram._call = self.fake
        self.user = make_user("k")
        self.ticket = make_ticket(self.user)
        # Giden bildirimi kur → message_id 1001 ile eşleme
        telegram.notify_new_ticket(self.ticket)
        self.link = TelegramLink.objects.get(ticket=self.ticket)
        self.url = reverse("feedback-telegram-webhook")

    def tearDown(self):
        telegram._call = self._orig

    def _update(self, text, reply_message_id, chat_id="555", message_id=2001):
        return {
            "message": {
                "message_id": message_id,
                "chat": {"id": int(chat_id)},
                "text": text,
                "reply_to_message": {"message_id": reply_message_id},
            }
        }

    def post(self, body, secret="shh"):
        headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret is not None else {}
        return self.client.post(
            self.url, data=body, content_type="application/json", headers=headers
        )

    def test_reply_becomes_staff_message_and_notifies_user(self):
        resp = self.post(self._update("Merhaba, inceliyoruz.", self.link.message_id))
        self.assertEqual(resp.status_code, 200)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.ANSWERED)
        staff = self.ticket.messages.filter(author_type="staff")
        self.assertEqual(staff.count(), 1)
        self.assertEqual(staff.first().body, "Merhaba, inceliyoruz.")
        self.assertIsNone(staff.first().author)  # Telegram cevabı yazarsız
        # Kullanıcıya push gitti
        self.assertTrue(any(n[0] == self.user.pk for n in notified))

    def test_missing_secret_config_is_fail_closed(self):
        with override_settings(FEEDBACK={**TG, "TELEGRAM_WEBHOOK_SECRET": ""}):
            resp = self.post(self._update("x", self.link.message_id))
        self.assertEqual(resp.status_code, 404)

    def test_wrong_secret_rejected(self):
        resp = self.post(self._update("x", self.link.message_id), secret="yanlis")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.ticket.messages.filter(author_type="staff").count(), 0)

    def test_foreign_chat_ignored(self):
        resp = self.post(self._update("sızma", self.link.message_id, chat_id="999"))
        self.assertEqual(resp.status_code, 200)  # sessizce yok sayılır
        self.assertEqual(self.ticket.messages.filter(author_type="staff").count(), 0)

    def test_reply_to_unknown_message_ignored(self):
        resp = self.post(self._update("boşa", reply_message_id=888888))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.ticket.messages.filter(author_type="staff").count(), 0)

    def test_non_reply_message_ignored(self):
        update = {"message": {"message_id": 3, "chat": {"id": 555}, "text": "selam"}}
        resp = self.post(update)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.ticket.messages.filter(author_type="staff").count(), 0)
