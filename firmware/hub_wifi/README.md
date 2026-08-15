# hub_wifi

Process-wide ESP-IDF Wi-Fi station owner for StopWatch Hub. CC Island polling
uses it now; Bambu Status MQTT/cloud clients must reuse it later.

M5Stack's built-in badge configuration portal temporarily switches the global
driver into access-point mode. The installer adds pause/resume hooks so the
station does not reconnect during that session and is restored afterwards.
