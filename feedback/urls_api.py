"""Kullanıcıya (mobil istemciye) açık uçlar.

Projede şöyle bağlanır — genelde API kökünün altına:

    path("support/", include("feedback.urls_api")),

Sonuç: /api/support/tickets/ , /api/support/tickets/<id>/reply/ …
"""

from rest_framework.routers import SimpleRouter

from .views import TicketViewSet

router = SimpleRouter()
router.register("tickets", TicketViewSet, basename="feedback-ticket")

urlpatterns = router.urls
