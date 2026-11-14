#!/usr/bin/env python3
"""Apply frozen signed-package inputs and generate a pristine EC2 profile."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PACKAGES = {'inithooks', 'turnkey-hub', 'tklbam', 'confconsole', 'webmin-tklbam'}
FLOORS = {'hubdns', 'hubclient', 'webmin'}


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def assets(data):
    yield data['profile_generator']
    yield data['aptconf_tag']
    for row in data['apps'].values():
        yield row['identity_package']
        yield from row['profile_conf'].values()
        yield from row.get('overlay', [])


def asset_path(base, item):
    relative = Path(item['path'])
    require(relative.as_posix() not in ('hotfix.json', 'ec2-hotfix.py'), 'reserved hotfix asset path')
    require(not relative.is_absolute() and '..' not in relative.parts, 'asset path must be relative')
    path = (base / relative).resolve()
    require(path.is_relative_to(base.resolve()) and path.is_file(), 'missing or escaped hotfix asset')
    require(sha(path) == item['sha256'], 'hotfix asset hash differs: ' + item['path'])
    return path


def load(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text())
    require(data['release'] == '19.0.3' and data['technical_release'] == '19.0.3.3', 'unexpected EC2 hotfix identity')
    require(data.get('release_notes', '').strip(), 'release notes are required')
    require(set(data['packages']) == PACKAGES and set(data['minimum_packages']) == FLOORS, 'incomplete package baseline')
    commits = list(data['sources'].values())
    require({'release_main', 'buildtasks_main', 'common_main', 'controller_main'} <= set(data['sources']), 'missing source main revisions')
    for name, item in data['packages'].items():
        require(item['version'] and 'qa' not in item['version'].lower(), 'private package version')
        require(re.fullmatch('[0-9a-f]{64}', item['sha256']), 'invalid package hash')
        commits.append(item['source_main'])
    for app, row in data['apps'].items():
        require(re.fullmatch('[a-z0-9][a-z0-9-]*', app), 'invalid app')
        require(re.fullmatch('ami-[a-f0-9]+', row['source_ami']), 'missing frozen source AMI')
        require(re.fullmatch('snap-[a-f0-9]+', row['source_snapshot']), 'missing frozen source snapshot')
        commits.append(row['source_main'])
        require('core' in row['profile_conf'] and (app == 'core' or app in row['profile_conf']), 'missing canonical profile configuration')
        for name in row['profile_conf']:
            require(name in ('core', app) or (name.startswith('hooks/' + app + '/') and '..' not in Path(name).parts), 'unexpected profile configuration member')
            if name.startswith('hooks/'):
                require(isinstance(row['profile_conf'][name].get('mode'), int), 'hook mode must be preserved explicitly')
        for overlay in row.get('overlay', []):
            require(overlay['target'].startswith('/') and '..' not in Path(overlay['target']).parts, 'unsafe overlay target')
            require(isinstance(overlay['previous_sha256'], list), 'overlay requires accepted previous hashes')
    require(all(re.fullmatch('[0-9a-f]{40}', commit) for commit in commits), 'invalid committed main identity')
    for item in assets(data):
        require(item['source_main'] in commits, 'asset is outside frozen source revisions')
        asset_path(path.parent, item)
    return data


def freeze(source, destination):
    """Retain exact inputs; relative paths keep the bundle usable on workers."""
    source, destination = Path(source).resolve(), Path(destination)
    data = load(source)
    destination.mkdir()
    for item in assets(data):
        target = destination / item['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(asset_path(source.parent, item), target)
    target = destination / 'hotfix.json'
    target.write_bytes(source.read_bytes())
    return target


def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, text=True, capture_output=True, **kwargs).stdout.strip()


def package_version(root, name, optional=False):
    try:
        return run(['chroot', root, 'dpkg-query', '-W', '-f=${Version}', name])
    except subprocess.CalledProcessError as error:
        if optional and error.returncode == 1:
            return None
        raise


def factory(root):
    require('RUN_FIRSTBOOT=true' in (root / 'etc/default/inithooks').read_text().splitlines(), 'root has already completed setup')
    for name in ['var/lib/turnkey-mail/state.json', 'var/lib/hubdns/sub_apikey', 'var/lib/tklbam/key', 'var/lib/turnkey-onboarding/state.json']:
        require(not (root / name).exists(), 'initialized service state in source: ' + name)


def install(root, manifest, app):
    root, manifest = Path(root), Path(manifest).resolve()
    data = load(manifest)
    row = data['apps'][app]
    factory(root)
    targets = []
    for name, item in data['packages'].items():
        records = run(['chroot', root, 'apt-cache', 'show', name + '=' + item['version']])
        hashes = re.findall(r'^SHA256: ([0-9a-f]{64})$', records, re.M)
        require(hashes and set(hashes) == {item['sha256']}, 'signed APT candidate hash differs: ' + name)
        targets.append(name + '=' + item['version'])
    for name, floor in data['minimum_packages'].items():
        installed = package_version(root, name, optional=True)
        result = subprocess.run(['dpkg', '--compare-versions', installed, 'ge', floor]) if installed else None
        if result is None or result.returncode:
            targets.append(name + '=' + floor)
    run(['chroot', root, 'apt-get', '-y', '--no-remove', '--no-install-recommends',
         '-o', 'APT::Get::AllowUnauthenticated=false', '-o', 'Acquire::AllowInsecureRepositories=false',
         '-o', 'DPkg::Options::=--force-confdef', '-o', 'DPkg::Options::=--force-confold', 'install'] + targets)
    for name, item in data['packages'].items():
        require(package_version(root, name) == item['version'], 'installed version differs: ' + name)
    for name, floor in data['minimum_packages'].items():
        run(['dpkg', '--compare-versions', package_version(root, name), 'ge', floor])
    package = asset_path(manifest.parent, row['identity_package'])
    identity = 'turnkey-' + app + '-' + data['technical_release']
    require(run(['dpkg-deb', '-f', package, 'Package']) == identity, 'identity DEB package name differs')
    require(run(['dpkg-deb', '-f', package, 'Version']) == '1', 'identity DEB revision differs')
    with tempfile.TemporaryDirectory(prefix='ec2-hotfix-', dir=root / 'run') as temporary:
        destination = Path(temporary) / package.name
        shutil.copyfile(package, destination)
        current = run(['chroot', root, 'dpkg-query', '-W', '-f=${Package}\n']).splitlines()
        old = [name for name in current if re.fullmatch('turnkey-' + re.escape(app) + r'-[0-9][0-9.\-]*', name) and name != identity]
        if old:
            run(['chroot', root, 'dpkg', '--purge'] + old)
        run(['chroot', root, 'dpkg', '--install', '/' + str(destination.relative_to(root))])
    for item in row.get('overlay', []):
        target = root / item['target'].lstrip('/')
        require(target.resolve().is_relative_to(root.resolve()), 'overlay escapes candidate root')
        require(target.is_file() and sha(target) in item['previous_sha256'], 'overlay would overwrite an unexpected source file')
        shutil.copyfile(asset_path(manifest.parent, item), target)
        target.chmod(item.get('mode', 0o644))
    config = root / 'etc/webmin/miniserv.conf'
    lines = config.read_text().splitlines()
    chain = [line for line in lines if line.startswith('extracas=')]
    canonical_chain = 'extracas=/etc/ssl/private/cert.pem'
    require(chain in ([], ['extracas='], [canonical_chain]), 'source has a different Webmin chain configuration')
    if chain == ['extracas=']:
        lines[lines.index('extracas=')] = canonical_chain
        config.write_text('\n'.join(lines) + '\n')
    elif not chain:
        config.write_text('\n'.join(lines + [canonical_chain]) + '\n')
    technical = identity + '-trixie-amd64'
    (root / 'etc/turnkey_version').write_text(technical + '\n')
    run(['bash', asset_path(manifest.parent, data['aptconf_tag']), root, 'ec2'])
    factory(root)
    marker = root / 'var/lib/turnkey-info/hotfix.json'
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({'manifest_sha256': sha(manifest), 'identity': technical,
                                 'sources': data['sources'], 'app_main': row['source_main']}, sort_keys=True) + '\n')


def profile(root, manifest, app, output):
    """Index the final mounted filesystem, never the source or a booted guest."""
    root, manifest, output = Path(root), Path(manifest).resolve(), Path(output)
    data = load(manifest)
    factory(root)
    identity = 'turnkey-' + app + '-' + data['technical_release'] + '-trixie-amd64'
    require((root / 'etc/turnkey_version').read_text().strip() == identity, 'wrong profile identity')
    output.mkdir(parents=True, exist_ok=True)
    expected = output / (identity + '.tar.gz')
    require(not expected.exists(), 'profile output already exists; use a new candidate directory')
    with tempfile.TemporaryDirectory(prefix='ec2-profile-', dir=root / 'run') as temporary:
        temporary = Path(temporary)
        work, pristine, destination = [temporary / name for name in ['work', 'pristine', 'output']]
        for path in [work, pristine, destination]:
            path.mkdir()
        config = work / 'profile-conf'
        config.mkdir()
        for name, item in data['apps'][app]['profile_conf'].items():
            target = config / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(asset_path(manifest.parent, item), target)
            target.chmod(item.get('mode', 0o644))
        shutil.copyfile(asset_path(manifest.parent, data['profile_generator']), work / 'generate-profile')
        mounted = []
        try:
            run(['mount', '--bind', root, pristine]); mounted.append(pristine)
            run(['mount', '-o', 'remount,bind,ro', pristine])
            run(['mount', '--bind', output, destination]); mounted.append(destination)
            relative = '/' + str(temporary.relative_to(root))
            run(['chroot', root, '/usr/bin/env', '-i', 'HOME=/root', 'PATH=/usr/bin:/bin',
                 'PYTHONDONTWRITEBYTECODE=1', 'TKLBAM_LIB_PATH=/usr/lib/tklbam',
                 'PYTHONPATH=/usr/lib/tklbam:/usr/lib/tklbam/deps/lib', '/usr/lib/tklbam-pypy2/bin/pypy',
                 relative + '/work/generate-profile', '--profiles-conf=' + relative + '/work/profile-conf',
                 relative + '/pristine', relative + '/output'])
        finally:
            for path in reversed(mounted):
                run(['umount', path])
    require(expected.is_file(), 'profile generator did not produce the exact EC2 identity')
    packages = run(['chroot', root, 'dpkg-query', '-W', '-f=${Package}\t${Version}\t${Status}\n'])
    (output / 'packages.tsv').write_text(packages + '\n')
    receipt = {'profile': expected.name, 'profile_sha256': sha(expected), 'identity': identity,
               'manifest_sha256': sha(manifest), 'source_ami': data['apps'][app]['source_ami'],
               'source_main': data['apps'][app]['source_main'], 'sources': data['sources'],
               'packages_sha256': sha(output / 'packages.tsv'),
               'root_marker_sha256': sha(root / 'var/lib/turnkey-info/hotfix.json'), 'pristine': True}
    (output / 'profile-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'profile'])
    parser.add_argument('root')
    parser.add_argument('manifest')
    parser.add_argument('app')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.action == 'install':
        install(args.root, args.manifest, args.app)
    else:
        require(args.output, 'profile requires --output')
        profile(args.root, args.manifest, args.app, args.output)
