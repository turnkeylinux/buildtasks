# Shared 19.0 maintenance patch

Apply this standard TKLPatch to a pristine, mounted Debian 13 amd64 TurnKey 19.0 root. The committed conf/packages.json pins five runtime packages and three minimum floors to public signed APT bytes. Existing running servers receive these packages through APT. The ISO-only installer stays in the native installer stage.

From a specific published buildtasks main revision, build the ordinary patch archive:

```sh
PATCH_EPOCH=$(git show -s --format=%ct "$MAIN")
git archive --format=tar --mtime="@$PATCH_EPOCH" --prefix=library-19.0-hotfix/ "$MAIN:patches/library-19.0-hotfix" | gzip -n > library-19.0-hotfix.tar.gz
sudo tklpatch-apply "$ROOTFS" library-19.0-hotfix.tar.gz
```

The caller runs in an isolated mount namespace, provides working resolver/proc/dev/sys/run mounts and a policy-rc.d that returns 101, and preserves their original files/metadata for restoration, including failure cleanup. Qualify the public tklpatch 0.95 commands on Core and LAMP before release. The audited 84e0cdf source documents the standard advanced conf hook; apply-conf copies packages.json alongside post-overlay. The conf keeps authenticated APT, refuses mismatched candidate hashes, refreshes metadata only when a required candidate is absent, preserves conffiles and refuses package removal. Newer minimum-floor versions remain installed.

TKLPatch owns shared runtime/config mutations and its normal cache cleanup. The format caller then applies the app identity, its reviewed overlay through tklpatch-apply-overlay and aptconf-tag, restores policy/resolver fixtures, removes temporary tooling and completes final cleanup. Generate the genuine canonical profile only afterward from the exact final pristine filesystem. Keep app identity/profile/publication metadata outside this common patch.

Preserve the source ISO’s validated BIOS/ISOLINUX and isohybrid MBR layout with `tklpatch-prepare-cdroot` and `tklpatch-geniso`. Native ISO/PVE use mounted-root tklpatch-apply; AWS volume/snapshot/AMI/region lifecycle remains in the existing controller. Freeze this archive hash as shared_patch, with source_main equal to controller_main, in the per-image input manifest. Fresh technical identities are ISO 19.0.3.10, PVE 19.0.3.11 and EC2 19.0.3.12 (public 19.0.3); retain every older published image/profile unchanged.
