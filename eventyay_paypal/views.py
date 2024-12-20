import contextlib
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http import HTTPStatus

from django.contrib import messages
from django.core import signing
from django.db.models import Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_scopes import scopes_disabled
from pretix.base.models import Event, Order, OrderPayment, OrderRefund, Quota
from pretix.base.payment import PaymentException
from pretix.control.permissions import event_permission_required
from pretix.multidomain.urlreverse import eventreverse

from .models import ReferencedPayPalObject
from .payment import Paypal
from .utils import safe_get

logger = logging.getLogger("pretix.plugins.eventyay_paypal")


@xframe_options_exempt
def redirect_view(request, *args, **kwargs):
    signer = signing.Signer(salt="safe-redirect")
    try:
        url = signer.unsign(request.GET.get("url", ""))
    except signing.BadSignature:
        return HttpResponseBadRequest("Invalid parameter")

    r = render(
        request,
        "plugins/paypal/redirect.html",
        {
            "url": url,
        },
    )
    r._csp_ignore = True
    return r


@scopes_disabled()
def oauth_return(request, *args, **kwargs):
    """
    https://developer.paypal.com/docs/multiparty/seller-onboarding/before-payment/
    Reference for seller onboarding
    """
    required_params = [
        "merchantId",
        "merchantIdInPayPal",
        "permissionsGranted",
        "consentStatus",
        "isEmailConfirmed",
    ]
    required_session_params = [
        "payment_paypal_oauth_event",
        "payment_paypal_tracking_id",
    ]
    if any(p not in request.session for p in required_session_params) or any(
        p not in request.GET for p in required_params
    ):
        messages.error(
            request,
            _("An error occurred during connecting with PayPal, please try again."),
        )
        return redirect(reverse("control:index"))

    event = get_object_or_404(Event, pk=request.session.get("payment_paypal_oauth_event"))
    event.settings.payment_paypal_connect_user_id = request.GET.get("merchantId")
    event.settings.payment_paypal_merchant_id = request.GET.get("merchantIdInPayPal")

    messages.success(
        request,
        _(
            "Your PayPal account is now connected to Eventyay. You can change the settings in "
            "detail below."
        ),
    )

    return redirect(
        reverse(
            "control:event.settings.payment.provider",
            kwargs={
                "organizer": event.organizer.slug,
                "event": event.slug,
                "provider": "paypal",
            },
        )
    )


def success(request, *args, **kwargs):
    token = request.GET.get("token")
    payer = request.GET.get("PayerID")
    request.session["payment_paypal_token"] = token
    request.session["payment_paypal_payer"] = payer

    urlkwargs = {}
    if "cart_namespace" in kwargs:
        urlkwargs["cart_namespace"] = kwargs["cart_namespace"]

    if request.session.get("payment_paypal_payment"):
        payment = OrderPayment.objects.get(
            pk=request.session.get("payment_paypal_payment")
        )
    else:
        payment = None

    if request.session.get("payment_paypal_order_id", None):
        if payment:
            prov = Paypal(request.event)
            try:
                resp = prov.execute_payment(request, payment)
            except PaymentException as e:
                messages.error(request, str(e))
                urlkwargs["step"] = "payment"
                return redirect(
                    eventreverse(
                        request.event, "presale:event.checkout", kwargs=urlkwargs
                    )
                )
            if resp:
                return resp
    else:
        messages.error(request, _("Invalid response from PayPal received."))
        logger.error("Session did not contain payment_paypal_order_id")
        urlkwargs["step"] = "payment"
        return redirect(
            eventreverse(request.event, "presale:event.checkout", kwargs=urlkwargs)
        )

    if payment:
        return redirect(
            eventreverse(
                request.event,
                "presale:event.order",
                kwargs={"order": payment.order.code, "secret": payment.order.secret},
            )
            + ("?paid=yes" if payment.order.status == Order.STATUS_PAID else "")
        )
    urlkwargs["step"] = "confirm"
    return redirect(
        eventreverse(request.event, "presale:event.checkout", kwargs=urlkwargs)
    )


def abort(request, *args, **kwargs):
    messages.error(request, _("It looks like you canceled the PayPal payment"))

    if request.session.get("payment_paypal_payment"):
        payment = OrderPayment.objects.get(
            pk=request.session.get("payment_paypal_payment")
        )
    else:
        payment = None

    if payment:
        return redirect(
            eventreverse(
                request.event,
                "presale:event.order",
                kwargs={"order": payment.order.code, "secret": payment.order.secret},
            )
            + ("?paid=yes" if payment.order.status == Order.STATUS_PAID else "")
        )
    else:
        return redirect(
            eventreverse(
                request.event, "presale:event.checkout", kwargs={"step": "payment"}
            )
        )


def check_webhook_signature(request, event, event_json, prov) -> bool:
    """
    Verifies the signature of a webhook from PayPal.

    :param request: The current request object
    :param event: The event object
    :param event_json: The json payload of the webhook
    :param prov: The payment provider instance
    :return: True if the signature is valid, False otherwise
    """

    required_headers = [
        "PAYPAL-AUTH-ALGO",
        "PAYPAL-CERT-URL",
        "PAYPAL-TRANSMISSION-ID",
        "PAYPAL-TRANSMISSION-SIG",
        "PAYPAL-TRANSMISSION-TIME",
    ]
    if any(header not in request.headers for header in required_headers):
        logger.error("Paypal webhook missing required headers")
        return False

    # Prevent replay attacks: check timestamp
    current_time = datetime.now(timezone.utc)
    transmission_time = datetime.fromisoformat(
        request.headers.get("PAYPAL-TRANSMISSION-TIME")
    )
    if current_time - transmission_time > timedelta(minutes=7):
        logger.error("Paypal webhook timestamp is too old.")
        return False

    verify_response = prov.paypal_request_handler.verify_webhook_signature(
        data={
            "auth_algo": request.headers.get("PAYPAL-AUTH-ALGO"),
            "transmission_id": request.headers.get("PAYPAL-TRANSMISSION-ID"),
            "cert_url": request.headers.get("PAYPAL-CERT-URL"),
            "transmission_sig": request.headers.get("PAYPAL-TRANSMISSION-SIG"),
            "transmission_time": request.headers.get("PAYPAL-TRANSMISSION-TIME"),
            "webhook_id": event.settings.payment_paypal_webhook_id,
            "webhook_event": event_json,
        }
    )

    if (
        verify_response.get("errors")
        or safe_get(verify_response, ["response", "verification_status"], "")
        == "FAILURE"
    ):
        errors = verify_response.get("errors")
        logger.error("Unable to verify signature of webhook: %s", errors["reason"])
        return False
    return True


def parse_webhook_event(request, event_json):
    """
    Parse the given webhook event and return the corresponding event, payment ID and RPO.

    :param request: The current request object
    :param event_json: The json payload of the webhook
    :return: A tuple of (event, payment_id, referenced_paypal_object)
    """
    event = None
    payment_id = None
    if event_json["resource_type"] == "refund":
        for link in event_json["resource"]["links"]:
            if link["rel"] == "up":
                refund_url = link["href"]
                payment_id = refund_url.split("/")[-1]
                break
    else:
        payment_id = event_json["resource"]["id"]

    references = [payment_id]

    # For filtering reference, there are a lot of ids appear within json__event
    if ref_order_id := (
        safe_get(
            event_json,
            ["resource", "supplementary_data", "related_ids", "order_id"]
        )
    ):
        references.append(ref_order_id)

    # Grasp the corresponding RPO
    rpo = (
        ReferencedPayPalObject.objects.select_related("order", "order__event")
        .filter(reference__in=references)
        .first()
    )

    if rpo:
        event = rpo.order.event
        if "id" in rpo.payment.info_data:
            payment_id = rpo.payment.info_data["id"]
    elif hasattr(request, "event"):
        event = request.event

    return event, payment_id, rpo


def extract_order_and_payment(payment_id, event, event_json, prov, rpo=None):
    """
    Extracts order details and associated payment information from PayPal webhook data.

    :param payment_id: The ID of the payment to be extracted.
    :param event: The event object associated with the payment.
    :param event_json: The JSON payload of the webhook event.
    :param prov: The payment provider instance.
    :param rpo: Optional. The referenced PayPal object containing order and payment information.

    :returns: A tuple containing the order details and the payment object.
              Returns (None, None) if an error occurs while retrieving order details.
    """
    order_detail = None
    payment = None

    order_response = prov.paypal_request_handler.get_order(order_id=payment_id)
    if errors := order_response.get("errors"):
        logger.error("Paypal error on webhook: %s", errors["reason"])
        logger.exception("PayPal error on webhook. Event data: %s", str(event_json))
        return order_detail, payment

    order_detail = order_response.get("response")

    if rpo and rpo.payment:
        payment = rpo.payment
    else:
        payments = OrderPayment.objects.filter(
            order__event=event, provider="paypal", info__icontains=order_detail.get("id")
        )
        payment = None
        for p in payments:
            if (
                "info_data" in p
                and "purchase_units" in p.info_data
                and p.info_data["purchase_units"]
            ):
                for capture in safe_get(
                    p.info_data["purchase_units"][0], ["payments", "captures"], []
                ):
                    if capture.get("status") in [
                        "COMPLETED",
                        "PARTIALLY_REFUNDED",
                    ] and capture.get("id") == order_detail.get("id"):
                        payment = p
                        break

    return order_detail, payment


@csrf_exempt
@require_POST
@scopes_disabled()
def webhook(request, *args, **kwargs):
    """
    https://developer.paypal.com/api/rest/webhooks/event-names/
    Webhook reference
    """
    event_body = request.body.decode("utf-8").strip()
    event_json = json.loads(event_body)

    if event_json.get("resource_type") not in ("checkout-order", "refund", "capture"):
        return HttpResponse("Wrong resource type", status=HTTPStatus.BAD_REQUEST)

    event, payment_id, rpo = parse_webhook_event(request, event_json)
    if event is None:
        return HttpResponse("Unable to get event from webhook", status=HTTPStatus.BAD_REQUEST)

    prov = Paypal(event)

    # Verify signature
    if not check_webhook_signature(request, event, event_json, prov):
        return HttpResponse("Unable to verify signature of webhook", status=HTTPStatus.BAD_REQUEST)

    order_detail, payment = extract_order_and_payment(
        payment_id, event, event_json, prov, rpo
    )
    if order_detail is None or payment is None:
        return HttpResponse("Order or payment not found", status=HTTPStatus.BAD_REQUEST)

    payment.order.log_action("pretix.plugins.eventyay_paypal.event", data=event_json)

    def handle_refund():
        refund_id_in_event = safe_get(event_json, ["resource", "id"])
        refund_response = prov.paypal_request_handler.get_refund_detail(
            refund_id=refund_id_in_event,
            merchant_id=event.settings.payment_paypal_merchant_id,
        )
        if errors := refund_response.get("errors"):
            logger.error("Paypal error on webhook: %s", errors["reason"])
            logger.exception("PayPal error on webhook. Event data: %s", str(event_json))
            return HttpResponse(
                f'Refund {refund_id_in_event} not found', status=HTTPStatus.BAD_REQUEST
            )

        refund_detail = refund_response.get("response")
        if refund_id := refund_detail.get("id"):
            known_refunds = {
                refund.info_data.get("id"): refund for refund in payment.refunds.all()
            }
            if refund_id not in known_refunds:
                payment.create_external_refund(
                    amount=abs(
                        Decimal(safe_get(refund_detail, ["amount", "value"], "0.00"))
                    ),
                    info=json.dumps(refund_detail),
                )
            elif know_refund := known_refunds.get(refund_id):
                if (
                    know_refund.state
                    in (
                        OrderRefund.REFUND_STATE_CREATED,
                        OrderRefund.REFUND_STATE_TRANSIT,
                    )
                    and refund_detail.get("status", "") == "COMPLETED"
                ):
                    know_refund.done()

            seller_payable_breakdown_value = safe_get(
                refund_detail,
                ["seller_payable_breakdown", "total_refunded_amount", "value"],
                "0.00",
            )
            known_sum = payment.refunds.filter(
                state__in=(
                    OrderRefund.REFUND_STATE_DONE,
                    OrderRefund.REFUND_STATE_TRANSIT,
                    OrderRefund.REFUND_STATE_CREATED,
                    OrderRefund.REFUND_SOURCE_EXTERNAL,
                )
            ).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
            total_refunded_amount = Decimal(seller_payable_breakdown_value)
            if known_sum < total_refunded_amount:
                payment.create_external_refund(amount=total_refunded_amount - known_sum)

    def handle_payment_state_confirmed():
        if event_json.get("resource_type") == "refund":
            handle_refund()
        elif order_detail.get("status") == "REFUNDED":
            known_sum = payment.refunds.filter(
                state__in=(
                    OrderRefund.REFUND_STATE_DONE,
                    OrderRefund.REFUND_STATE_TRANSIT,
                    OrderRefund.REFUND_STATE_CREATED,
                    OrderRefund.REFUND_SOURCE_EXTERNAL,
                )
            ).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
            if known_sum < payment.amount:
                payment.create_external_refund(amount=payment.amount - known_sum)

    def handle_payment_state_pending():
        if order_detail.get("status") == "APPROVED":
            try:
                request.session["payment_paypal_order_id"] = payment.info_data.get("id")
                payment.payment_provider.execute_payment(request, payment)
            except PaymentException as e:
                logger.error(
                    "Error executing approved payment in webhook: payment not yet populated."
                )
                logger.exception("Unable to execute payment in webhook: %s", str(e))
        elif order_detail.get("status") == "COMPLETED":
            captured = False
            captures_completed = True
            for purchase_unit in order_detail.get("purchase_units", []):
                for capture in safe_get(purchase_unit, ["payment", "captures"], []):
                    with contextlib.suppress(
                        ReferencedPayPalObject.MultipleObjectsReturned
                    ):
                        ReferencedPayPalObject.objects.get_or_create(
                            order=payment.order,
                            payment=payment,
                            reference=capture.get("id"),
                        )
                    if capture.get("status") in (
                        "COMPLETED",
                        "REFUNDED",
                        "PARTIALLY_REFUNDED",
                    ):
                        captured = True
                    else:
                        captures_completed = False
            if captured and captures_completed:
                with contextlib.suppress(Quota.QuotaExceededException):
                    payment.info = json.dumps(order_detail)
                    payment.save(update_fields=["info"])
                    payment.confirm()

    if payment.state == OrderPayment.PAYMENT_STATE_CONFIRMED and order_detail[
        "status"
    ] in ("PARTIALLY_REFUNDED", "REFUNDED", "COMPLETED"):
        handle_payment_state_confirmed()
    elif payment.state in (
        OrderPayment.PAYMENT_STATE_PENDING,
        OrderPayment.PAYMENT_STATE_CREATED,
        OrderPayment.PAYMENT_STATE_CANCELED,
        OrderPayment.PAYMENT_STATE_FAILED,
    ):
        handle_payment_state_pending()

    return HttpResponse(status=HTTPStatus.OK)


@event_permission_required("can_change_event_settings")
@require_POST
def oauth_disconnect(request, **kwargs):
    del request.event.settings.payment_paypal_connect_user_id
    del request.event.settings.payment_paypal_merchant_id
    request.event.settings.payment_paypal__enabled = False
    messages.success(request, _("Your PayPal account has been disconnected."))

    return redirect(
        reverse(
            "control:event.settings.payment.provider",
            kwargs={
                "organizer": request.event.organizer.slug,
                "event": request.event.slug,
                "provider": "paypal",
            },
        )
    )
