# Interactive retry after automatic headless setup

Headless builds generate temporary random preseeds when no configuration was
supplied. If a required setup hook fails, the runner retains that configuration
for diagnosis. A later normal `turnkey-init` must ask for customer choices rather
than silently reusing those temporary credentials.

`29preseed` records the generated configuration's SHA256 in
`${INITHOOKS_CONF}.headless-generated.sha256`. Both newly generated files are
root-only (0600). On interactive initialization, the hook discards the temporary
configuration only when its contents still match that provenance, then consumes
the sidecar. Supplied preseeds and operator-edited generated configurations are
preserved. Successful finalization blanks the configuration; a later interactive
run preserves that blank file and consumes the stale sidecar. Missing files and
repeated retries are harmless.

This belongs to the headless image build overlay. An older image without the
provenance sidecar cannot safely distinguish generated fallback values from
customer input, so this hook does not guess or delete its configuration. Build
and validate a fresh candidate to establish the corrected recovery path.

Focused checks execute the actual Bash hook with private installation paths:

```sh
python3 -m unittest discover -s tests -p test_headless_preseed.py -v
```

They cover fallback generation followed by a required-hook failure and
interactive prompting, supplied and edited preseeds, successful finalization,
missing or invalid provenance, private modes and repeated retry. Actual platform
firstboot/failure recovery remains a separate runtime acceptance case.

## First login while automatic setup is running

The headless login profile keeps its single dtach command and shared interactive
socket. The command now starts `turnkey-init-first-login`, which waits for the
automatic inithooks unit to settle before opening interactive setup. The waiting
message explains Ctrl-C cancellation; canceling leaves automatic setup and its
protection unchanged.

A boot unit that never executed, including a condition-skipped PVE/LXC unit,
reaches interactive setup promptly. After an automatic execution, the helper
checks the unit result, the firstboot flag and the latest required-hook outcome.
A failed or incomplete automatic run displays the log location and supported
manual retry command instead of silently retrying. This matters because the
headless unit's shell wrapper can report success after its runner failed.

The single-command profile remains compatible with `turnkey-sudoadmin`, which
prefixes each line with sudo and rewrites the root socket path for admin. The
helper belongs to the headless build overlay; direct administrator invocations
of `turnkey-init` retain their existing behavior.

Focused tests cover waiting, skipped/failed units, preserved original failure,
normal completion, cancellation and the copied admin profile. A harmless local
barrier reproduction with the actual dispatch loops and dtach first demonstrated
overlap, then verified that the guarded admin profile entered its hook only
after automatic execution ended. No database or credential operation was used,
and this does not attribute the earlier missing-socket exception to overlap.
The immediate path uses one unit-state query and no polling; only an active or
queued automatic run waits.

Container units use `Type=oneshot` with `RemainAfterExit=yes`. Their completed
`active/exited` state reaches interactive setup through the same original
firstboot flag and hook-log checks as a completed EC2 unit. Running or queued
units still wait; an exited unit with a failed or incomplete original setup
shows the existing recovery instruction.
