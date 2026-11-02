# Courier route in Yandex Navigator

The owner chose “Hammasi birga Yandex Navigator’da ochilsin”. A deliberate
tap on the courier map tab opens one route in Navigator. An individual order
map opens that order's destination in the same app. Restoring the map view
or refreshing the board must not launch an external app.

Include all active orders with a valid map pin, excluding pickup, delivered
and cancelled orders. Use the existing nearest-next ordering from the
courier's fresh position, while retaining explicit manual ordering/exclusions.
If location is unavailable, Navigator uses its own current location; the panel
continues to explain how to grant location access for nearest-first ordering.

Send all selected destinations as zero-based via points and a final destination,
with the known origin when available. Do not split at ten stops or silently
truncate at twenty-five. Navigator is the automatic app; Maps is only an
explicit fallback. If Navigator is absent, offer its installation.

Approaches: Go's documented links carry a single destination; Maps-first
launching does not meet the selected app preference. The chosen approach is
the existing HTTPS bridge with Navigator-first native links, preserving the
current Telegram integration and desktop web fallback.

No changes to orders, stock, payments, authorization or deployment settings.
Device app launches cannot be proven by a desktop test. Yandex documents a
five-launch daily limit for unsigned Navigator links; lifting that limit needs
a Yandex-issued client and signing key, which this project does not configure.

References: https://yandex.ru/dev/navigator/doc/ru/concepts/navigator-url-params
and https://yandex.ru/dev/navigator/doc/ru/concepts/navigator-commercial-use.
