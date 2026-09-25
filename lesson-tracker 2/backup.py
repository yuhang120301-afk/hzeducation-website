"""Consistent SQLite backup; copy the resulting file to private off-host storage."""
import argparse
import sqlite3
from pathlib import Path
from server import DB_PATH

parser = argparse.ArgumentParser()
parser.add_argument('destination', help='New private backup path (must not exist)')
args = parser.parse_args()
target = Path(args.destination).resolve()
source = Path(DB_PATH).resolve()
if not source.is_file():
    raise SystemExit('数据库不存在。')
if target == source or target.exists():
    raise SystemExit('请选择一个尚不存在的备份文件路径。')
target.parent.mkdir(parents=True,exist_ok=True)
with sqlite3.connect(f'{source.as_uri()}?mode=ro',uri=True) as src, sqlite3.connect(target) as dest:
    src.backup(dest)
    if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise SystemExit('备份校验失败。')
target.chmod(0o600)
print('备份成功。请将文件保存到独立的私有存储。')
