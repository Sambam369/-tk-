"""Filter and rank TikTok metadata deterministically.
No video upload, paid scraper calls, browser cookie reads, or downloads.
"""
import argparse, datetime, json, math, os, pathlib, re, time, urllib.request, urllib.error

def load_candidates(path):
    data=json.loads(pathlib.Path(path).read_text(encoding='utf-8-sig'))
    return data if isinstance(data,list) else data.get('items',[])

def normalize(items, language, min_views, min_likes):
    found={}
    for i in items:
        vid=str(i.get('id',''))
        stats=i.get('stats',{})
        views=stats.get('playCount'); likes=stats.get('diggCount')
        if not re.fullmatch(r'\d{10,25}',vid):continue
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<0 for x in (views,likes)):continue
        if views<min_views or likes<min_likes:continue
        if i.get('textLanguage')!=language:continue
        found[vid]=i
    return list(found.values())

def rank(items):
    ranks={}
    for key in ('playCount','diggCount'):
        previous=None; position=0
        for n,i in enumerate(sorted(items,key=lambda x:x['stats'][key],reverse=True)):
            value=i['stats'][key]
            if value!=previous:position=n
            ranks[i['id']]=ranks.get(i['id'],0)+position
            previous=value
    return sorted(items,key=lambda i:(ranks[i['id']],-i['stats']['playCount'],i['id']))
