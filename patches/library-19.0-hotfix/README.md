# Shared 19.0 maintenance patch

Apply this standard TKLPatch to a pristine, mounted Debian 13 amd64 TurnKey 19.0 root. For 19.0.4, resolve the shared package candidates once from the signed Debian and TurnKey APT repositories. Keep the resulting archive and JSON receipt for all formats and retries in that batch. The committed `conf/packages.json` preserves the historical 19.0.3 inputs.

On a Debian 13 preparation system, use the normal image's APT source and preference directories and their trusted keyrings. Assemble the patch from the selected committed Buildtasks main revision:

```sh
bin/prepare-library-hotfix --revision "$MAIN" \
    --sources /etc/apt/sources.list.d --preferences /etc/apt/preferences.d \
    --output library-19.0-hotfix.tar.gz > shared-packages.json
sudo tklpatch-apply "$ROOTFS" library-19.0-hotfix.tar.gz
```

The caller runs in an isolated mount namespace with a working resolver, proc/dev/sys/run mounts, and a policy-rc.d that returns 101. Preserve the original files and metadata for restoration. Qualify the public tklpatch 0.95 commands on Core and LAMP before release. The patch verifies authenticated APT package hashes and installs the resolved versions while preserving conffiles. It stops if a selected version disappears or would require a downgrade. It also requires root to pass `sudo -n -- id -u` with result `0`.

After package updates, the patch applies the qualified native Webmin SSH Include fix and migrates any legacy EC2 policy filename while preserving access choices and metadata. Identical copies collapse; conflicting custom copies stop the patch. This component comes from turnkey-common main `fab5756728697c408000572cffced769a9c5b45a` and the qualified `ec2-ssh-access-20261116` artifact (SHA256 `f29d4593c3d7e93456c290024ac1e08c3c97036fff244a90c722d601d0d4b30b`). The EC2 caller separately supplies missing factory defaults and retains admin/sudo initialization. Hub user-data applies the user’s selected password policy after security updates and backup restore.

TKLPatch owns shared runtime/config mutations and its normal cache cleanup. The format caller then applies the app identity, its reviewed overlay through tklpatch-apply-overlay and aptconf-tag, restores policy/resolver fixtures, removes temporary tooling and completes final cleanup. ISO and EC2 callers apply `patches/clean-old-kernels` before final packaging or snapshotting. EC2 callers then unmount and zero unused ext4 blocks before taking the snapshot. Generate the genuine canonical profile only afterward from the exact final pristine filesystem. Keep app identity/profile/publication metadata outside this common patch.

Preserve the source ISO’s validated BIOS/ISOLINUX and isohybrid MBR layout with `tklpatch-prepare-cdroot` and `tklpatch-geniso`. Native ISO/PVE use mounted-root tklpatch-apply. The existing controller manages AWS volumes, snapshots, AMIs and regions. Freeze this archive hash as shared_patch, with source_main equal to controller_main, in the per-image input manifest. Use the public 19.0.4 label across delivery channels and allocate matching internal build identities and profile references. Retain backup-profile metadata for existing installations after retiring superseded image bytes.
