from rest_framework import serializers

from ..models import InboxMessage


class InboxMessageSerializer(serializers.ModelSerializer):
    read = serializers.BooleanField(read_only=True)

    class Meta:
        model = InboxMessage
        fields = ["id", "event_code", "subject", "body", "link", "created_at", "read_at", "read"]
        read_only_fields = fields
