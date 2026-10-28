"""Offline behavior checks. Does not contact TikTok, Feishu or GitHub."""
import ast
import importlib
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
for path in ROOT.rglob('*.py'):
    ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
with tempfile.TemporaryDirectory() as tmp:
    config = Path(tmp) / 'collector.config.json'
    config.write_text(json.dumps(dict(base_token='test', tasks_table_id='test',
        assets_table_id='test', attachment_field_id='test', browser_id='test',
        media_root=tmp)), encoding='utf-8')
    os.environ['TIKTOK_LIBRARY_CONFIG'] = str(config)
    worker = importlib.import_module('run_feishu_tasks')
    assert worker.task_settings({}) == (20, 100000, 1000)
    assert worker.task_settings({'采集数量':['10'], '门槛模式':['自定义'],
        '最低播放量':0, '最低点赞量':0}) == (10, 0, 0)
    assert worker.task_settings({'最低播放量':0}) == (20, 100000, 1000)
    from filter_candidates import normalize, rank
    def item(vid, views, likes, language='pt'):
        return dict(id=vid, textLanguage=language, stats=dict(playCount=views, diggCount=likes))
    good=item('1234567890123456789',200000,3000)
    other=item('1234567890123456788',300000,4000)
    values=[good, good, other, item('1234567890123456787',99999,5000),
        item('1234567890123456786',200000,3000,'es'),
        item('1234567890123456785',float('nan'),3000)]
    eligible=normalize(values, 'pt', 100000, 1000)
    assert len(eligible)==2
    assert rank(eligible)[0]['id']==other['id']
    assert normalize([item('1234567890123456784',0,0)], 'pt', 0, 0)
for path in ROOT.rglob('*'):
    if path.is_file() and '__pycache__' not in path.parts:
        assert path.suffix.lower() not in ('.mp4','.partial','.log','.ndjson'), path
        assert path.name not in ('collector.config.json','storage.json','.env'), path
print('PASS: syntax, defaults, custom zero, threshold/language/metric filtering, dedup, ranking, package artifacts')
