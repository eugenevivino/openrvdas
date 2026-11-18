# ADCP health and cross-checks

These transforms provide a listen-only view of ADCP health. They never open a
socket, write a setting, or send a command to an ADCP, UHDAS, or VmDAS.

`PD0SummaryTransform` validates and summarizes raw PD0 ensembles. Ask the ADCP
operator for a receive-only serial split or an existing network rebroadcast of
the ADCP output. Never tap or connect to the command line, because UHDAS or
VmDAS owns it. Configure an OpenRVDAS `SerialReader` or `UDPReader` with null
encoding so it delivers bytes, then pass those bytes to the transform. The
required `beam_angle_deg` is 30 for an Ocean Surveyor and 20 for a Workhorse.

**Verify the layout against a real capture on the pilot ship.** The offsets and
scales are isolated in `pd0_layout.yaml`, based on the public Teledyne RDI
Commands and Output Data Format manuals. Ocean Surveyor, Workhorse, and
Pinnacle use these selected leader fields, but firmware and output selection
must still be confirmed with captured data.

`ADCPCrossCheckTransform` maps configured field names to roles. It compares
ADCP heading with gyro and GNSS, sound speed with TSG and probe values, bottom
track depth with multibeam nadir depth, and ensemble timing with multibeam or
EK80 pings. A heading error rotates velocity components and therefore becomes
a cross-track velocity error. A steady sound-speed offset often indicates a
fixed EC value. Lost bottom track removes an independent depth check. Ping
overlap is only a five-minute diagnostic hint for transmit awareness and
K-Sync, never a control signal.

Thresholds use degrees, metres per second, and percent. Persistence and clear
delays suppress flicker. Evaluation uses record timestamps, so replaying the
same ordered records produces the same alarm decisions. Missing and stale
sources are reported, not estimated. The transforms copy incoming fields and
only add output fields. They do not calculate velocity profiles or currents.

Operator alarm text identifies the failed check, observed values, limit, and a
suggested next step. For a frozen heading feed it directs the operator to check
the heading feed into UHDAS. For other alarms, compare the named sensor values
and verify the configured role mapping before changing any shipboard system.

## Inputs and outputs

PD0 input may be bytes, a record containing a byte field, a list, or `None`.
The parser accepts split and concatenated ensembles, checks every offset,
requires the checksum, skips unknown data types, and caps buffered input at 64
KiB. It emits ensemble attitude, clock, BIT, sound-speed, transducer-depth, and
bottom-track summary fields plus checksum and resynchronization counters.

The cross-check accepts `DASRecord` or dictionary records. Its `roles` mapping
names `adcp_heading`, `gyro_heading`, `gnss_heading`, `adcp_sv`, `tsg_sv`,
`probe_sv`, `adcp_bt_depth`, `mb_depth`, `adcp_time`, `mb_ping_time`, and
`ek_ping_time`. See the demo configuration for a complete mapping.
