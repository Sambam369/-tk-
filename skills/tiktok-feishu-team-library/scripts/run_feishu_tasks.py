"""Run pending Feishu collection tasks once on this computer. No paid API."""
import csv
import argparse
import datetime
import io
import hashlib
import json
import os
import msvcrt
import pathlib
import re
import shutil
import subprocess
import time
import unicodedata
import urllib.parse

import feishu_bridge as bridge
from filter_candidates import normalize, rank

ROOT = bridge.ROOT

def browser(*args):
    r = subprocess.run(['browser-act', *args], cwd=ROOT, capture_output=True,
                       text=True, encoding='utf-8', timeout=100)
    if r.returncode:
        raise RuntimeError(r.stderr[:800] or r.stdout[:800])
    if r.stdout.startswith('Error '):
        raise RuntimeError(r.stdout[:800])
    return r.stdout

def text(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.lower()) if not unicodedata.combining(c))

def choice(value, fallback):
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get('name', value.get('text'))
    return fallback if value is None or value == '' else value

def task_settings(task):
    legacy = bridge.cell(task, '目标数量')
    count = int(choice(bridge.cell(task, '采集数量'), 20 if legacy is None else legacy))
    mode = choice(bridge.cell(task, '门槛模式'), '默认')
    if mode not in ('默认', '自定义'):
        raise ValueError('Unknown threshold mode')
    views = bridge.cell(task, '最低播放量') if mode == '自定义' else None
    likes = bridge.cell(task, '最低点赞量') if mode == '自定义' else None
    return count, 100000 if views is None else int(views), 1000 if likes is None else int(likes)

def execute(task):
    rid = task['record_id']
    keyword = str(bridge.cell(task, '关键词') or '').strip()
    country = str(bridge.cell(task, '国家') or '巴西')
    count, min_views, min_likes = task_settings(task)
    if not keyword or not 1 <= count <= 100 or min_views < 0 or min_likes < 0:
        raise ValueError('Invalid keyword, count or thresholds')
    if country not in ('巴西', 'BR', 'Brazil'):
        raise ValueError('Only Brazil currently supported; Mexico requires a separate language/market configuration')
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', keyword).strip(' .')[:80]
    date = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
    if not bridge.MEDIA_ROOT.is_dir():
        raise RuntimeError('Company network library unavailable; not falling back to local storage')
    out = bridge.MEDIA_ROOT / date / '巴西' / safe
    work = bridge.WORK / rid
    work.mkdir(parents=True, exist_ok=True)
    session = ('feishu-' + rid).lower()
    items = {}
    seen = set()
    bridge.update(bridge.TASKS, rid, {'状态': '采集中', '本地目录': str(out),
        '执行机': os.environ.get('COMPUTERNAME', '采集电脑'),
        '开始时间': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds'),
        '结束时间': None,
        '运行说明': '团队共享队列：本机执行，其他任务排队；Gemini/Apify关闭'})
    opened = False
    try:
        browser('--session', session, 'browser', 'open', bridge.CONFIG['browser_id'],
                'https://www.tiktok.com/search/video?q=' + urllib.parse.quote(keyword), '--headed')
        opened = True
        for query in (keyword, keyword + ' Brasil'):
            if query != keyword:
                browser('--session', session, 'navigate', 'https://www.tiktok.com/search/video?q=' + urllib.parse.quote(query))
            stable = 0
            for page in range(16):
                before = len(items)
                raw = browser('--session', session, 'network', 'requests', '--type', 'xhr,fetch', '--filter', 'search/item/full')
                rows = csv.DictReader(io.StringIO('\n'.join(x for x in raw.splitlines() if not x.startswith('#'))))
                for row in rows:
                    request_id = row.get('request_id')
                    if not request_id or request_id in seen:
                        continue
                    seen.add(request_id)
                    detail = browser('--session', session, 'network', 'request', request_id)
                    for line in detail.splitlines():
                        if line.startswith('response_body='):
                            try:
                                data = json.loads(line.split('=', 1)[1])
                            except ValueError:
                                continue
                            for item in data.get('item_list', []):
                                items[str(item['id'])] = item
                (work / 'candidates.json').write_text(json.dumps(list(items.values()), ensure_ascii=False), encoding='utf-8')
                stable = stable + 1 if len(items) == before else 0
                if stable >= 4 and page >= 5:
                    break
                browser('--session', session, 'eval', "document.querySelector('main').scrollTop = document.querySelector('main').scrollHeight")
                time.sleep(1)
    finally:
        if opened:
            browser('session', 'close', session)
    eligible = normalize(list(items.values()), 'pt', min_views, min_likes)
    # Deterministic text matching; not a claim of visual understanding or country verification.
    words = [w for w in re.findall(r'\w+', text(keyword)) if len(w) >= 4]
    eligible = [i for i in eligible if not words or all(w in text(i.get('desc', '')) for w in words)]
    ordered = rank(eligible)
    from download_video import download_video
    completed = []
    errors = []
    for item in ordered:
        if len(completed) >= count:
            break
        vid = str(item['id'])
        author = item.get('author', {}).get('uniqueId', '')
        url = 'https://www.tiktok.com/@' + author + '/video/' + vid
        target = out / vid / (vid + '.mp4')
        try:
            if not target.is_file():
                source = download_video(url, work / 'downloads' / vid, vid)
                r = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-f', 'null', '-'], capture_output=True, timeout=180)
                if r.returncode:
                    raise RuntimeError('Video decode failed')
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix('.mp4.partial')
                shutil.copy2(source, temporary)
                with source.open('rb') as original, temporary.open('rb') as copied:
                    if hashlib.file_digest(original, 'sha256').digest() != hashlib.file_digest(copied, 'sha256').digest():
                        raise RuntimeError('Network copy checksum mismatch')
                # Rename on the same network volume, avoiding cross-device replace.
                temporary.replace(target)
                source.unlink()
            else:
                r = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(target), '-f', 'null', '-'], capture_output=True, timeout=180)
                if r.returncode:
                    raise RuntimeError('Existing video decode failed')
            completed.append({'id': vid, 'author': author, 'sourceUrl': url, 'filePath': str(target),
                              'stats': item['stats'], 'title': item.get('desc', ''), 'decodeVerified': True})
            bridge.update(bridge.TASKS, rid, {'已下载数量': len(completed)})
        except Exception as exc:
            errors.append({'id': vid, 'error': str(exc)[:300]})
    manifest = work / 'assets.json'
    manifest.write_text(json.dumps(completed, ensure_ascii=False, indent=2), encoding='utf-8')
    result = bridge.sync(manifest, keyword, date, task_id=rid)
    state = '上传待重试' if result['failed'] else ('已完成' if len(completed) >= count else '数量不足')
    bridge.update(bridge.TASKS, rid, {'状态': state, '运行说明':
        f'候选{len(items)}条；通过葡语/指标/文案匹配{len(eligible)}条；本地{len(completed)}条；飞书{result["uploaded"]}条。地区推断，非平台确认。' + json.dumps(errors, ensure_ascii=False)[:1000]})
    bridge.update(bridge.TASKS, rid, {'结束时间': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')})

def run_once():
    if not bridge.MEDIA_ROOT.is_dir():
        raise RuntimeError('Company NAS unavailable; shared worker cannot claim tasks')
    control = bridge.MEDIA_ROOT / '.collector-control'
    control.mkdir(exist_ok=True)
    shared = (control / 'worker.lock').open('a+b')
    shared.seek(0)
    if not shared.read(1):
        shared.write(b'0')
        shared.flush()
    shared.seek(0)
    try:
        # SMB byte-range lock: released by the OS on process exit, shared across computers.
        msvcrt.locking(shared.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        shared.close()
        print(json.dumps({'worker': 'another team collector is active'}), flush=True)
        return
    lock = bridge.WORK / 'worker.lock'
    bridge.WORK.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        shared.seek(0)
        msvcrt.locking(shared.fileno(), msvcrt.LK_UNLCK, 1)
        shared.close()
        raise SystemExit('Worker lock exists. Confirm previous worker stopped before removing it.')
    try:
        os.close(fd)
        tasks = bridge.records(bridge.TASKS, ['关键词', '国家', '目标数量', '采集数量', '门槛模式', '最低播放量', '最低点赞量', '状态'])
        for task in tasks:
            if bridge.cell(task, '状态') != '待采集':
                continue
            try:
                execute(task)
            except Exception as exc:
                bridge.update(bridge.TASKS, task['record_id'], {'状态': '失败', '运行说明': str(exc)[:1500],
                    '结束时间': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')})
                print(json.dumps({'task': task['record_id'], 'failed': True}), flush=True)
    finally:
        lock.unlink(missing_ok=True)
        shared.seek(0)
        msvcrt.locking(shared.fileno(), msvcrt.LK_UNLCK, 1)
        shared.close()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--watch', action='store_true', help='Poll queued button requests until stopped')
    p.add_argument('--interval', type=int, default=15)
    args = p.parse_args()
    if args.interval < 10:
        p.error('Minimum poll interval is 10 seconds')
    if not args.watch:
        return run_once()
    watcher = bridge.WORK / 'watcher.lock'
    bridge.WORK.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(watcher, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit('Watcher already started or stale lock; inspect before restarting')
    with os.fdopen(fd, 'w') as f:
        f.write(str(os.getpid()))
    try:
        while True:
            try:
                run_once()
                print(json.dumps({'watcher': 'ready', 'time': time.time()}), flush=True)
            except Exception as exc:
                print(json.dumps({'watcher': 'error', 'error': str(exc)[:1000]}), flush=True)
            time.sleep(args.interval)
    finally:
        watcher.unlink(missing_ok=True)

if __name__ == '__main__':
    main()
