from django.contrib import admin
from django.urls import include, path

from tests.settings import DRF

urlpatterns = [path("admin/", admin.site.urls)]

if DRF:
    urlpatterns.append(path("api/notifications/", include("django_notification_rules.api.urls")))
