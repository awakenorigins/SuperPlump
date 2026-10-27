# Beat 5 Final Pilot Acceptance Checklist

Scope: no mock pilot acceptance for SuperPlump v1.5.

- [x] Visible pilot auth box in app shell.
- [x] Register/login UI creates backend pilot account and uses one-time 13-char token/JWT session storage.
- [x] Real pilot wallet starts with 1,313 Nara, no fake payment/top-up fallback.
- [x] Five-minute pilot wait gate is visible through `/v1/me/pilot` and UI wait copy.
- [x] Browse drops loads from backend `/v1/drops`, with local mock core data cleared.
- [x] Backend two-user golden path covered: register, age gate, create drop, offer, accept deal, start, submit, confirm, wallet/profile effects.
- [x] Users can resume accepted/in-progress deals after reload via `/v1/me/deals` and UI deal list rendering.
- [x] Service worker cache version bumped to force new UI shell.
- [x] Browser-like deterministic E2E added; skips only if no browser/deps are available.

Blockers: none in source implementation. Runtime E2E depends on local API/database availability.
