# printsphere_m5

This layer adapts `printsphere_core` to the M5Stack StopWatch factory firmware.
It must use the existing HAL and Mooncake lifecycle instead of initializing a
display, touch controller, PMU, audio device, LVGL, Wi-Fi event loop, or OTA
policy of its own.

The current runtime is a lifecycle skeleton. Shared Wi-Fi and storage adapters
will be added before MQTT/cloud clients are enabled.
