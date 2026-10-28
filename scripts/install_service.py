"""Install a private runtime bundle outside macOS's protected Documents folder."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import sqlite3


def prepare_install(source, target, python, mode, plist_path):
    if mode not in ('mock','real'):
        raise ValueError('模式必須為 mock 或 real')
    os.umask(0o077)
    source=Path(source).resolve()
    target=Path(target).resolve()
    bundle=target/'app'
    data=target/'data'
    first_install=not data.exists()
    for directory in (target,bundle,data):
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        directory.chmod(0o700)
    files=[]
    for directory,suffixes in [('server',{'.py'}),('web',{'.html','.js','.css','.svg','.png','.ico','.woff2','.webmanifest'})]:
        files.extend(p for p in (source/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and (p.suffix in suffixes or p.name=='.nojekyll'))
    files.append(source/'scripts'/'run-service.sh')
    for path in files:
        if path.is_symlink():
            raise ValueError('安裝檔案不可為 symlink')
        destination=bundle/path.relative_to(source)
        destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if destination.is_symlink():
            raise ValueError('安裝目的檔案不可為 symlink')
        shutil.copyfile(path,destination)
        destination.chmod(0o700 if path.suffix=='.sh' else 0o600)
    if (source/'.env').is_file():
        shutil.copyfile(source/'.env',bundle/'.env')
        (bundle/'.env').chmod(0o600)
    if first_install:
        old=source/'.runtime'
        for name in ('apks','media'):
            if (old/name).is_dir():
                shutil.copytree(old/name,data/name,dirs_exist_ok=True)
        for path in old.glob('*.sqlite3'):
            # SQLite backup includes outstanding WAL transactions; never copy a live WAL blindly.
            src=sqlite3.connect(f'{path.as_uri()}?mode=ro',uri=True)
            dst=sqlite3.connect(data/path.name)
            try:
                src.backup(dst)
                dst.execute('PRAGMA journal_mode=DELETE')
            finally:
                src.close();dst.close()
        for path in data.rglob('*'):
            path.chmod(0o700 if path.is_dir() else 0o600)
    config={
        'Label':'com.ultron.adb-qa',
        'ProgramArguments':['/bin/zsh',str(bundle/'scripts'/'run-service.sh'),str(python),mode],
        'WorkingDirectory':str(bundle),
        'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,
        'EnvironmentVariables':{'PATH':str(Path(python).parent)+':/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin','ULTRON_DATA':str(data)},
        'StandardOutPath':str(data/'service.log'),
        'StandardErrorPath':str(data/'service-error.log')
    }
    plist_path=Path(plist_path)
    plist_path.parent.mkdir(parents=True,exist_ok=True)
    with plist_path.open('wb') as stream:
        plistlib.dump(config,stream)
    plist_path.chmod(0o600)
    return bundle,data


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source');parser.add_argument('target');parser.add_argument('python');parser.add_argument('mode');parser.add_argument('plist')
    args=parser.parse_args()
    bundle,data=prepare_install(args.source,args.target,args.python,args.mode,args.plist)
    print('服務程式：'+str(bundle))
    print('本機資料：'+str(data))
