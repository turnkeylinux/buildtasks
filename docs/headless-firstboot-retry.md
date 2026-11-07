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
