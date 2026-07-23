from django.db import transaction
from rest_framework import serializers

from . import conf
from .models import Ticket, TicketMessage

MAX_BODY_LENGTH = 4000


class TicketMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketMessage
        fields = ["id", "author_type", "body", "created_at", "read_at"]
        read_only_fields = fields


class TicketListSerializer(serializers.ModelSerializer):
    """Liste görünümü — yazışmanın tamamını taşımaz."""

    unread_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "kind",
            "subject",
            "status",
            "created_at",
            "updated_at",
            "unread_count",
            "last_message",
        ]

    def get_unread_count(self, ticket):
        """Kullanıcının henüz okumadığı EKİP mesajı sayısı (rozet için)."""
        return sum(
            1
            for m in ticket.messages.all()
            if m.author_type == TicketMessage.Author.STAFF and m.read_at is None
        )

    def get_last_message(self, ticket):
        messages = list(ticket.messages.all())
        if not messages:
            return None
        last = messages[-1]
        return {
            "author_type": last.author_type,
            "preview": last.body[:120],
            "created_at": last.created_at,
        }


class TicketDetailSerializer(TicketListSerializer):
    messages = TicketMessageSerializer(many=True, read_only=True)

    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + ["messages"]


class TicketCreateSerializer(serializers.ModelSerializer):
    """Yeni talep = başlık + ilk mesaj + otomatik cihaz bilgisi.

    `user` İSTEMCİDEN ALINMAZ, view'da request.user'dan yazılır (IDOR koruması).
    """

    body = serializers.CharField(max_length=MAX_BODY_LENGTH, trim_whitespace=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "kind",
            "subject",
            "body",
            "app_version",
            "os_version",
            "device_model",
            "locale",
        ]

    def validate_subject(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Konu boş olamaz.")
        return value

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("Mesaj boş olamaz.")
        return value.strip()

    def validate(self, attrs):
        user = self.context["request"].user
        limit = conf.get("MAX_OPEN_TICKETS")
        open_count = Ticket.objects.filter(
            user=user, status__in=Ticket.ACTIVE_STATUSES
        ).count()
        if open_count >= limit:
            raise serializers.ValidationError(
                {
                    "detail": (
                        f"Aynı anda en fazla {limit} açık talebiniz olabilir. "
                        "Mevcut talebinize yanıt yazarak devam edebilirsiniz."
                    )
                }
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        body = validated_data.pop("body")
        user = self.context["request"].user
        ticket = Ticket.objects.create(user=user, **validated_data)
        TicketMessage.objects.create(
            ticket=ticket,
            author_type=TicketMessage.Author.USER,
            author=user,
            body=body,
        )
        return ticket


class ReplySerializer(serializers.Serializer):
    """Hem kullanıcının hem ekibin yanıt gövdesi."""

    body = serializers.CharField(max_length=MAX_BODY_LENGTH, trim_whitespace=True)

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("Mesaj boş olamaz.")
        return value.strip()
