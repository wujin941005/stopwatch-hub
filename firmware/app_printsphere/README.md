# PrintSphere Mooncake app

This directory owns the PrintSphere Mooncake lifecycle and the factory go-home
input. The complete pinned PrintSphere application runs behind
`printsphere_m5`.

`onCreate` starts process-lifetime printer state services. `onOpen` reveals the
PrintSphere LVGL root and resumes App-scoped display policy. `onClose` hides the
root, restores official display/brightness state, and pauses camera and preview
work while low-rate printer status services may stay warm.
