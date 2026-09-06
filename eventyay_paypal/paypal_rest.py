import base64
import hashlib
import json
import logging
import time
import urllib.parse
import uuid
from http import HTTPMethod

import requests
from cryptography.fernet import Fernet
from django.core.cache import cache

from .utils import (
    build_paypal_auth_assertion,
    paypal_error_reason,
    resolve_paypal_api_base,
    uses_paypal_connect,
)

logger = logging.getLogger(__name__)


class PaypalRequestHandler:
    def __init__(self, settings):
        self.settings = settings
        if uses_paypal_connect(settings):
            self.connect_client_id = self.settings.connect_client_id
            self.secret_key = self.settings.connect_secret_key
            endpoint_setting = self.settings.connect_endpoint
        else:
            self.connect_client_id = self.settings.get("client_id")
            self.secret_key = self.settings.get("secret")
            endpoint_setting = self.settings.get("endpoint") or "live"

        self.set_cache_token_key()
        self.endpoint = resolve_paypal_api_base(endpoint_setting)

        self.oauth_url = urllib.parse.urljoin(self.endpoint, "v1/oauth2/token")
        self.partner_referrals_url = urllib.parse.urljoin(self.endpoint, "v2/customer/partner-referrals")
        self.order_url = urllib.parse.urljoin(self.endpoint, "v2/checkout/orders/{order_id}")
        self.create_order_url = urllib.parse.urljoin(self.endpoint, "v2/checkout/orders")
        self.capture_order_url = urllib.parse.urljoin(self.endpoint, "v2/checkout/orders/{order_id}/capture")
        self.refund_detail_url = urllib.parse.urljoin(self.endpoint, "v2/payments/refunds/{refund_id}")
        self.refund_payment_url = urllib.parse.urljoin(self.endpoint, "v2/payments/captures/{capture_id}/refund")
        self.verify_webhook_url = urllib.parse.urljoin(self.endpoint, "v1/notifications/verify-webhook-signature")

        self.paypal_request_id = self.get_paypal_request_id()

    def request(
        self,
        url: str,
        method: HTTPMethod,
        data=None,
        params=None,
        headers=None,
        timeout=15,
    ) -> dict:
        reason = ""
        response_data = {}
        try:
            if method == HTTPMethod.GET:
                response = requests.get(url, data=data, params=params, headers=headers, timeout=timeout)
            elif method == HTTPMethod.POST:
                response = requests.post(url, data=data, params=params, headers=headers, timeout=timeout)
            elif method == HTTPMethod.PATCH:
                response = requests.patch(url, data=data, params=params, headers=headers, timeout=timeout)
            else:
                response_data["errors"] = {
                    "type": "UnsupportedMethod",
                    "reason": f"Unsupported HTTP method: {method}",
                    "exception": None,
                }
                return response_data

            reason = paypal_error_reason(response, fallback=response.reason)
            response.raise_for_status()

            if method == HTTPMethod.PATCH:
                return {"response": {}}

            if "application/json" not in response.headers.get("Content-Type", ""):
                response_data["errors"] = {
                    "type": "UnparseableResponse",
                    "reason": reason,
                    "exception": "Response is not json parseable",
                }
                return response_data

            response_data["response"] = response.json()
            return response_data
        except requests.exceptions.ReadTimeout as e:
            response_data["errors"] = {
                "type": "ReadTimeout",
                "reason": reason or "PayPal request timed out",
                "exception": e,
            }
            return response_data
        except requests.exceptions.RequestException as e:
            response_data["errors"] = {
                "type": "Ambiguous",
                "reason": reason or str(e),
                "exception": e,
            }
            return response_data

    @staticmethod
    def check_expired_token(access_token_data: dict, buffer_time: int = 300) -> bool:
        current_time = time.time()
        expiration_time = access_token_data["created_at"] + access_token_data["expires_in"]
        return (current_time + buffer_time) > expiration_time

    @staticmethod
    def encode_b64(connect_client_id: str, connect_secret_key: str) -> str:
        key = f"{connect_client_id}:{connect_secret_key}"
        return base64.b64encode(key.encode("ascii")).decode("ascii")

    def set_cache_token_key(self) -> None:
        if self.connect_client_id and self.secret_key:
            hash_code = hashlib.sha256("".join([self.connect_client_id, self.secret_key]).encode()).hexdigest()
            self.cache_token_key = f"paypal_token_hash_{hash_code}"
            self.fernet = Fernet(base64.urlsafe_b64encode(hash_code[:32].encode()))
        else:
            self.cache_token_key = None
            self.fernet = None

    def get_paypal_request_id(self):
        return str(uuid.uuid4())

    def get_paypal_auth_assertion(self, merchant_id: str) -> str:
        return build_paypal_auth_assertion(self.connect_client_id, merchant_id)

    def get_access_token(self) -> str | None:
        if not self.cache_token_key or not self.connect_client_id or not self.secret_key:
            logger.error("PayPal API credentials are not configured")
            return None

        def request_new_access_token() -> dict:
            access_token_response = self.request(
                url=self.oauth_url,
                method=HTTPMethod.POST,
                headers={
                    "Authorization": f"Basic {self.encode_b64(self.connect_client_id, self.secret_key)}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials"},
            )

            if errors := access_token_response.get("errors"):
                logger.error("Error getting access token from Paypal: %s", errors["reason"])
                return {}

            access_token_data = access_token_response.get("response") or {}
            if not access_token_data.get("access_token"):
                logger.error("PayPal token response did not include an access token")
                return {}
            access_token_data["created_at"] = time.time()
            encrypted_access_token_data = self.fernet.encrypt(json.dumps(access_token_data).encode())
            cache.set(self.cache_token_key, encrypted_access_token_data, 3600 * 2)
            return access_token_data

        encrypted_access_token_data = cache.get(self.cache_token_key)
        if encrypted_access_token_data is None:
            access_token_data = request_new_access_token()
        else:
            access_token_data = json.loads(self.fernet.decrypt(encrypted_access_token_data).decode())
            if self.check_expired_token(access_token_data):
                access_token_data = request_new_access_token()

        if not access_token_data:
            return None
        return access_token_data.get("access_token")

    def create_partner_referrals(self, data: dict) -> dict:
        return self.request(
            url=self.partner_referrals_url,
            method=HTTPMethod.POST,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.get_access_token()}",
            },
            data=json.dumps(data),
        )

    def get_order(self, order_id: str) -> dict:
        return self.request(
            url=self.order_url.format(order_id=order_id),
            method=HTTPMethod.GET,
            headers={"Authorization": f"Bearer {self.get_access_token()}"},
        )

    def create_order(self, order_data: dict) -> dict:
        return self.request(
            url=self.create_order_url,
            method=HTTPMethod.POST,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.get_access_token()}",
                "PayPal-Request-Id": self.paypal_request_id,
            },
            data=json.dumps(order_data),
        )

    def capture_order(self, order_id: str) -> dict:
        return self.request(
            url=self.capture_order_url.format(order_id=order_id),
            method=HTTPMethod.POST,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.get_access_token()}",
                "PayPal-Request-Id": self.paypal_request_id,
            },
        )

    def update_order(self, order_id: str, update_data: list[dict]) -> dict:
        return self.request(
            url=self.order_url.format(order_id=order_id),
            method=HTTPMethod.PATCH,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.get_access_token()}",
            },
            data=json.dumps(update_data),
        )

    def get_refund_detail(self, refund_id: str, merchant_id: str) -> dict:
        return self.request(
            url=self.refund_detail_url.format(refund_id=refund_id),
            method=HTTPMethod.GET,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.get_access_token()}",
                "PayPal-Auth-Assertion": self.get_paypal_auth_assertion(merchant_id),
            },
        )

    def refund_payment(
        self,
        capture_id: str,
        refund_data: dict,
        merchant_id: str = None,
    ) -> dict:
        return self.request(
            url=self.refund_payment_url.format(capture_id=capture_id),
            method=HTTPMethod.POST,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.get_access_token()}",
                "PayPal-Auth-Assertion": self.get_paypal_auth_assertion(merchant_id),
                "PayPal-Request-Id": self.paypal_request_id,
            },
            data=json.dumps(refund_data),
        )

    def verify_webhook_signature(self, data: dict) -> dict:
        return self.request(
            url=self.verify_webhook_url,
            method=HTTPMethod.POST,
            data=json.dumps(data),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.get_access_token()}",
            },
        )
