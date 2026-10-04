#!/usr/bin/env python3
"""Validate both Linux packages without running their executables."""
from pathlib import Path
import io, struct, tarfile, hashlib, subprocess, re
import os
root = Path(__file__).resolve().parent.parent / 'dist'
version = os.environ.get('VERSION', '1.0.1')
for arch, machine in [('amd64', 62), ('arm64', 183)]:
    prefix = f'FileTransferEasy-{version}-linux-{arch}'
    raw = (root / (prefix + '.deb')).read_bytes()
    assert raw[:8] == b'!<arch>\n'
    members = {}
    offset = 8
    while offset < len(raw):
        header = raw[offset:offset + 60]
        assert header[58:60] == b'`\n'
        size = int(header[48:58])
        members[header[:16].decode().strip().rstrip('/')] = raw[offset + 60:offset + 60 + size]
        offset += 60 + size + size % 2
    assert members['debian-binary'] == b'2.0\n'
    with tarfile.open(fileobj=io.BytesIO(members['control.tar.gz'])) as t:
        control = t.extractfile('control').read().decode()
        assert f'Architecture: {arch}' in control
        assert f'Version: {version}' in control
    with tarfile.open(fileobj=io.BytesIO(members['data.tar.gz'])) as t:
        binary = t.extractfile('usr/bin/file-transfer-easy').read()
        assert struct.unpack_from('<H', binary, 18)[0] == machine
        info = t.getmember('usr/bin/file-transfer-easy')
        assert info.mode == 493
        assert t.extractfile('usr/share/applications/org.wails.file_transfer_easy.desktop').read().find(b'%F') >= 0
    with tarfile.open(root / (prefix + '.tar.gz')) as t:
        assert t.extractfile(prefix + '/file-transfer-easy').read() == binary
        install = t.extractfile(prefix + '/install.sh').read().decode()
        subprocess.run(['sh', '-n'], input=install, text=True, check=True)
        python = install.split("<<'PY'\n")[1].split('\nPY\n')[0]
        compile(python, 'install.sh', 'exec')
        quoted = next(line for line in python.splitlines() if line.startswith('executable =')).split(' = ', 1)[1]
        import sys
        old_argv = sys.argv
        sys.argv = ['test', '/home/name $cash `tick` "quote" \\slash%/.local/bin/file-transfer-easy']
        executable = eval(quoted, {'sys': sys, 'slash': chr(92)})
        sys.argv = old_argv
        assert executable == '/home/name \\\\$cash \\\\`tick\\\\` \\\\"quote\\\\" \\\\\\\\slash%%/.local/bin/file-transfer-easy'
        print(arch, 'desktop Exec escaping:', repr(executable))
    for extension in ('.deb', '.tar.gz'):
        data = (root / (prefix + extension)).read_bytes()
        checksum = (root / (prefix + extension + '.sha256')).read_text().split()[0]
        assert hashlib.sha256(data).hexdigest() == checksum
    eh = struct.unpack_from('<16sHHIQQQIHHHHHH', binary)
    phoff, phentsize, phnum = (eh[5], eh[9], eh[10])
    segments = [struct.unpack_from('<IIQQQQQQ', binary, phoff + i * phentsize) for i in range(phnum)]
    interp = next((p for p in segments if p[0] == 3))
    print(arch, 'interpreter:', binary[interp[2]:interp[2] + interp[5]].rstrip(b'\x00').decode())
    dynamic = next((p for p in segments if p[0] == 2))
    entries = [struct.unpack_from('<qQ', binary, i) for i in range(dynamic[2], dynamic[2] + dynamic[5], 16)]
    assert not any((tag in (15, 29) for tag, val in entries)), 'Unexpected RPATH/RUNPATH'
    straddr = next((val for tag, val in entries if tag == 5))
    seg = next((p for p in segments if p[0] == 1 and p[3] <= straddr < p[3] + p[5]))
    start = seg[2] + straddr - seg[3]
    libs = [binary[start + v:binary.index(b'\x00', start + v)].decode() for tag, v in entries if tag == 1]
    print(arch, 'libraries:', ', '.join(libs))
    assert 'libwebkit2gtk-4.1.so.0' in libs and 'libgtk-3.so.0' in libs
    versions = {tuple(map(int, v.split(b'.'))) for v in re.findall(b'GLIBC_(\\d+\\.\\d+(?:\\.\\d+)?)\\x00', binary)}
    assert versions and max(versions) <= (2, 36), 'Requires newer glibc than Debian 12'
    print('PASS', arch, 'DEB, TAR, ELF, permissions, desktop entry, installer syntax, checksums')
