from django.urls import path

from . import views


app_name = "gating"

urlpatterns = [
    path("zalopay/callback/", views.zalopay_callback, name="zalopay-callback"),
    path("zalopay/return/", views.zalopay_return, name="zalopay-return"),
    path("content/<int:content_id>/buy/", views.zalopay_buy, name="zalopay-buy"),
]
