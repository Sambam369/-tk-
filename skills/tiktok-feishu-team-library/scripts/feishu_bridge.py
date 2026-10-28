"""Local TikTok workflow -> Feishu. No Gemini/Apify. Run from workspace root."""
import argparse
import json
import os
import pathlib
import subprocess
import shutil
import time

CONFIG_PATH = pathlib.Path(os.environ.get('TIKTOK_LIBRARY_CONFIG', 'collector.config.json')).resolve()
CONFIG = json.loads(CONFIG_PATH.read_text(encoding='utf-8-sig'))
ROOT = CONFIG_PATH.parent
WORK = ROOT / 'runtime'
CLI = CONFIG.get('lark_cli', 'lark-cli')
BASE = CONFIG['base_token']
TASKS = CONFIG['tasks_table_id']
ASSETS = CONFIG['assets_table_id']
MEDIA_ROOT = pathlib.Path(CONFIG['media_root']).expanduser()
if not MEDIA_ROOT.is_absolute():
    MEDIA_ROOT = (ROOT / MEDIA_ROOT).resolve()
if not all((BASE, TASKS, ASSETS, CONFIG.get('attachment_field_id'), CONFIG.get('browser_id'))):
    raise ValueError('Complete collector.config.json before running')

def call(command, table=None, payload=None, extra=()):
    WORK.mkdir(parents=True, exist_ok=True)
    args = [CLI, 'base', command, '--base-token', BASE, '--as', 'user']
    if table:
        args += ['--table-id', table]
    if payload is not None:
        path = WORK / 'request.json'
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        args += ['--json', '@' + path.relative_to(ROOT).as_posix()]
    args += list(extra)
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    if result.returncode == 10:
        raise RuntimeError('Feishu requires explicit high-risk confirmation; no automatic override.')
    try:
        data = json.loads(result.stdout if result.returncode == 0 else result.stderr)
    except ValueError:
        raise RuntimeError('Feishu CLI failed, exit=' + str(result.returncode)) from None
    if result.returncode or data.get('ok') is False:
        raise RuntimeError(json.dumps(data.get('error', data), ensure_ascii=False))
    return data.get('data', data)

def records(table, fields):
    offset = 0
    out = []
    while True:
        path = WORK / ('records-' + table + '.ndjson')
        extra = ['--format', 'ndjson', '--output', path.relative_to(ROOT).as_posix(),
                 '--overwrite', '--offset', str(offset), '--limit', '2000']
        for field in fields:
            extra += ['--field-id', field]
        response = call('+record-list', table, extra=extra)
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line]
        out.extend(rows)
        if not response.get('has_more'):
            return out
        if not rows:
            raise RuntimeError('Pagination returned no rows with has_more=true')
        offset += len(rows)

def cell(row, name):
    return row.get(name, row.get('fields', {}).get(name))

def create(table, fields):
    result = call('+record-batch-create', table, {'create_records': [fields]})
    ids = result.get('record_id_list')
    if not ids or len(ids) != 1:
        raise RuntimeError('Record created but ID missing; inspect before retrying')
    return ids[0]

def update(table, rid, fields):
    return call('+record-batch-update', table, {'update_records': {rid: fields}})

def find_video(item):
    p = pathlib.Path(item.get('filePath', ''))
    if p.is_file() and p.suffix.lower() == '.mp4':
        return p.resolve()
    matches = list(MEDIA_ROOT.rglob(str(item['id']) + '.mp4'))
    if len(matches) != 1:
        raise RuntimeError('Cannot uniquely locate video ' + str(item['id']))
    return matches[0].resolve()

def sync(manifest, keyword, date, country='巴西', task_id=None):
    items = json.loads(pathlib.Path(manifest).read_text(encoding='utf-8-sig'))
    existing = {str(cell(r, '视频ID')): r for r in records(ASSETS, ['视频ID', '上传状态', '视频'])}
    if task_id is None:
        task_id = create(TASKS, {'任务名称': date + ' ' + keyword + ' 历史素材同步', '关键词': keyword,
                               '国家': country, '目标数量': len(items), '状态': '上传中',
                               '运行说明': '历史素材迁移；保留原始采集指标，不代表通过新门槛。'})
    uploaded = 0
    failures = []
    for item in items:
        vid = str(item['id'])
        try:
            path = find_video(item)
            if not path.is_relative_to(MEDIA_ROOT.resolve()):
                raise RuntimeError('Video outside configured library')
            row = existing.get(vid)
            if row and cell(row, '视频'):
                uploaded += 1
                continue
            fields = {'视频ID': vid, '采集任务': task_id, '关键词': keyword, '国家': country,
                      '采集日期': date, '作者': item.get('author', ''), '标题': item.get('title') or '',
                      '来源链接': item.get('sourceUrl', ''), '本地路径': str(path),
                      '地区依据': '葡萄牙语及账号资料推断；未获平台地区确认', '上传状态': '待上传'}
            stats = item.get('stats', {})
            for target, source in [('播放量', 'playCount'), ('点赞量', 'diggCount')]:
                if isinstance(stats.get(source), (int, float)):
                    fields[target] = stats[source]
            rid = row['record_id'] if row else create(ASSETS, fields)
            if row:
                update(ASSETS, rid, fields)
            # Never blindly retry an attachment append after an ambiguous response.
            upload_path = path
            if not path.is_relative_to(ROOT):
                # CLI only accepts workspace-relative file paths. Library remains on NAS.
                upload_path = WORK / 'upload-staging' / (vid + '.mp4')
                upload_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, upload_path)
            result = call('+record-upload-attachment', ASSETS, extra=[
                '--record-id', rid, '--field-id', CONFIG['attachment_field_id'],
                '--file', upload_path.relative_to(ROOT).as_posix()])
            (WORK / ('upload-' + vid + '.json')).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
            update(ASSETS, rid, {'上传状态': '已上传'})
            if upload_path != path:
                upload_path.unlink(missing_ok=True)
            uploaded += 1
            print(json.dumps({'id': vid, 'uploaded': uploaded}), flush=True)
        except Exception as exc:
            failures.append({'id': vid, 'error': str(exc)})
            print(json.dumps({'id': vid, 'status': 'failed'}), flush=True)
    update(TASKS, task_id, {'状态': '已完成' if not failures else '上传待重试',
                           '已下载数量': len(items), '已上传数量': uploaded,
                           '运行说明': '历史素材同步完成' if not failures else json.dumps(failures, ensure_ascii=False)[:1800]})
    report = {'task_id': task_id, 'uploaded': uploaded, 'failed': failures}
    (WORK / 'sync-report.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))
    return report

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest')
    p.add_argument('--keyword')
    p.add_argument('--date', required=True)
    p.add_argument('--pending', action='store_true')
    a = p.parse_args()
    if a.pending:
        rows = records(TASKS, ['任务名称', '关键词', '国家', '目标数量', '最低播放量', '最低点赞量', '状态'])
        print(json.dumps([r for r in rows if cell(r, '状态') == '待采集'], ensure_ascii=True))
    elif a.manifest and a.keyword:
        sync(a.manifest, a.keyword, a.date)
    else:
        p.error('Use --pending or --manifest FILE --keyword TEXT')

if __name__ == '__main__':
    main()
