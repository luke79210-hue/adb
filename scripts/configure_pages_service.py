"""Configure a GitHub Pages origin in the local .env without exposing secrets."""
import argparse
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def pages_origin(value):
    url = urlsplit(value.strip())
    if (url.scheme != 'https' or not url.hostname or not re.fullmatch(r'[A-Za-z0-9-]+\.github\.io',url.hostname)
            or url.username or url.password or url.query or url.fragment or url.port not in (None,443)):
        raise ValueError('請使用有效 GitHub Pages HTTPS 網址，例如 https://owner.github.io/repo/')
    return 'https://'+url.hostname.lower()


def configure(path, url):
    origin = pages_origin(url)
    text = path.read_text() if path.exists() else ''
    lines = text.splitlines(keepends=True)
    pattern = re.compile(r'^\s*(?:export\s+)?ULTRON_ALLOWED_ORIGINS\s*=')
    matches = [i for i,line in enumerate(lines) if pattern.match(line)]
    origins = set()
    if len(matches)>1:
        raise ValueError('存在重複的 ULTRON_ALLOWED_ORIGINS，請先整理設定')
    if matches:
        tokens = shlex.split(lines[matches[0]].split('=',1)[1],comments=True)
        if len(tokens)>1 or (tokens and ('$' in tokens[0] or '`' in tokens[0])):
            raise ValueError('原設定包含動態 shell 表達式，未覆寫')
        origins.update(filter(None,(tokens[0] if tokens else '').split(',')))
    origins.add(origin)
    setting='ULTRON_ALLOWED_ORIGINS='+shlex.quote(','.join(sorted(origins)))+'\n'
    if matches:
        lines[matches[0]]=setting
    else:
        if lines and not lines[-1].endswith('\n'):
            lines[-1]+='\n'
        lines.append(setting)
    # Save a local recovery copy; it is ignored by Git and never uploaded.
    if path.exists():
        backup=path.parent/'.runtime'/'env-before-pages-setup'
        backup.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if not backup.exists():
            backup.write_text(text)
            backup.chmod(0o600)
    path.write_text(''.join(lines))
    path.chmod(0o600)
    return origin


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('pages_url')
    args=parser.parse_args()
    print('本機服務已允許來源：'+configure(ROOT/'.env',args.pages_url))
    print('設定將在下次啟動生效；未公開監聽 LAN，也未輸出或改寫其他憑證。')
