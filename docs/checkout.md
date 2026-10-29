# Cart and checkout

> [!CAUTION]
> `set_cart_item`, `submit_order`, and `cancel_order` can change real upstream state. The checkout and cancellation MCP implementation is mock-tested, not validated by a new live MCP order. Official frontend captures are evidence of the observed requests, not proof of MCP end-to-end behavior. Upstream contracts, server-side price enforcement and idempotency remain uncertain.

## Cart and quotes

`get_cart(longitude, latitude)` reads a point-in-time cart. `set_cart_item(longitude, latitude, product_id, quantity, price)` sets the **absolute integer quantity**; zero removes the item. Use the current search price as a string in UZS and confirm the intended change. The server retrieves a fresh cart and verifies the requested quantity, cart identity and preservation of other items after the write. If the result is ambiguous, read the cart and investigate instead of automatically retrying.

`checkout_preview` is a read-only quote at coordinates: it does not select a saved address or card, reserve a price or issue a submission token. Total or availability can be unknown. Coordinates alone do not prove exact address selection.

## Preview and submit

1. Inspect `saved_addresses` and `saved_cards`; select an exact saved-address index and a unique four-digit card suffix. `saved_addresses` includes sensitive details; `saved_cards` exposes masked suffixes and does not itself select a card.
2. Call `order_preview(address_index, card_suffix)`. Review the returned address, items, total UZS, card and delivery with the user. This is not an order. The current implementation supports non-rover, on-demand delivery only.
3. Only after explicit approval of those exact terms, call `submit_order(preview_token, confirmed_total_uzs, explicit_confirmation=true)` using the exact returned total string. The token is single-use and expires after five minutes; preflight re-reads and compares the bound data. If anything changes or expires, obtain and confirm a new preview.

The preflight is local, not a server-side price guarantee. Each attempt is sent at most once. An order ID does not establish successful payment; check official status and payment separately. The local durable guard is not account-wide across other applications or installations.

## Rejection and uncertainty

The server can return a redacted diagnostic projection, not a complete upstream response; even machine-like error codes can be sensitive. A recognized checkout rejection can release the guard. For a recognized `bad_service_fee_v2` or `bad_service_fee` rejection, refresh the cart and preview, compare old and new totals and available item, fee, delivery and availability changes, respect the budget, and obtain fresh explicit approval. The code alone does not prove product prices changed or explain the fee error. Never reuse a consumed token or retry automatically.

A timeout, transport error, or unrecognized response may mean the outcome is **unknown**. The guard quarantines the attempt. Check official order history and payment, confirm no request is in progress, and consider delayed processing and duplicate-order risk. `reconcile_checkout` requires explicit attestations of those checks and risks before releasing the local guard; it does not independently verify them or prove no order exists. Never bypass the guard by deleting or switching state files. Another application can bypass the local guard entirely.

## Tracking and cancellation

`active_orders` is an active tracking feed, not history; an empty feed cannot rule out a delayed or completed order. Nonempty feed entries are counted, not interpreted as a verified order count. `order_history` returns identifiers, timestamps and statuses; its page size is at most 21 and the optional `older_than` cursor must be timezone-aware ISO format. Pagination completeness and ties are not established. Treat identifiers as private.

`cancel_order(order_id, explicit_confirmation=true)` sends at most one cancellation request and quarantines further cancellation attempts. Confirm the exact order and review applicable terms first. A successful HTTP response, including an empty object, does not prove cancellation; verify the exact order in the official app. Refund status and fees are unknown. The cancellation guard has no release workflow: later cancellations require independent reconciliation and an operator-managed solution, not automatic retry or deletion of state.
