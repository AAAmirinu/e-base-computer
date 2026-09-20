"""Metadata-only transient service probe. Never connects to a display socket."""
import json
import os
import stat
import argparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outer-pid', type=int)
    args = parser.parse_args()
    if args.outer_pid is not None and args.outer_pid <= 1:
        raise ValueError('Explicit non-init process required')
    paths = ('/mnt/wslg/runtime-dir/wayland-0', '/tmp/.X11-unix/X0',
             '/run/WSL/1_interop', '/run/user/1000/bus')
    if args.outer_pid:
        paths += (f'/proc/{args.outer_pid}/root/mnt/wslg/runtime-dir/wayland-0',
                  f'/proc/{args.outer_pid}/root/tmp/.X11-unix/X0')
    results = {}
    for path in paths:
        try:
            metadata = os.stat(path)
            mode = metadata.st_mode
            results[path] = {'visible': True, 'is_socket': stat.S_ISSOCK(mode),
                             'mode': oct(stat.S_IMODE(mode)), 'owner_uid': metadata.st_uid,
                             'write_access': os.access(path, os.W_OK)}
        except OSError as error:
            results[path] = {'visible': False, 'errno': error.errno}
    # Names only, no connection or protocol traffic; abstract sockets are not
    # fenced by hiding filesystem paths. Do not export unrelated socket names.
    with open('/proc/net/unix') as stream:
        abstract_display = [line.split()[-1] for line in stream
                            if '@/tmp/.X11-unix/' in line or '@wayland-' in line]
    print(json.dumps({'uid': os.getuid(), 'mount_namespace': os.readlink('/proc/self/ns/mnt'),
        'paths': results, 'abstract_display_socket_names': abstract_display,
        'clipboard_access_attempted': False, 'full_boundary_accepted': False}))


if __name__ == '__main__':
    main()
