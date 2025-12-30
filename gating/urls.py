from django.urls import path

from . import views


app_name = "gating"

urlpatterns = [
    path("zalopay/callback/", views.zalopay_callback, name="zalopay-callback"),
    path("zalopay/return/", views.zalopay_return, name="zalopay-return"),
    path("content/<int:content_id>/buy/", views.zalopay_buy, name="zalopay-buy"),
    path("points/", views.points_home, name="points"),
    path("points/<int:package_id>/topup/", views.zalopay_topup, name="points-topup"),
    path("points/callback/", views.zalopay_topup_callback, name="points-callback"),
    path("points/return/", views.zalopay_topup_return, name="points-return"),
]
