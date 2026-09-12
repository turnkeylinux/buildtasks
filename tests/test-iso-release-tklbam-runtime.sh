#!/bin/bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || {
    echo "this fixture must run as root inside LibreSBX" >&2
    exit 1
}

repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
host_pypy=/usr/lib/tklbam-pypy2/bin/pypy
host_parent_created=
host_pypy_created=

cleanup() {
    if [[ -n "$host_pypy_created" ]]; then
        rm -f -- "$host_pypy"
    fi
    if [[ -n "$host_parent_created" ]]; then
        rmdir /usr/lib/tklbam-pypy2/bin /usr/lib/tklbam-pypy2 2>/dev/null || true
    fi
    rm -rf -- "$fixture"
}
trap cleanup EXIT

[[ ! -e "$host_pypy" ]] || {
    echo "$host_pypy already exists in the test sandbox" >&2
    exit 1
}

bt=$fixture/buildtasks
profiles=$fixture/profiles
commands=$fixture/bin
log=$fixture/calls
name=turnkey-tkldev-19.0-trixie-amd64
install -d "$bt/bin" "$bt/config" "$profiles/hooks/tkldev" "$commands"
cp "$repo/bin/iso-release" "$repo/bin/generate-tklbam-profile" "$bt/bin/"
printf 'core profile\n' > "$profiles/core"
printf 'tkldev profile\n' > "$profiles/tkldev"
printf 'profile hook\n' > "$profiles/hooks/tkldev/profile-hook"

cat > "$bt/config/common.cfg" <<'EOF'
export BT_PROFILES=${TEST_BT_PROFILES:?}
EOF

for helper in generate-signature generate-manifest generate-buildenv; do
    cat > "$bt/bin/$helper" <<'EOF'
#!/bin/bash
case "$(basename "$0")" in
    generate-manifest) echo manifest ;;
    generate-buildenv) echo buildenv ;;
esac
EOF
    chmod 0755 "$bt/bin/$helper"
done

cat > "$commands/turnkey-version" <<EOF
#!/bin/bash
if [[ " \$* " == *" --name "* ]]; then
    echo tkldev
else
    echo $name
fi
EOF
chmod 0755 "$commands/turnkey-version"

cat > "$commands/fab-chroot" <<'EOF'
#!/bin/bash
set -eu

[[ $# -eq 5 ]]
[[ $1 == -e ]]
[[ $2 == PROFILES_CONF:TKLBAM_LIB_PATH:LD_LIBRARY_PATH ]]
rootfs=$3
[[ $4 == --script ]]
wrapper=$5
[[ $PROFILES_CONF == /var/tmp/buildtasks-tklbam-profile.*/profiles ]]
[[ $TKLBAM_LIB_PATH == /usr/lib/tklbam ]]
[[ $LD_LIBRARY_PATH == /usr/lib/tklbam-pypy2/bin ]]
stage=${PROFILES_CONF%/profiles}
guest_profiles=$PROFILES_CONF
guest_generator=$stage/generate-tklbam-profile
guest_output=$stage/output
[[ $wrapper == "$rootfs$stage/run-tklbam-profile" ]]
[[ -x $rootfs/usr/lib/tklbam-pypy2/bin/pypy ]]

cmp -s "$TEST_PROFILES/core" "$rootfs$guest_profiles/core"
cmp -s "$TEST_PROFILES/tkldev" "$rootfs$guest_profiles/tkldev"
cmp -s "$TEST_PROFILES/hooks/tkldev/profile-hook" \
    "$rootfs$guest_profiles/hooks/tkldev/profile-hook"

expected=$(mktemp)
mapped=$(mktemp)
cleanup_fab() {
    rm -f -- "$expected" "$mapped"
}
trap cleanup_fab EXIT
cat > "$expected" <<EXPECTED
#!/bin/bash
exec /usr/lib/tklbam-pypy2/bin/pypy "$guest_generator" / "$guest_output"
EXPECTED
cmp -s "$expected" "$wrapper"
sed "s|^exec /usr/lib/tklbam-pypy2/bin/pypy |exec $TEST_PYPY |" \
    "$wrapper" > "$mapped"
chmod 0755 "$mapped"
TEST_ROOTFS=$rootfs "$mapped"

archive_root=$(mktemp -d)
trap 'rm -rf -- "$archive_root"; cleanup_fab' EXIT
printf 'dirindex\n' > "$archive_root/dirindex"
printf 'dirindex conf\n' > "$archive_root/dirindex.conf"
awk '
    /^Package: / { package = $2 }
    /^Status: install ok installed$/ &&
        package !~ /^(di-live|tkl-installer|live-boot|live-boot-initramfs-tools|live-tools)$/ {
            print package
        }
' "$rootfs/var/lib/dpkg/status" | sort > "$archive_root/packages"
tar -C "$archive_root" -zcf "$rootfs$guest_output/$TEST_NAME.tar.gz" .
EOF
chmod 0755 "$commands/fab-chroot"

cat > "$commands/root-pypy" <<'EOF'
#!/bin/bash
set -eu

guest_generator=$1
[[ $2 == / ]]
guest_output=$3
cmp -s "$TEST_GENERATOR" "$TEST_ROOTFS$guest_generator"
printf 'root:%s:%s\n' "$guest_generator" "$guest_output" >> "$TEST_LOG"
if [[ -n ${TEST_CHROOT_FAIL:-} ]]; then
    exit "$TEST_CHROOT_FAIL"
fi
EOF
chmod 0755 "$commands/root-pypy"

cat > "$commands/cp" <<'EOF'
#!/bin/bash
set -eu
if [[ -n ${TEST_COPY_FAIL:-} && " $* " == *'/buildtasks-tklbam-profile.'*'/output/. '* ]]; then
    exit "$TEST_COPY_FAIL"
fi
exec /bin/cp "$@"
EOF
chmod 0755 "$commands/cp"

make_product() {
    local case_name=$1
    local product=$fixture/$case_name/product
    local rootfs=$product/build/root.sandbox
    install -d "$rootfs/usr/lib/tklbam-pypy2/bin" \
        "$rootfs/usr/lib/tklbam" "$rootfs/var/lib/dpkg" "$rootfs/var/tmp" \
        "$fixture/$case_name/output"
    install -m 0755 /bin/true "$rootfs/usr/lib/tklbam-pypy2/bin/pypy"
    printf 'changelog\n' > "$product/changelog"
    printf 'iso\n' > "$product/build/product.iso"
    cat > "$rootfs/var/lib/dpkg/status" <<'EOF'
Package: bash
Status: install ok installed

Package: live-tools
Status: install ok installed

Package: tkl-installer
Status: install ok installed

Package: removed-package
Status: deinstall ok config-files
EOF
    printf '%s\n' "$product"
}

run_release() {
    local product=$1
    local output=$2
    local chroot_fail=${3:-}
    local copy_fail=${4:-}
    (
        cd "$product"
        export PATH="$commands:$PATH"
        export TEST_BT_PROFILES=$profiles
        export TEST_CHROOT_FAIL=$chroot_fail
        export TEST_COPY_FAIL=$copy_fail
        export TEST_GENERATOR=$bt/bin/generate-tklbam-profile
        export TEST_LOG=$log
        export TEST_NAME=$name
        export TEST_PYPY=$commands/root-pypy
        export TEST_PROFILES=$profiles
        "$bt/bin/iso-release" --no-screens "$output"
    )
}

install_host_pypy() {
    if [[ ! -d /usr/lib/tklbam-pypy2 ]]; then
        host_parent_created=yes
    fi
    install -d /usr/lib/tklbam-pypy2/bin
    cat > "$host_pypy" <<'EOF'
#!/bin/bash
set -eu
printf 'host:%s\n' "$*" >> "$TEST_LOG"
[[ $1 == "$TEST_GENERATOR" ]]
archive_root=$(mktemp -d)
trap 'rm -rf -- "$archive_root"' EXIT
printf 'host runtime\n' > "$archive_root/runtime"
tar -C "$archive_root" -zcf "$3/$TEST_NAME.tar.gz" .
EOF
    chmod 0755 "$host_pypy"
    host_pypy_created=yes
}

remove_host_pypy() {
    rm -f -- "$host_pypy"
    host_pypy_created=
    if [[ -n "$host_parent_created" ]]; then
        rmdir /usr/lib/tklbam-pypy2/bin /usr/lib/tklbam-pypy2
        host_parent_created=
    fi
}

assert_no_stage() {
    ! find "$1/build/root.sandbox/var/tmp" -mindepth 1 -maxdepth 1 \
        -name 'buildtasks-tklbam-profile.*' -print -quit | grep -q .
}

: > "$log"
install_host_pypy
host_product=$(make_product host)
run_release "$host_product" "$fixture/host/output"
grep -q '^host:' "$log"
! grep -q '^root:' "$log"
[[ -f "$fixture/host/output/$name.tklbam/$name.tar.gz" ]]
remove_host_pypy

: > "$log"
root_product=$(make_product root)
run_release "$root_product" "$fixture/root/output"
grep -q '^root:' "$log"
archive=$fixture/root/output/$name.tklbam/$name.tar.gz
[[ -f "$archive" ]]
tar -tzf "$archive" | grep -qx './dirindex'
tar -tzf "$archive" | grep -qx './dirindex.conf'
tar -tzf "$archive" | grep -qx './packages'
tar -xOzf "$archive" ./packages | grep -qx bash
! tar -xOzf "$archive" ./packages | grep -Eq '^(live-tools|tkl-installer)$'
assert_no_stage "$root_product"

: > "$log"
failure_product=$(make_product failure)
set +e
run_release "$failure_product" "$fixture/failure/output" 37
status=$?
set -e
[[ $status -eq 37 ]]
grep -q '^root:' "$log"
[[ ! -e "$fixture/failure/output/$name.tklbam/$name.tar.gz" ]]
assert_no_stage "$failure_product"

: > "$log"
copy_product=$(make_product copy-failure)
set +e
run_release "$copy_product" "$fixture/copy-failure/output" '' 41
status=$?
set -e
[[ $status -eq 41 ]]
grep -q '^root:' "$log"
[[ ! -e "$fixture/copy-failure/output/$name.tklbam/$name.tar.gz" ]]
assert_no_stage "$copy_product"
