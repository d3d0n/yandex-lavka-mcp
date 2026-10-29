"""Conservative read-only observations, not proof of order reconciliation.

The request path is named by the storefront frontend; its Uzbekistan response
format remains unverified. Never use an empty result to clear an uncertain order.
"""
import logging
import os
import re
import asyncio

from lavka_uz import BASE, Lavka, create_http


class ObservationError(Exception):
    pass


def summarize_active_orders(data):
    if not isinstance(data, dict) or not isinstance(data.get("orders"), list):
        raise ObservationError("Unrecognized active-order response; no conclusion possible")
    statuses = []
    for item in data["orders"]:
        if not isinstance(item, dict) or not isinstance(item.get("status"), str) or not re.fullmatch(r"[a-z_]{1,40}", item["status"]):
            raise ObservationError("Unrecognized order status; no conclusion possible")
        statuses.append(item["status"])
    return {"active_order_count": len(statuses), "statuses": statuses}


async def observe():
    logging.disable(logging.CRITICAL)
    if not os.environ.get("YANDEX_SESSION_FILE"):
        raise ObservationError("Set YANDEX_SESSION_FILE to the authorized Uzbekistan session")
    async with create_http() as http:
        props = await Lavka(http).bootstrap()
        if props.get("pageData", {}).get("passportInfo", {}).get("status") != "VALID":
            raise ObservationError("Authenticated Uzbekistan session required")
        headers = {
            "Origin": BASE, "Referer": BASE + "/", "X-Requested-With": "XMLHttpRequest",
            "X-Csrf-Token": props.get("authProxyCsrfToken") or "",
            "X-Csrf-Token-Bff": props.get("csrfToken") or "",
        }
        try:
            response = await http.get(BASE + "/api/v1/providers/orders-tracking/v1/tracked-orders", headers=headers)
            if response.status_code != 200:
                raise ObservationError(f"Active-order endpoint HTTP {response.status_code}")
            return summarize_active_orders(response.json())
        except ObservationError:
            raise
        except Exception:
            raise ObservationError("Active-order read failed or was not JSON") from None


if __name__ == "__main__":
    try:
        print(asyncio.run(observe()))
    except ObservationError as exc:
        raise SystemExit(str(exc)) from None
