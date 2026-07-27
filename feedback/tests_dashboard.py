"""Yönetim paneli (staff /support/) testleri.

Panel URL'leri projede include edildiğinde çalışır; bu testler projenin URL
konfigürasyonuna güvenir (coparents /support/ altına bağlar).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Ticket, TicketMessage

User = get_user_model()

dashboard_notifications = []


def fake_notifier(user, title, body, data=None):
    dashboard_notifications.append((user.pk, title, body, data))


def project_stats():
    return [{"label": "Premium aile", "value": 42, "hint": "test"}]


def make_user(name, **extra):
    field = User.USERNAME_FIELD
    return User.objects.create_user(
        **{field: f"{name}@test.com", "password": "parola-123456", **extra}
    )


@override_settings(
    FEEDBACK={
        "APP_NAME": "TestApp",
        "NOTIFIER": "feedback.tests_dashboard.fake_notifier",
        "DASHBOARD_STATS": "feedback.tests_dashboard.project_stats",
    }
)
class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = make_user("ekip", is_staff=True)
        cls.normal = make_user("kullanici")
        cls.ticket = Ticket.objects.create(
            user=cls.normal, subject="Bildirimler gelmiyor", kind=Ticket.Kind.COMPLAINT
        )
        TicketMessage.objects.create(
            ticket=cls.ticket,
            author_type=TicketMessage.Author.USER,
            author=cls.normal,
            body="Hiç bildirim almıyorum.",
        )

    def setUp(self):
        dashboard_notifications.clear()

    # --- erişim ---

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("feedback-dashboard-overview"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.url)

    def test_non_staff_user_cannot_access(self):
        self.client.force_login(self.normal)
        response = self.client.get(reverse("feedback-dashboard-list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.url)

    def test_staff_sees_overview_with_core_and_project_stats(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("feedback-dashboard-overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Açık talep")     # çekirdek kart
        self.assertContains(response, "Premium aile")   # enjekte edilen kart
        self.assertContains(response, "Bildirimler gelmiyor")

    # --- liste + filtre ---

    def test_status_filter(self):
        self.client.force_login(self.staff)
        url = reverse("feedback-dashboard-list")
        self.assertContains(self.client.get(url, {"status": "open"}), "Bildirimler gelmiyor")
        self.assertNotContains(
            self.client.get(url, {"status": "closed"}), "Bildirimler gelmiyor"
        )

    # --- cevap akışı ---

    def test_staff_reply_posts_message_sets_answered_and_notifies(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("feedback-dashboard-detail", args=[self.ticket.pk]),
            {"action": "reply", "body": "Merhaba, inceliyoruz."},
        )
        self.assertEqual(response.status_code, 302)  # redirect-after-post
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.ANSWERED)
        self.assertEqual(self.ticket.messages.filter(author_type="staff").count(), 1)
        self.assertEqual(len(dashboard_notifications), 1)
        self.assertEqual(dashboard_notifications[0][0], self.normal.pk)

    def test_empty_reply_rejected(self):
        self.client.force_login(self.staff)
        self.client.post(
            reverse("feedback-dashboard-detail", args=[self.ticket.pk]),
            {"action": "reply", "body": "   "},
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.messages.filter(author_type="staff").count(), 0)
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)

    def test_status_action_and_invalid_transition(self):
        self.client.force_login(self.staff)
        url = reverse("feedback-dashboard-detail", args=[self.ticket.pk])
        # geçerli: open → closed
        self.client.post(url, {"action": "status", "status": "closed"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.CLOSED)
        # geçersiz: closed → answered (durum değişmemeli)
        self.client.post(url, {"action": "status", "status": "answered"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.CLOSED)

    def test_staff_cannot_open_other_via_guessing_is_fine_all_visible(self):
        # Panelde staff TÜM talepleri görür (kullanıcı API'sinin aksine); bu
        # bilinçli — ekip her talebe erişebilmeli. Var olmayan id 404.
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.get(reverse("feedback-dashboard-detail", args=[999999])).status_code,
            404,
        )
