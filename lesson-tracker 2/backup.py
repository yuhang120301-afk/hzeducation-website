"""Consistent SQLite backup; copy the resulting file to private off-host storage."""
import argparse
import sqlite3
from pathlib import Path

def snapshot_bytes(source_path):
    """Online backup. Safe while the app is writing; does not replace the live file."""
    source = Path(source_path).resolve()
    if not source.is_file():
        raise FileNotFoundError('数据库不存在。')
    dest = sqlite3.connect(':memory:')
    try:
        with sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True) as src:
            src.backup(dest)
        if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('备份校验失败。')
        return dest.serialize()
    finally:
        dest.close()

def write_snapshot(source_path, destination):
    target = Path(destination).resolve()
    source = Path(source_path).resolve()
    if target == source or target.exists():
        raise FileExistsError('请选择一个尚不存在的备份文件路径。')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(snapshot_bytes(source))
    target.chmod(0o600)
    return target

if __name__ == '__main__':
    from server import DB_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', help='New private backup path (must not exist)')
    args = parser.parse_args()
    try:
        write_snapshot(DB_PATH, args.destination)
    except (FileNotFoundError, FileExistsError, RuntimeError) as exc:
        raise SystemExit(str(exc))
    print('备份成功。请将文件保存到独立的私有存储。')
