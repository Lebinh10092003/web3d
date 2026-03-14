from django.urls import path

from . import views

app_name = "support_chat"

urlpatterns = [
    path("api/messages/", views.messages_feed, name="messages"),
    path("api/send/", views.send_message, name="send"),
    path("internal/operator-reply/", views.operator_reply, name="operator-reply"),
]
