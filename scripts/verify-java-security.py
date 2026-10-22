#!/usr/bin/env python3
"""Validate the frozen OpenJDK mitigation and every Compose JVM mount."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def verify(root=ROOT):
    folder = root / 'security/java'
    manifest = json.loads((folder / 'provenance.json').read_text())
    for filename, field in [('blocked.certs', 'blockedSha256'), ('blocked.certs.pem', 'sourceSha256')]:
        actual = hashlib.sha256((folder / filename).read_bytes()).hexdigest()
        if actual != manifest[field]:
            raise ValueError(f'{filename}: frozen upstream artifact checksum mismatch')
    filename = 'blocked-' + manifest['blockedSha256'] + '.certs'
    if manifest['composeSourceFilename'] != filename or (folder / filename).read_bytes() != (folder / 'blocked.certs').read_bytes():
        raise ValueError('Compose must use the immutable content-addressed certificate file')
    lines = (folder / 'blocked.certs').read_text().splitlines()
    if lines[0] != 'Algorithm=SHA-256' or len(lines[1:]) != 86:
        raise ValueError('Expected the complete SHA-256 upstream blocklist')
    if lines[1:] != sorted(set(lines[1:])) or any(not re.fullmatch('[A-F0-9]{64}', row) for row in lines[1:]):
        raise ValueError('Invalid or duplicate certificate fingerprint')
    profiles = [
        ['lightweight-docker-compose.yml'], ['docker-compose.yml'],
        ['docker-compose.server.yml'], ['docker-compose.compatibility.yml'],
        ['docker-compose.yml', 'docker-compose.model-mock.yml'],
        ['lightweight-docker-compose.yml', 'docker-compose.grpc.yml'],
    ]
    checked = 0
    task_env = os.environ.copy()
    task_env.setdefault('POSTGRES_PASSWORD', 'security-config-validation-placeholder')
    for profile in profiles:
        command = ['docker', 'compose']
        for filename in profile:
            command += ['-f', filename]
        command += ['config', '--format', 'json', '--no-env-resolution']
        config = json.loads(subprocess.check_output(command, cwd=root, env=task_env))
        for name, service in config['services'].items():
            image = service.get('image', '')
            if not any(part in image for part in (
                'slawekradzyminski/backend:', 'slawekradzyminski/consumer:',
                'slawekradzyminski/ollama-mock:', 'apache/artemis:', 'quay.io/keycloak/keycloak:',
            )):
                continue
            target = ('/usr/lib/jvm/jre-21' if 'keycloak' in image else '/opt/java/openjdk') + '/lib/security/blocked.certs'
            mounts = [mount for mount in service.get('volumes', []) if mount.get('target') == target]
            if len(mounts) != 1:
                raise ValueError(f'{profile}/{name}: JVM blocklist mount missing or duplicated')
            mount = mounts[0]
            if (mount['type'] != 'bind' or Path(mount['source']).resolve() != (folder / manifest['composeSourceFilename']).resolve()
                    or not mount.get('read_only') or mount.get('bind', {}).get('create_host_path', True)):
                raise ValueError(f'{profile}/{name}: blocklist must use the exact existing read-only file')
            checked += 1
    inventory = (root / 'ansible/inventory/group_vars/production/main.yml').read_text()
    if 'app_copy_paths:\n  - security\n' not in inventory:
        raise ValueError('Production must copy the security artifact before Compose recreates services')
    if 'COPY security/java/blocked.certs ${JAVA_HOME}/lib/security/blocked.certs' not in (root / 'Dockerfile').read_text():
        raise ValueError('The optional Jenkins JVM must include the blocklist')
    print(f'Verified upstream certificate artifacts and {checked} fail-closed JVM mounts')


if __name__ == '__main__':
    verify()
