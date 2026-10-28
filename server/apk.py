"""APK metadata reader: plain XML and Android binary XML, no third party tools."""
import hashlib
import struct
import zipfile
from xml.etree import ElementTree


def manifest_metadata(data):
    if data.lstrip().startswith(b'<'):
        root = ElementTree.fromstring(data)
        ns = '{http://schemas.android.com/apk/res/android}'
        return {'package': root.get('package'), 'versionCode': root.get(ns + 'versionCode'),
                'versionName': root.get(ns + 'versionName')}
    if len(data) < 8 or struct.unpack_from('<H', data)[0] != 3:
        raise ValueError('不是有效的 Android Manifest')
    strings = []
    offset = struct.unpack_from('<H', data, 2)[0]

    def length(pos, utf8):
        if utf8:
            first = data[pos]
            return (((first & 127) << 8) | data[pos+1], pos+2) if first & 128 else (first, pos+1)
        first = struct.unpack_from('<H', data, pos)[0]
        return (((first & 32767) << 16) | struct.unpack_from('<H', data, pos+2)[0], pos+4) if first & 32768 else (first, pos+2)

    while offset + 8 <= len(data):
        kind, header, size = struct.unpack_from('<HHI', data, offset)
        if size < header or size < 8 or offset + size > len(data):
            raise ValueError('損壞的 binary XML chunk')
        if kind == 1:
            count, _, flags, start, _ = struct.unpack_from('<IIIII', data, offset+8)
            if count > 100000:
                raise ValueError('字串數量異常')
            utf8 = bool(flags & 256)
            for i in range(count):
                pos = offset + start + struct.unpack_from('<I', data, offset+header+i*4)[0]
                if utf8:
                    _, pos = length(pos, True)
                n, pos = length(pos, utf8)
                strings.append(data[pos:pos+n*(1 if utf8 else 2)].decode('utf-8' if utf8 else 'utf-16le'))
        elif kind == 0x102:
            _, name, attr_start, attr_size, count = struct.unpack_from('<IIHHH', data, offset+16)
            if strings[name] == 'manifest':
                result = {}
                for i in range(count):
                    pos = offset+16+attr_start+i*attr_size
                    _, key, raw, _, _, value_type, value = struct.unpack_from('<IIIHBBI', data, pos)
                    key = strings[key]
                    if key in ('package', 'versionCode', 'versionName'):
                        result[key] = strings[raw] if raw != 0xffffffff else (strings[value] if value_type == 3 else str(value))
                return result
        offset += size
    raise ValueError('Manifest 缺少套件資訊')


def inspect_apk(path):
    with zipfile.ZipFile(path) as apk:
        info = apk.getinfo('AndroidManifest.xml')
        if info.file_size > 8 * 1024 * 1024:
            raise ValueError('Manifest 過大')
        result = manifest_metadata(apk.read(info))
    if not result.get('package') or not str(result.get('versionCode', '')).isdigit():
        raise ValueError('APK 缺少有效 Package Name / VersionCode')
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return {**result, 'size': path.stat().st_size, 'sha256': digest.hexdigest()}
