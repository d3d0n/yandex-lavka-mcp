# Yandex Lavka Uzbekistan MCP

**A local MCP server for exploring and managing a Yandex Lavka Uzbekistan cart—with explicit controls around consequential writes.**

Unofficial · Uzbekistan ordering; RU/KZ anonymous search · Python · stdio

> [!WARNING]
> This server can modify a real cart, submit a paid order, and request cancellation. Its order and cancellation MCP paths are tested with mocked upstream responses, **not a new live MCP transaction**. Official-site transactions were observed separately; they do not prove this implementation works end to end. Use only with trusted clients, review every consequential action, and never retry an uncertain write blindly.

## From a question to a cart

Connect a local MCP client, then ask it to search for products at a location in Uzbekistan. It can read the cart, show masked saved-card suffixes and quote a checkout. Cart updates and ordering are separate actions; a quote is neither a reservation nor a payment.

| Capability | Tools | Boundary |
|---|---|---|
| Discover | `select_region`, `delivery_location`, `detect_delivery_location`, `service_status`, `suggest_address`, `search_products` | `select_region`, `service_status` and `search_products` accept explicit RU/KZ/UZ; other discovery tools remain UZ-only. Homepage status and suggestions do not establish address coverage. |
| Sign in | `login_start`, `qr_login_status`, `qr_login_cancel` | Private, short-lived QR login; see [authentication](docs/auth.md). |
| Cart | `get_cart`, `set_cart_item`, `checkout_preview` | Coordinates are longitude, latitude; a cart quote does not select an address or card. `set_cart_item` is a real write. |
| Account and orders | `saved_address_count`, `saved_addresses`, `saved_cards`, `active_orders`, `order_history` | Address details and order identifiers are private. Active tracking is not history. |
| Checkout | `order_preview`, `submit_order`, `reconcile_checkout`, `cancel_order` | Explicit confirmation and careful reconciliation are essential; see [checkout](docs/checkout.md). |

Prices, availability and delivery charges change. The server uses undocumented web APIs that may change or reject requests, and it is not affiliated with Yandex. Country-level currency confirmation does not prove coverage at an individual address.

## Country and delivery location

Choose a startup country when adding the MCP server by setting `YANDEX_LAVKA_REGION` to `UZ`, `RU`, or `KZ`; if omitted it defaults to `UZ`. Any other value prevents startup. See [client setup](docs/clients.md) for configuration examples. At any time call `select_region(country="RU")` (or `KZ` or `UZ`) to change the default for `service_status` and `search_products`. Selection is in memory for this stdio server process only; it is not written to a shared file and resets to the configured startup value when restarted. Use a separate server process per client session; this is not per-client isolation for a shared multi-client server.

`service_status(country="RU")` and `search_products(country="KZ", longitude=..., latitude=...)` explicitly override the selected country for that read only, without changing the selection. RU/KZ reads use fresh anonymous country-specific sessions and confirm currency. Login, address suggestions, location helpers, cart, payments and checkout are UZ-only and are refused while RU/KZ is selected. A region change is rejected while a UZ tool is in flight; retry after it completes, especially for an order with an uncertain outcome. Switching itself places no order. No country is inferred from IP or device geolocation.

For a delivery location, call `delivery_location(country="UZ", longitude=..., latitude=...)`, or use `detect_delivery_location(country="UZ")` with an authenticated session. Detection returns candidate coordinates only when exactly one favorite exists; zero or multiple favorites require an explicit choice. For multiple favorites, review `saved_addresses` and pass its freshly obtained `address_index` to `detect_delivery_location`. Alternatively, use `suggest_address` and choose an address with usable coordinates. Indexes can change and similar favorites may differ in apartment details; verify the exact address before checkout.

These tools are stateless: changing location means passing the new coordinates to **each** search, cart and quote call. They do not update the account's address, select a checkout address, or persist a default. Refresh search and cart after a change; old prices and carts may be stale and cart identity may be shared across locations. Review the exact saved address again in `order_preview`. The bounding box is only a coarse input check, not proof that the coordinates lie in Uzbekistan or that delivery is available. Coordinates and saved addresses are private; use a trusted client and beware client logs.

## Get started

Install [mise](https://mise.jdx.dev/getting-started.html) first. From the repository root on a Unix-like system:

```sh
mise trust
mise install
mise run install
mise run test
.venv/bin/yandex-lavka-mcp
```

`mise` manages `uv`; the install task uses `uv` to install a managed Python 3.12 and synchronize dependencies from `uv.lock`. The test task runs the offline suite.

The last command starts an MCP **stdio** server; it waits for an MCP client and is not an interactive CLI. Stop it with Ctrl-C. For a client, configure the virtual environment's Python as the command and the absolute path to `lavka_uz.py` as its argument. See [client setup](docs/clients.md) for a JSON example and connection checks.

Ask your client to call `login_start` when authenticated access is needed, then scan its QR code in the Yandex app or open its link, and poll `qr_login_status`. **The QR image and link are temporary credentials**: use a private, trusted client and channel; clients and chat logs may retain them. An existing session is not replaced unless explicitly requested.

## Safety in practice

- Confirm the exact item and quantity before a cart write. Quantities are absolute; zero removes an item. An ambiguous result calls for a fresh cart read, not an automatic retry.
- Before an order, review the exact saved address, items, total in UZS, masked card and delivery in `order_preview`; obtain explicit user approval for those terms. The preview expires and can change before submission.
- An order ID is not proof of payment. A cancellation response is not proof of cancellation or refund. Check the exact order in the official app and inspect payment independently.
- The local duplicate-order guard does not cover other clients or installations. Unknown outcomes can be delayed; empty active tracking is not proof that no order exists. [Read the recovery procedure](docs/checkout.md).

## Documentation

- [Client setup and connection checks](docs/clients.md)
- [Authentication and session security](docs/auth.md)
- [Cart, checkout, tracking and cancellation](docs/checkout.md)
- [Contributing and tests](CONTRIBUTING.md) · [Security reporting](SECURITY.md)

The root-level research notes are historical and may describe older implementations; where they conflict, use the current source and these operational guides.

## License

[GNU General Public License v3.0 only](LICENSE) (GPL-3.0-only).
