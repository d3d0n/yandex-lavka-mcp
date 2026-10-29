# Contributing

Help is welcome, especially for tests, documentation and careful investigation of upstream changes. This project interacts with an undocumented service and can affect real accounts and payments. Do not run live writes, submit orders or cancel orders as a test without separate, informed authorization for the exact action.

## Local setup

Install [mise](https://mise.jdx.dev/getting-started.html), then from the repository root on a Unix-like system:

```sh
mise trust
mise install
mise run install
mise run test
```

Mise manages uv and runs the project tasks; uv installs the configured managed Python and locked dependencies.

The test suite uses mocked upstream traffic and does not place real orders or change a live cart. A passing test is not proof of live behavior. Keep new tests synthetic; do not record account data or real credentials in fixtures. Run the relevant tests and the full suite before proposing a change, and describe the commands and results.

## Changes and evidence

- Separate read-only behavior from writes, and make assumptions and unverified contracts explicit. Test rejected, uncertain and concurrent outcomes where relevant.
- Preserve explicit approval, one-attempt write behavior, and the distinction between confirmed and ambiguous outcomes. Never weaken guard behavior merely to unblock a test.
- Explain any live evidence's scope and date. Do not claim that a mock proves upstream behavior, that an order ID proves payment, or that an empty active feed proves no order exists.
- Use sanitized, synthetic examples. Do not share session cookies, QR links, tokens, precise addresses, payment identifiers, order IDs, raw requests or responses, or private SQLite state. See [SECURITY.md](SECURITY.md).
- Keep user-facing docs and tests aligned with the code. Older research notes can be historical; check current source before relying on them.

The project is licensed under [GPL-3.0-only](LICENSE). Ensure you have the right to contribute your changes under that license.
