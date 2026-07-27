"""Yönetim paneli uçları — proje köküne bağlanır (API'nin ALTINA DEĞİL):

    path("support/", include("feedback.urls_dashboard")),

Sonuç: /support/ (özet), /support/tickets/ (liste), /support/tickets/<id>/
"""

from django.urls import path

from . import views_dashboard as v

urlpatterns = [
    path("", v.overview, name="feedback-dashboard-overview"),
    path("tickets/", v.ticket_list, name="feedback-dashboard-list"),
    path("tickets/<int:pk>/", v.ticket_detail, name="feedback-dashboard-detail"),
]
