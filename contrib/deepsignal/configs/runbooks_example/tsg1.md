---
stream: tsg1
endpoint: /dev/tty_tsg1
baud: 9600
format: SBE21
power: Science rack PDU A, outlet 4
spare_location: Main lab, instrument spares cabinet, shelf 2
escalation: Call the on-watch marine technician, then the science systems manager.
causes:
  - check: Confirm the PDU outlet and SBE 21 display are on.
    fix: Reset outlet 4 once, then replace the power supply from spares.
    stages: [read]
  - check: Confirm /dev/tty_tsg1 points to the expected serial server channel.
    fix: Restore the serial server mapping and restart the tsg1 logger.
    stages: [read]
  - check: Compare a raw line with the active SBE21 parser definition.
    fix: Select the matching parser definition and preserve the raw sample with the alarm.
    stages: [parse]
owner: Marine technician
---
# Thermosalinograph 1

The SBE 21 receives water from the uncontaminated seawater line. Check flow before changing software.
The expected wiring runs from serial server channel 7 to the science rack patch panel and then the SBE 21.
