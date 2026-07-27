from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import services, telegram
from .models import Ticket, TicketMessage
from .pagination import TicketCursorPagination
from .serializers import (
    ReplySerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketListSerializer,
)
from .throttles import CreateTicketThrottle, ReplyThrottle


class TicketViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Kullanıcının kendi destek talepleri.

    Silme/düzenleme yoktur (yazışma kaydı bozulmasın). Queryset her zaman
    `user=request.user` ile daraltılır — nesne izni ayrıca gerekmez, başkasının
    talebi 404 döner (IDOR).
    """

    permission_classes = [IsAuthenticated]
    pagination_class = TicketCursorPagination

    def get_queryset(self):
        return (
            Ticket.objects.filter(user=self.request.user)
            .prefetch_related("messages")
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return TicketCreateSerializer
        if self.action == "list":
            return TicketListSerializer
        return TicketDetailSerializer

    def get_throttles(self):
        if self.action == "create":
            return [CreateTicketThrottle()]
        if self.action == "reply":
            return [ReplyThrottle()]
        return super().get_throttles()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = serializer.save()
        # Yöneticiye Telegram bildirimi (yapılandırılmışsa; değilse sessiz no-op).
        # Hata talep oluşturmayı BOZMAZ (telegram içinde yutulur/loglanır).
        telegram.notify_new_ticket(ticket)
        # Yanıtta ayrıntı biçimini döndür: istemci hemen yazışma ekranını açabilir
        detail = TicketDetailSerializer(ticket, context=self.get_serializer_context())
        return Response(detail.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        """Kullanıcının kendi talebine yanıtı."""
        ticket = self.get_object()
        serializer = ReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.post_user_reply(ticket, request.user, serializer.validated_data["body"])
        # Yeniden çek: get_object() öncesi prefetch'lenmiş mesaj listesi bayat
        fresh = self.get_queryset().get(pk=ticket.pk)
        return Response(
            TicketDetailSerializer(fresh, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        """Ekip mesajlarını okundu işaretler (idempotent, rozet sıfırlar)."""
        ticket = self.get_object()
        ticket.messages.filter(
            author_type=TicketMessage.Author.STAFF, read_at__isnull=True
        ).update(read_at=timezone.now())
        fresh = self.get_queryset().get(pk=ticket.pk)
        return Response(
            TicketDetailSerializer(fresh, context=self.get_serializer_context()).data
        )
