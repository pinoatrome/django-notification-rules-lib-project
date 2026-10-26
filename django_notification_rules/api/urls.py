from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CatalogueView, InboxViewSet

app_name = "django_notification_rules"

router = DefaultRouter()
router.register("inbox", InboxViewSet, basename="inbox-message")

urlpatterns = [
    path("catalogue/", CatalogueView.as_view(), name="catalogue"),
    path("", include(router.urls)),
]
