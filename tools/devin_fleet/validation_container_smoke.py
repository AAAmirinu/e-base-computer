"""Trusted validation-VM-only smoke, no project source; retain stopped container."""
import json
from pathlib import Path
import subprocess
import uuid
from sandbox_validation_container import admit_image, create_arguments, verify_created_container, ENV

IMAGE = 'sha256:1750198e508ceeabc96bb744de28bce36fe877ab0cd7f5a4a2eb0eff6d710f1f'


def run(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr[:2000])
    return result.stdout


def main():
    image = json.loads(run(['docker', 'image', 'inspect', IMAGE]))[0]
    admit_image(image)
    operation = uuid.uuid4().hex
    container = run(create_arguments(IMAGE, operation)).strip()
    receipt = {'operation': operation, 'container_id': container, 'image_id': IMAGE}
    try:
        info = json.loads(run(['docker', 'inspect', container]))[0]
        verify_created_container(info, IMAGE, operation)
        receipt['prestart_verified'] = True
        run(['docker', 'start', container])
        source = Path('/tmp/validation_boundary_probe.py').read_text()
        raw = run(['docker', 'exec', container, '/usr/bin/env', '-i', *ENV,
                   '/usr/local/bin/python3', '-I', '-c', source])
        receipt['probe'] = json.loads(raw)
    finally:
        run(['docker', 'stop', '--time', '2', container])
        state = json.loads(run(['docker', 'inspect', '--format', '{{json .State}}', container]))
        receipt['stopped'] = state['Running'] is False
        print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
