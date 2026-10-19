# Controller, firmware and MPTool (identify and guide only)

Mass-production tools (MPTool) for flash controllers (Phison, SMI, Alcor, Chipsbank, Innostor and others) rewrite
firmware, bad-block tables, capacity and VID/PID. The tool version must match the exact controller revision and the
NAND flash id; a mismatch gives wrong capacity or a bricked device, and every run erases all data. The skill:

- collects identifiers read-only (VID/PID, controller vendor/model, flash id from ChipGenius / ChipEasy, which must
  agree), records them with `rs.py session note <sid> <text>`, and points to lookup resources (flashboot.ru iFlash
  is a VID/PID + flash id database; the same VID/PID spans several models, so VID/PID alone is never enough);
- never chooses firmware or a tool by brand or capacity, never downloads or runs firmware from an unverified source;
- requires an image or backup first, the exact controller id and the tool provenance in the gate
  (`--controller-id`, `--tool-source`), and leaves the flashing to the operator.

SSD firmware panics (for example a SATA SSD presenting as `SATAFIRM S11`) are lab cases: vendor labs report that OS
tools cannot read them and that a firmware update may overwrite the translation layer.

### Method: Vendor firmware update
- Preconditions: data secured; the vendor tool identifies the exact model and current firmware; release notes name
  the fix; downloaded from the vendor site with checksum.
- Risk: R2 (gate kind: firmware-update)
- Tool: the vendor's own updater (for example the SSD maker's toolbox); `--controller-id` and `--tool-source`
  recorded in the gate
- Expected result: new firmware version reported by `rs.py collect`; health unchanged or better.
- Stop criteria: the tool does not recognise the exact model, the source cannot be verified, power is unstable.

### Method: Reflash a flash controller with an MPTool
- Preconditions: data secured or abandoned; controller and flash id confirmed by two tools; MPTool version matched
  to both from a verifiable source; operator accepts the risk of a bricked device.
- Risk: R2 (gate kind: mptool-reflash)
- Tool: controller-specific MPTool (Windows GUI), run by the operator
- Expected result: device enumerates with the configured capacity; then a full verify (F3/H2testw) before any use.
- Stop criteria: identifiers disagree, the tool does not list the controller, any doubt about provenance; never try
  a second random tool after a failure.
