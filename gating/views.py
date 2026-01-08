import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from library.models import ContentItem

from .models import PaymentTransaction, PointLedger, PointPackage, PointTopupTransaction, Unlock


logger = logging.getLogger(__name__)


def _build_app_trans_id():
    date_prefix = datetime.now().strftime("%y%m%d")
    random_part = uuid.uuid4().hex[:10]
    return f"{date_prefix}_{random_part}"


def _build_unique_app_trans_id():
    app_trans_id = _build_app_trans_id()
    while (
        PaymentTransaction.objects.filter(app_trans_id=app_trans_id).exists()
        or PointTopupTransaction.objects.filter(app_trans_id=app_trans_id).exists()
    ):
        app_trans_id = _build_app_trans_id()
    return app_trans_id


def _sign_hmac(key, data):
    return hmac.new(key.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()


def _post_zalopay_create(payload):
    encoded = urlencode(payload).encode("utf-8")
    request = Request(
        settings.ZALOPAY_ENDPOINT_CREATE,
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")
    return json.loads(body or "{}")


@login_required
@require_POST
def zalopay_buy(request, content_id):
    content = get_object_or_404(
        ContentItem, pk=content_id, is_public=True, status=ContentItem.Status.PUBLISHED
    )
    if content.price_vnd <= 0:
        messages.error(request, "This content is not for sale.")
        return redirect("library:content-detail", pk=content_id)
    if content.owner_id == request.user.id:
        messages.info(request, "You already own this content.")
        return redirect("library:content-detail", pk=content_id)
    if Unlock.objects.filter(
        content=content, user=request.user, method=Unlock.Method.PAYMENT
    ).exists():
        messages.info(request, "Content already unlocked.")
        return redirect("library:content-detail", pk=content_id)

    if not settings.ZALOPAY_APP_ID or not settings.ZALOPAY_KEY1:
        messages.error(request, "ZaloPay is not configured.")
        return redirect("library:content-detail", pk=content_id)

    callback_url = settings.ZALOPAY_CALLBACK_URL or request.build_absolute_uri(
        reverse("gating:zalopay-callback")
    )
    return_url = settings.ZALOPAY_RETURN_URL or request.build_absolute_uri(
        reverse("gating:zalopay-return")
    )

    app_time = int(time.time() * 1000)
    app_trans_id = _build_unique_app_trans_id()
    app_user = str(request.user.id)
    amount = int(content.price_vnd)

    items = json.dumps(
        [
            {
                "itemid": content.id,
                "itemname": content.title,
                "itemprice": amount,
                "itemquantity": 1,
            }
        ]
    )
    embed_data = json.dumps(
        {
            "content_id": content.id,
            "user_id": request.user.id,
            "return_url": return_url,
        }
    )

    mac_data = "|".join(
        [
            str(settings.ZALOPAY_APP_ID),
            app_trans_id,
            app_user,
            str(amount),
            str(app_time),
            embed_data,
            items,
        ]
    )
    mac = _sign_hmac(settings.ZALOPAY_KEY1, mac_data)

    payload = {
        "app_id": settings.ZALOPAY_APP_ID,
        "app_user": app_user,
        "app_trans_id": app_trans_id,
        "app_time": app_time,
        "amount": amount,
        "item": items,
        "embed_data": embed_data,
        "description": f"Unlock content {content.id}",
        "callback_url": callback_url,
        "redirect_url": return_url,
        "mac": mac,
    }

    transaction = PaymentTransaction.objects.create(
        user=request.user,
        content=content,
        amount=amount,
        currency="VND",
        provider="ZALOPAY",
        status=PaymentTransaction.Status.PENDING,
        app_trans_id=app_trans_id,
        app_time=app_time,
    )

    try:
        response_data = _post_zalopay_create(payload)
    except Exception as exc:
        logger.exception("ZaloPay create failed: %s", exc)
        transaction.status = PaymentTransaction.Status.FAILED
        transaction.save(update_fields=["status", "updated_at"])
        messages.error(request, "Payment service is unavailable.")
        return redirect("library:content-detail", pk=content_id)

    transaction.raw_callback = response_data
    return_code = str(response_data.get("return_code") or "")
    order_url = response_data.get("order_url") or response_data.get("orderurl")
    if return_code != "1" or not order_url:
        transaction.status = PaymentTransaction.Status.FAILED
        transaction.save(update_fields=["status", "raw_callback", "updated_at"])
        messages.error(request, response_data.get("return_message", "Payment failed."))
        return redirect("library:content-detail", pk=content_id)

    transaction.save(update_fields=["raw_callback", "updated_at"])
    return redirect(order_url)


@require_GET
def points_home(request):
    packages = PointPackage.objects.filter(is_active=True).order_by("sort_order", "points")
    return render(request, "gating/points.html", {"packages": packages})


@login_required
@require_POST
def zalopay_topup(request, package_id):
    package = get_object_or_404(PointPackage, pk=package_id, is_active=True)
    if not settings.ZALOPAY_APP_ID or not settings.ZALOPAY_KEY1:
        messages.error(request, "ZaloPay is not configured.")
        return redirect("gating:points")

    callback_url = settings.ZALOPAY_TOPUP_CALLBACK_URL or request.build_absolute_uri(
        reverse("gating:points-callback")
    )
    return_url = settings.ZALOPAY_TOPUP_RETURN_URL or request.build_absolute_uri(
        reverse("gating:points-return")
    )

    app_time = int(time.time() * 1000)
    app_trans_id = _build_unique_app_trans_id()
    app_user = str(request.user.id)
    amount = int(package.price_vnd)

    items = json.dumps(
        [
            {
                "itemid": package.id,
                "itemname": package.name,
                "itemprice": amount,
                "itemquantity": 1,
            }
        ]
    )
    embed_data = json.dumps(
        {
            "package_id": package.id,
            "points": package.points,
            "return_url": return_url,
        }
    )

    mac_data = "|".join(
        [
            str(settings.ZALOPAY_APP_ID),
            app_trans_id,
            app_user,
            str(amount),
            str(app_time),
            embed_data,
            items,
        ]
    )
    mac = _sign_hmac(settings.ZALOPAY_KEY1, mac_data)

    payload = {
        "app_id": settings.ZALOPAY_APP_ID,
        "app_user": app_user,
        "app_trans_id": app_trans_id,
        "app_time": app_time,
        "amount": amount,
        "item": items,
        "embed_data": embed_data,
        "description": f"Top up {package.points} points",
        "callback_url": callback_url,
        "redirect_url": return_url,
        "mac": mac,
    }

    transaction = PointTopupTransaction.objects.create(
        user=request.user,
        package=package,
        points=package.points,
        amount=amount,
        currency="VND",
        provider="ZALOPAY",
        status=PointTopupTransaction.Status.PENDING,
        app_trans_id=app_trans_id,
        app_time=app_time,
    )

    try:
        response_data = _post_zalopay_create(payload)
    except Exception as exc:
        logger.exception("ZaloPay topup create failed: %s", exc)
        transaction.status = PointTopupTransaction.Status.FAILED
        transaction.save(update_fields=["status", "updated_at"])
        messages.error(request, "Payment service is unavailable.")
        return redirect("gating:points")

    transaction.raw_callback = response_data
    return_code = str(response_data.get("return_code") or "")
    order_url = response_data.get("order_url") or response_data.get("orderurl")
    if return_code != "1" or not order_url:
        transaction.status = PointTopupTransaction.Status.FAILED
        transaction.save(update_fields=["status", "raw_callback", "updated_at"])
        messages.error(request, response_data.get("return_message", "Payment failed."))
        return redirect("gating:points")

    transaction.save(update_fields=["raw_callback", "updated_at"])
    return redirect(order_url)


@csrf_exempt
@require_POST
def zalopay_callback(request):
    if not settings.ZALOPAY_KEY2:
        return JsonResponse({"return_code": -1, "return_message": "Missing key2"})

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"return_code": 0, "return_message": "Invalid JSON"})

    data = payload.get("data") or ""
    mac = payload.get("mac") or ""
    if not data or not mac:
        return JsonResponse({"return_code": 0, "return_message": "Missing data"})

    expected_mac = _sign_hmac(settings.ZALOPAY_KEY2, data)
    if expected_mac != mac:
        return JsonResponse({"return_code": -1, "return_message": "Invalid mac"})

    try:
        data_obj = json.loads(data)
    except json.JSONDecodeError:
        return JsonResponse({"return_code": 0, "return_message": "Invalid data"})

    app_trans_id = data_obj.get("app_trans_id")
    if not app_trans_id:
        return JsonResponse({"return_code": 0, "return_message": "Missing app_trans_id"})

    try:
        transaction = PaymentTransaction.objects.select_related("content", "user").get(
            app_trans_id=app_trans_id
        )
    except PaymentTransaction.DoesNotExist:
        return JsonResponse({"return_code": 0, "return_message": "Transaction not found"})

    transaction.raw_callback = data_obj
    zp_trans_id = data_obj.get("zp_trans_id") or data_obj.get("zp_trans_token") or ""
    if zp_trans_id:
        transaction.zp_trans_id = str(zp_trans_id)

    status_value = str(
        data_obj.get("status")
        or data_obj.get("return_code")
        or data_obj.get("result_code")
        or ""
    )

    if transaction.status != PaymentTransaction.Status.PAID and status_value == "1":
        transaction.status = PaymentTransaction.Status.PAID
        transaction.save(update_fields=["status", "zp_trans_id", "raw_callback", "updated_at"])
        Unlock.objects.get_or_create(
            content=transaction.content,
            user=transaction.user,
            defaults={
                "method": Unlock.Method.PAYMENT,
                "cost_points": 0,
            },
        )
        return JsonResponse({"return_code": 1, "return_message": "success"})

    if transaction.status == PaymentTransaction.Status.PENDING and status_value != "1":
        transaction.status = PaymentTransaction.Status.FAILED
        transaction.save(update_fields=["status", "zp_trans_id", "raw_callback", "updated_at"])

    return JsonResponse({"return_code": 1, "return_message": "success"})


@csrf_exempt
@require_POST
def zalopay_topup_callback(request):
    if not settings.ZALOPAY_KEY2:
        return JsonResponse({"return_code": -1, "return_message": "Missing key2"})

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"return_code": 0, "return_message": "Invalid JSON"})

    data = payload.get("data") or ""
    mac = payload.get("mac") or ""
    if not data or not mac:
        return JsonResponse({"return_code": 0, "return_message": "Missing data"})

    expected_mac = _sign_hmac(settings.ZALOPAY_KEY2, data)
    if expected_mac != mac:
        return JsonResponse({"return_code": -1, "return_message": "Invalid mac"})

    try:
        data_obj = json.loads(data)
    except json.JSONDecodeError:
        return JsonResponse({"return_code": 0, "return_message": "Invalid data"})

    app_trans_id = data_obj.get("app_trans_id")
    if not app_trans_id:
        return JsonResponse({"return_code": 0, "return_message": "Missing app_trans_id"})

    try:
        with db_transaction.atomic():
            topup = (
                PointTopupTransaction.objects.select_for_update()
                .select_related("user")
                .get(app_trans_id=app_trans_id)
            )
            topup.raw_callback = data_obj
            zp_trans_id = data_obj.get("zp_trans_id") or data_obj.get("zp_trans_token") or ""
            if zp_trans_id:
                topup.zp_trans_id = str(zp_trans_id)

            amount_value = int(data_obj.get("amount") or 0)
            if amount_value and amount_value != int(topup.amount):
                topup.status = PointTopupTransaction.Status.FAILED
                topup.save(update_fields=["status", "raw_callback", "zp_trans_id", "updated_at"])
                logger.warning(
                    "ZaloPay topup amount mismatch for %s: %s != %s",
                    app_trans_id,
                    amount_value,
                    topup.amount,
                )
                return JsonResponse({"return_code": 0, "return_message": "Invalid amount"})

            status_value = str(
                data_obj.get("status")
                or data_obj.get("return_code")
                or data_obj.get("result_code")
                or ""
            )

            if topup.status != PointTopupTransaction.Status.PAID and status_value == "1":
                topup.status = PointTopupTransaction.Status.PAID
                if not topup.points_awarded:
                    PointLedger.record(
                        topup.user,
                        topup.points,
                        f"Top up {topup.points} points",
                    )
                    topup.points_awarded = True
                topup.save(
                    update_fields=[
                        "status",
                        "points_awarded",
                        "zp_trans_id",
                        "raw_callback",
                        "updated_at",
                    ]
                )
                return JsonResponse({"return_code": 1, "return_message": "success"})

            if topup.status == PointTopupTransaction.Status.PENDING and status_value != "1":
                topup.status = PointTopupTransaction.Status.FAILED
                topup.save(update_fields=["status", "raw_callback", "zp_trans_id", "updated_at"])
                return JsonResponse({"return_code": 1, "return_message": "success"})

            topup.save(update_fields=["raw_callback", "zp_trans_id", "updated_at"])
            return JsonResponse({"return_code": 1, "return_message": "success"})
    except PointTopupTransaction.DoesNotExist:
        return JsonResponse({"return_code": 0, "return_message": "Transaction not found"})


@require_GET
def zalopay_return(request):
    app_trans_id = (request.GET.get("app_trans_id") or "").strip()
    if not app_trans_id:
        messages.info(request, "Payment is processing. Please check again shortly.")
        return redirect("library:home")

    try:
        transaction = PaymentTransaction.objects.select_related("content").get(
            app_trans_id=app_trans_id
        )
    except PaymentTransaction.DoesNotExist:
        messages.info(request, "Payment is processing. Please check again shortly.")
        return redirect("library:home")

    if transaction.status == PaymentTransaction.Status.PAID:
        messages.success(request, "Payment successful. Content unlocked.")
    elif transaction.status == PaymentTransaction.Status.FAILED:
        messages.error(request, "Payment failed or was cancelled.")
    else:
        messages.info(request, "Payment is processing. Please refresh later.")

    return redirect("library:content-detail", pk=transaction.content_id)


@require_GET
def zalopay_topup_return(request):
    app_trans_id = (request.GET.get("app_trans_id") or "").strip()
    if not app_trans_id:
        messages.info(request, "Payment is processing. Please check again shortly.")
        return redirect("gating:points")

    try:
        topup = PointTopupTransaction.objects.get(app_trans_id=app_trans_id)
    except PointTopupTransaction.DoesNotExist:
        messages.info(request, "Payment is processing. Please check again shortly.")
        return redirect("gating:points")

    if topup.status == PointTopupTransaction.Status.PAID:
        messages.success(request, "Top up successful. Points have been added.")
    elif topup.status == PointTopupTransaction.Status.FAILED:
        messages.error(request, "Payment failed or was cancelled.")
    else:
        messages.info(request, "Payment is processing. Please refresh later.")

    return redirect("gating:points")
