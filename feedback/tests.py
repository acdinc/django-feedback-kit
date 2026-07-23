"""Güvenlik ve iş kuralı regresyon testleri.

Modül projeden bağımsız olmalı: kullanıcı üretimi `get_user_model()` üzerinden,
USERNAME_FIELD'a göre yapılır (e-posta ile giriş yapan projelerde de çalışır).

Projede koşturmak için:  manage.py test feedback
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from . import services
from .models import Ticket, TicketMessage, TransitionError

User = get_user_model()

sent_notifications = []


def fake_notifier(user, title, body, data=None):
    """Test için NOTIFIER — gerçek push altyapısına dokunmaz."""
    sent_notifications.append((user.pk, title, body, data))


def make_user(name, **extra):
    field = User.USERNAME_FIELD
    return User.objects.create_user(**{field: f"{name}@test.com", "password": "parola-123456", **extra})


@override_settings(FEEDBACK={"APP_NAME": "TestApp", "NOTIFIER": "feedback.tests.fake_notifier"})
class TicketAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user("kullanici")
        cls.other = make_user("baskasi")

    def setUp(self):
        cache.clear()  # throttle sayaçları testler arasında sızmasın
        sent_notifications.clear()
        self.as_user = APIClient()
        self.as_user.force_authenticate(self.user)
        self.as_other = APIClient()
        self.as_other.force_authenticate(self.other)

    # --- yardımcılar ---

    def create_ticket(self, client=None, **overrides):
        payload = {
            "kind": "complaint",
            "subject": "Bildirimler gelmiyor",
            "body": "Üç gündür hiç bildirim almıyorum.",
            "app_version": "1.2.0",
            "os_version": "18.2",
            "device_model": "iPhone15,2",
            "locale": "tr-TR",
        }
        payload.update(overrides)
        return (client or self.as_user).post(reverse("feedback-ticket-list"), payload)

    # --- temel akış ---

    def test_create_ticket_opens_thread_with_first_message(self):
        response = self.create_ticket()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "open")
        self.assertEqual(len(response.data["messages"]), 1)
        self.assertEqual(response.data["messages"][0]["author_type"], "user")

        ticket = Ticket.objects.get(pk=response.data["id"])
        self.assertEqual(ticket.user, self.user)
        self.assertEqual(ticket.device_model, "iPhone15,2")

    def test_blank_subject_or_body_rejected(self):
        self.assertEqual(self.create_ticket(subject="   ").status_code, 400)
        self.assertEqual(self.create_ticket(body="   ").status_code, 400)

    def test_staff_reply_marks_answered_and_notifies_user(self):
        ticket = Ticket.objects.get(pk=self.create_ticket().data["id"])
        staff = make_user("ekip", is_staff=True)

        services.post_staff_reply(ticket, staff, "Merhaba, inceliyoruz.")

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.ANSWERED)
        self.assertEqual(len(sent_notifications), 1)
        user_pk, _title, _body, data = sent_notifications[0]
        self.assertEqual(user_pk, self.user.pk)
        self.assertEqual(data["kind"], "support_ticket")

    def test_user_reply_reopens_answered_ticket(self):
        ticket = Ticket.objects.get(pk=self.create_ticket().data["id"])
        services.post_staff_reply(ticket, make_user("ekip", is_staff=True), "Bakıyoruz.")

        response = self.as_user.post(
            reverse("feedback-ticket-reply", args=[ticket.pk]), {"body": "Hâlâ olmuyor."}
        )

        self.assertEqual(response.status_code, 201)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.OPEN)
        self.assertEqual(ticket.messages.count(), 3)

    def test_mark_read_only_touches_staff_messages(self):
        ticket = Ticket.objects.get(pk=self.create_ticket().data["id"])
        services.post_staff_reply(ticket, make_user("ekip", is_staff=True), "Cevap.")

        listed = self.as_user.get(reverse("feedback-ticket-list")).data["results"][0]
        self.assertEqual(listed["unread_count"], 1)

        response = self.as_user.post(reverse("feedback-ticket-mark-read", args=[ticket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["unread_count"], 0)
        self.assertIsNone(ticket.messages.filter(author_type="user").first().read_at)

    # --- IDOR / yetki ---

    def test_anonymous_request_is_rejected(self):
        client = APIClient()
        self.assertEqual(client.get(reverse("feedback-ticket-list")).status_code, 401)
        self.assertEqual(self.create_ticket(client=client).status_code, 401)

    def test_other_users_ticket_is_invisible(self):
        ticket = Ticket.objects.get(pk=self.create_ticket().data["id"])

        self.assertEqual(self.as_other.get(reverse("feedback-ticket-list")).data["results"], [])
        self.assertEqual(
            self.as_other.get(reverse("feedback-ticket-detail", args=[ticket.pk])).status_code, 404
        )
        self.assertEqual(
            self.as_other.post(
                reverse("feedback-ticket-reply", args=[ticket.pk]), {"body": "sızma"}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.as_other.post(
                reverse("feedback-ticket-mark-read", args=[ticket.pk])
            ).status_code,
            404,
        )

    def test_user_field_cannot_be_forced_from_client(self):
        response = self.create_ticket(user=self.other.pk)
        self.assertEqual(Ticket.objects.get(pk=response.data["id"]).user, self.user)

    def test_update_and_delete_are_not_exposed(self):
        ticket = Ticket.objects.get(pk=self.create_ticket().data["id"])
        url = reverse("feedback-ticket-detail", args=[ticket.pk])
        self.assertEqual(self.as_user.patch(url, {"status": "closed"}).status_code, 405)
        self.assertEqual(self.as_user.delete(url).status_code, 405)

    # --- kötüye kullanım frenleri ---

    @override_settings(
        FEEDBACK={"NOTIFIER": "feedback.tests.fake_notifier", "MAX_OPEN_TICKETS": 2}
    )
    def test_open_ticket_limit(self):
        self.assertEqual(self.create_ticket().status_code, 201)
        self.assertEqual(self.create_ticket().status_code, 201)
        self.assertEqual(self.create_ticket().status_code, 400)

        # Talep kapanınca yeniden açılabilir
        Ticket.objects.filter(user=self.user).update(status=Ticket.Status.CLOSED)
        self.assertEqual(self.create_ticket().status_code, 201)

    @override_settings(FEEDBACK={"CREATE_RATE": "2/hour", "MAX_OPEN_TICKETS": 50})
    def test_create_is_rate_limited(self):
        self.assertEqual(self.create_ticket().status_code, 201)
        self.assertEqual(self.create_ticket().status_code, 201)
        self.assertEqual(self.create_ticket().status_code, 429)


class TicketModelTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user("model")
        cls.ticket = Ticket.objects.create(user=cls.user, subject="Konu")

    def test_message_is_append_only(self):
        message = TicketMessage.objects.create(
            ticket=self.ticket, author_type=TicketMessage.Author.USER, author=self.user, body="ilk"
        )
        message.body = "değiştirildi"
        with self.assertRaises(PermissionError):
            message.save()
        with self.assertRaises(PermissionError):
            message.delete()

    def test_invalid_status_transition_raises(self):
        self.ticket.set_status(Ticket.Status.CLOSED)
        with self.assertRaises(TransitionError):
            self.ticket.set_status(Ticket.Status.ANSWERED)

    def test_same_status_transition_is_noop(self):
        self.ticket.set_status(Ticket.Status.OPEN)
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)
