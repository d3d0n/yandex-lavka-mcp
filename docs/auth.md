# Authentication

Authenticated cart, account and order operations require a valid Yandex Passport Uzbekistan session. The server defaults to `~/.local/share/yandex-lavka-mcp/session.json`; set `YANDEX_SESSION_FILE` to choose another cookie-jar path. Cookies retain their original domain scope: a `.ru` session is not widened into a `.uz` session. Other state, including checkout previews and guards, remains under `~/.local/share/yandex-lavka-mcp/` regardless of that override.

## QR login

1. In a trusted private MCP client, explicitly call `login_start`. It returns a QR image and a link for the same pending login.
2. Scan using the Yandex app or open the link on your phone and approve the sign-in.
3. Poll `qr_login_status` until the flow finishes. The session is saved only after the server verifies it with Lavka. Use `qr_login_cancel` to stop a pending flow.
4. Replacing an existing session requires explicit approval and `login_start(replace_existing=true)`.

`qr_login_cancel` works even after selecting RU or KZ; switching regions does not automatically cancel a pending QR. Its local expiry is checked when login is started or polled, not by a background timer. Cancel before stopping or restarting the server: pending login state is process-local, and a restart does not recover it or guarantee deletion of leftover QR or staged-session files. Remove any such credential files privately if needed; the upstream link may remain valid until it expires.

**The QR image, link and session file are credentials.** Anyone with access while valid may be able to authenticate. Send them only to the intended account holder over a private channel. Client logs, transcripts, screenshots and image caches can retain them even though the server suppresses HTTP request logging. Do not post them in issues or commit them. Store session and state files in a trusted owner-only directory and restrict file access. Sharing a machine or client can expose the account; use a separate authorized session for another user.

Login may expire, be rejected or require additional upstream action. The undocumented service can change without notice. A successful login does not establish that a particular saved address is serviceable or that an order has been paid. See [checkout](checkout.md).
