"""The REST API (Django REST framework, the `drf` extra): the user's inbox, and the catalogue of event types,
resolvers and channels an operator UI builds its rule forms from. Include `django_notification_rules.api.urls`:

    path("api/notifications/", include("django_notification_rules.api.urls"))

- `GET inbox/` (`?unread=1`), `GET inbox/{id}/`, `GET inbox/unread-count/`, `POST inbox/{id}/read/`,
  `POST inbox/read-all/`: the signed-in user's own messages only.
- `GET catalogue/`: for users who may view the rules (`django_notification_rules.view_notificationrule`).
"""
