from django.utils import timezone
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .. import catalogue
from ..models import InboxMessage
from .serializers import InboxMessageSerializer


class InboxViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The signed-in user's inbox, newest first (`?unread=1`: the unread ones only)."""

    serializer_class = InboxMessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        rows = InboxMessage.objects.filter(user=self.request.user)
        if self.action == "list" and self.request.query_params.get("unread", "").lower() in ("1", "true"):
            rows = rows.filter(read_at__isnull=True)
        return rows

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        return Response({"unread": InboxMessage.objects.filter(user=request.user, read_at__isnull=True).count()})

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        message = self.get_object()
        if message.read_at is None:
            message.read_at = timezone.now()
            message.save(update_fields=["read_at"])
        return Response(self.get_serializer(message).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        marked = InboxMessage.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
        return Response({"marked": marked})


class CanViewRules(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.has_perm("django_notification_rules.view_notificationrule"))


class CatalogueView(APIView):
    """The event types (their fields, the operators each takes, their default texts), the resolvers and the
    channels set up: what a rule can be made of."""

    permission_classes = [permissions.IsAuthenticated, CanViewRules]

    def get(self, request):
        return Response(catalogue.catalogue())
