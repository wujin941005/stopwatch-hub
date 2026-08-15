# PrintSphere M5Stack adapter

This layer exposes the complete pinned PrintSphere v1.6.2 application as a
Mooncake App. The generated port uses the existing M5Stack HAL and `hub_wifi`
instead of initializing a second display, touch controller, PMU, codec, I2C
bus, LVGL task, NVS stack, default event loop or Wi-Fi driver.

The long-lived application task keeps printer state available. App open/close
controls the private LVGL root, camera/preview pipelines, brightness and an
app-scoped display-rotation lease. Uploaded sounds live below
`/spiflash/printsphere/sounds`; Web Config listens on port 8080; OTA accepts
only the combined `StopWatch-UserDemo` image.
