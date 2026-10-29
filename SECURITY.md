# Security

## Reporting a vulnerability

Please report suspected vulnerabilities **privately to the repository owner** using a private channel agreed with them, or the repository's private vulnerability reporting feature if it is enabled. Do not open a public issue with exploit details, credentials or personal data. No dedicated security contact or response timeline has been specified; if a private channel is not available, ask the owner how to report without disclosing sensitive details.

Include a minimal reproduction with synthetic data, affected code and potential impact. Do not test against another person's account, submit a real order, or disclose live session material. Avoid raw upstream payloads and logs: even redacted machine codes can be sensitive.

## Protect local state

QR images and links are temporary login credentials. Cookies, session files, preview tokens, exact addresses, payment identifiers, order IDs, cart contents, SQLite databases and captured responses may contain credentials or private information. Store state owner-only in a trusted directory, use trusted local MCP clients, and never commit or publish this material. Client logs and chat history can retain information outside the server's control.

A compromised session may permit account access or consequential actions. Use the account provider's official session-management process to revoke access if you suspect exposure, and remove exposed material from places you control. Do not assume deleting a local file revokes an upstream session. For an uncertain checkout or cancellation, consult [the checkout guide](docs/checkout.md); do not clear guards or retry blindly.
