from django.urls import path

from . import views

app_name = "contributions"

urlpatterns = [
    path("submit/", views.submit, name="submit"),
]
