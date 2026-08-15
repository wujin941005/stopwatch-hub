# printsphere_core

This directory contains the hardware-independent portion of the PrintSphere
port. Files derived from PrintSphere are licensed under FNCL v1.1; see
`LICENSES/FNCL-1.1.txt` and `NOTICE.md` at the repository root.

The first imported slice contains the printer snapshot/store and Bambu status
normalization/model mapping. Network clients will be moved here only after
their Wi-Fi and lifecycle dependencies have explicit platform interfaces.
