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
install -d "$bt/bin" "$bt/config" "$profiles" "$commands"
cp "$repo/bin/iso-release" "$repo/bin/generate-tklbam-profile" "$bt/bin/"
printf 'core profile\n' > "$profiles/core"
printf 'tkldev profile\n' > "$profiles/tkldev"

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

make_product() {
    local case_name=$1
    local product=$fixture/$case_name/product
    local rootfs=$product/build/root.sandbox
    install -d "$rootfs/usr/lib/tklbam-pypy2/bin" \
        "$rootfs/usr/lib/tklbam" "$rootfs/var/lib/dpkg" \
        "$fixture/$case_name/output"
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
    cat > "$rootfs/usr/lib/tklbam-pypy2/bin/pypy" <<'EOF'
#!/bin/bash
set -eu

generator=$1
rootfs=$2
output=$3
[[ $generator == "$TEST_GENERATOR" ]]
[[ $PROFILES_CONF == "$TEST_PROFILES" ]]
[[ $TKLBAM_LIB_PATH == "$rootfs/usr/lib/tklbam" ]]
printf 'root:%s:%s\n' "$rootfs" "$output" >> "$TEST_LOG"
if [[ -n ${TEST_ROOT_RUNTIME_FAIL:-} ]]; then
    exit "$TEST_ROOT_RUNTIME_FAIL"
fi

archive_root=$(mktemp -d)
cleanup_archive() {
    rm -rf -- "$archive_root"
}
trap cleanup_archive EXIT
printf 'dirindex\n' > "$archive_root/dirindex"
printf 'dirindex conf\n' > "$archive_root/dirindex.conf"
awk '
    /^Package: / { package = $2 }
    /^Status: install ok installed$/ &&
        package !~ /^(di-live|tkl-installer|live-boot|live-boot-initramfs-tools|live-tools)$/ {
            print package
        }
' "$rootfs/var/lib/dpkg/status" | sort > "$archive_root/packages"
tar -C "$archive_root" -zcf "$output/$TEST_NAME.tar.gz" .
EOF
    chmod 0755 "$rootfs/usr/lib/tklbam-pypy2/bin/pypy"
    printf '%s\n' "$product"
}

run_release() {
    local product=$1
    local output=$2
    local runtime_fail=${3:-}
    (
        cd "$product"
        export PATH="$commands:$PATH"
        export TEST_BT_PROFILES=$profiles
        export TEST_GENERATOR=$bt/bin/generate-tklbam-profile
        export TEST_LOG=$log
        export TEST_NAME=$name
        export TEST_PROFILES=$profiles
        export TEST_ROOT_RUNTIME_FAIL=$runtime_fail
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
! find "$root_product/build/root.sandbox" -name 'buildtasks-tklbam-profile.*' \
    -print -quit | grep -q .

: > "$log"
failure_product=$(make_product failure)
set +e
run_release "$failure_product" "$fixture/failure/output" 37
status=$?
set -e
[[ $status -eq 37 ]]
grep -q '^root:' "$log"
[[ ! -e "$fixture/failure/output/$name.tklbam/$name.tar.gz" ]]
! find "$failure_product/build/root.sandbox" -name 'buildtasks-tklbam-profile.*' \
    -print -quit | grep -q .
