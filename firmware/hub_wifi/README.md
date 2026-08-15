# hub_wifi

Process-wide ESP-IDF Wi-Fi owner for StopWatch Hub. CC Island HTTP polling and
the complete PrintSphere LAN/cloud clients share this one driver, event loop,
STA netif and AP netif.

It accepts build-time CC Island credentials and runtime credentials persisted
by PrintSphere, supports STA/APSTA transitions, scans, reconnects and a
PrintSphere fallback setup AP. M5Stack's Badge configuration page temporarily
takes exclusive AP ownership; the installer adds suspend/resume hooks and then
restores the shared station without creating duplicate default netifs.
