# Bambu Status app

Mooncake/LVGL presentation layer for the PrintSphere-derived port. The app
constructs and deletes only its own LVGL tree and delegates long-lived state to
`printsphere_m5`.

The first slice deliberately shows a setup-required state. It verifies app
registration, clean lifecycle teardown, core linkage, and an independent
launcher icon before Bambu networking is introduced.
