"""Validate the exact public static artifact; never include local service data."""
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = {'.html', '.js', '.css', '.svg', '.png', '.ico', '.webmanifest', '.woff2'}


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src'):
            self.paths.append(attrs['src'])
        if tag == 'link' and attrs.get('href'):
            self.paths.append(attrs['href'])


def verify(root=ROOT):
    web = (root/'web').resolve()
    if not (web/'index.html').is_file():
        raise ValueError('缺少 web/index.html')
    files = []
    for path in sorted(web.rglob('*')):
        if path.is_symlink():
            raise ValueError('禁止發佈 symlink：'+str(path.relative_to(web)))
        if not path.is_file():
            continue
        relative = path.relative_to(web)
        if path.name != '.nojekyll' and (path.suffix not in ALLOWED or any(part.startswith('.') for part in relative.parts)):
            raise ValueError('非靜態檔案不得發佈：'+str(relative))
        if path.suffix in ('.html', '.js', '.css'):
            content = path.read_text()
            if re.search(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}',content):
                raise ValueError('靜態檔案含認證格式，停止發佈：'+str(relative))
        files.append(str(relative))
    parser = Assets()
    parser.feed((web/'index.html').read_text())
    for asset in parser.paths:
        url = urlsplit(asset)
        if url.scheme == 'data':
            continue
        if url.scheme or url.netloc or asset.startswith('/'):
            raise ValueError('頁面資源須用相對路徑以支援 /adb/：'+asset)
        target = (web/unquote(url.path)).resolve()
        if not target.is_relative_to(web) or not target.is_file():
            raise ValueError('遺失或越界的頁面資源：'+asset)
    return files


if __name__ == '__main__':
    files = verify()
    print(f'發布檢查通過：僅 web/ 的 {len(files)} 個靜態檔案；資源支援子路徑，未包含本機資料或認證檔案。')
