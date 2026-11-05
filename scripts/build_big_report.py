# -*- coding: utf-8 -*-
"""
G 盘查重报告 v2 —— 簇式选择 + 分片加载 + 分页渲染

设计要点（都是踩过坑之后定下来的）：
  1. 缩略图**落盘成独立小文件**（t/00001.jpg），不内嵌base64。
     内嵌 base64 会让每个分片涨到 800 KB，51 片就是 40 MB，
     浏览器解析 JSON 直接卡死。落盘后单张约 1.5 KB，
     页面用相对路径 + loading="lazy"，首屏只请求视口内那几十张。
  2. **断点续跑**：已存在的缩略图直接跳过。中途被SIGTERM 也不用从头解码 2.4 万张。
     （历史教训：内嵌方案重跑一次要十几分钟，被打断就全白费。）
  3. 分片 JS 只存路径和元数据，单片 ~60 KB，按需加载，首屏只解析 1 片。
  4. 页面每次只渲染 PER_PAGE 个簇，默认 40，可调 20/40/80/160。

全程只读：只读取原图生成缩略图，绝不修改/移动/删除任何原始照片。
"""
import csv
import os
import base64
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from io import BytesIO
from PIL import Image

SRC = r'G:\_photo_dedupe_out\重复照片明细_全部.csv'
OUT_DIR = r'E:\G盘查重报告'
THUMB_DIR = os.path.join(OUT_DIR, 't')

THUMB_W = 72# 缩略图边长
THUMB_QUAL = 60       # JPEG 质量
CHUNK = 200           # 每个分片多少个簇
THUMB_WORKERS = 8     # 解码并发线程数

# ---------- 读取与聚簇 ----------

rows = list(csv.DictReader(open(SRC, encoding='utf-8-sig')))
same = [r for r in rows if '疑似' in r['类别'] and r['保留文件'] == r['重复文件名']]
diff = [r for r in rows if '疑似' in r['类别'] and r['保留文件'] != r['重复文件名']]
conf = [r for r in rows if '确认真重复' in r['类别']]

print('CSV 读入 %d 行：同名疑似 %d / 异名疑似 %d / 确认 %d'
      % (len(rows), len(same), len(diff), len(conf)))


def file_rel(p):
    return 'file:///' + quote(p.replace('\\', '/'), safe='/:')


clusters_map = defaultdict(lambda: {'keep': '', 'keeppath': '', 'dups': [], 'dirs': set(), 'kb': 0.0})
for r in same:
    k = (r['保留路径'], r['重复文件名'])
    c = clusters_map[k]
    c['keep'] = r['保留文件']
    c['keeppath'] = r['保留路径']
    c['dups'].append(r['重复文件路径'])
    c['dirs'].add(r['所在文件夹'])
    c['kb'] += float(r['单张大小KB'])

clusters = list(clusters_map.values())
for c in clusters:
    c['dirs'] = sorted(c['dirs'])
    c['mb'] = round(c['kb'] / 1024, 2)
    del c['kb']

total_dups = sum(len(c['dups']) for c in clusters)
total_mb = sum(c['mb'] for c in clusters)

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)

# ---------- 展平所有需要缩略图的路径，编号 ----------
all_paths = []
for c in clusters:
    all_paths.append(c['keeppath'])
    all_paths.extend(c['dups'])

n = len(all_paths)
print('簇 %d / 副本 %d / %.2f GB / 需缩略图 %d 张'
      % (len(clusters), total_dups, total_mb / 1024, n))


def thumb_file(i):
    return os.path.join(THUMB_DIR, '%05d.jpg' % i)


def make_thumb(arg):
    """返回 (编号, 是否现生成)。已存在则跳过——断点续跑的关键。"""
    i, path = arg
    tf = thumb_file(i)
    if os.path.exists(tf) and os.path.getsize(tf) > 0:
        return i, False
    try:
        im = Image.open(path)
        im.draft('RGB', (THUMB_W * 4, THUMB_W * 4))   # draft 必须在 convert 之前
        im = im.convert('RGB')
        im.thumbnail((THUMB_W, THUMB_W))
        buf = BytesIO()
        im.save(buf, 'JPEG', quality=THUMB_QUAL, optimize=False)
        tmp = tf + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(buf.getvalue())
        os.replace(tmp, tf)                # 原子替换，避免半张图
        return i, True
    except Exception:
        return i, False


todo = list(enumerate(all_paths))
todo = [(i, p) for i, p in todo
        if not (os.path.exists(thumb_file(i)) and os.path.getsize(thumb_file(i)) > 0)]
print('待生成缩略图 %d 张（已有 %d 张跳过）...' % (len(todo), n - len(todo)))

_t0 = time.time()
made = 0
if todo:
    with ThreadPoolExecutor(max_workers=THUMB_WORKERS) as ex:
        for k, (i, is_new) in enumerate(ex.map(make_thumb, todo), 1):
            made += 1 if is_new else 0
            if k % 1000 == 0 or k == len(todo):
                el = time.time() - _t0
                eta = el / k * (len(todo) - k)
                print('  %5d/%5d  新建 %5d  已用 %5.0f 秒  预计剩余 %5.0f 秒'
                      % (k, len(todo), made, el, eta))
print('缩略图阶段完成，耗时 %.1f 秒' % (time.time() - _t0))

# ---------- 分片写出（只存路径，不存图） ----------
_ti = 0
for c in clusters:
    cnt = len(c['dups']) + 1
    c['tids'] = list(range(_ti, _ti + cnt))
    _ti += cnt


def build_one(idx_lo, idx_hi):
    part = []
    for c in clusters[idx_lo:idx_hi]:
        tids = c['tids']
        part.append({
            'keep': c['keep'],
            'keeppath': c['keeppath'],
            'klink': file_rel(c['keeppath']),
            'kt': tids[0],
            'dups': c['dups'],
            'dlinks': [file_rel(p) for p in c['dups']],
            'dt': tids[1:],
            'dirs': c['dirs'],
            'mb': c['mb'],
        })
    fn = 'g_p%03d.js' % (idx_lo // CHUNK)
    with open(os.path.join(OUT_DIR, fn), 'w', encoding='utf-8') as f:
        f.write('window.PART[' + str(idx_lo // CHUNK) + ']=')
        f.write(json.dumps(part, ensure_ascii=False))
        f.write(';')
    return os.path.getsize(os.path.join(OUT_DIR, fn))


for old in os.listdir(OUT_DIR):
    if old.startswith('g_p') and old.endswith('.js'):
        os.remove(os.path.join(OUT_DIR, old))

n_chunks = (len(clusters) + CHUNK - 1) // CHUNK
sizes = []
for i in range(n_chunks):
    lo = i * CHUNK
    sizes.append(build_one(lo, min(lo + CHUNK, len(clusters))))

thumb_total = sum(os.path.getsize(os.path.join(THUMB_DIR, f)) for f in os.listdir(THUMB_DIR))

idx = {
    'total': len(clusters),
    'dups': total_dups,
    'mb': round(total_mb, 2),
    'chunk': CHUNK,
    'chunks': n_chunks,
    'chunkKB': round(max(sizes) / 1024),
    'partKB': round(sum(sizes) / 1024),
    'thumbN': len(os.listdir(THUMB_DIR)),
    'thumbMB': round(thumb_total / 1024 ** 2, 1),
}
with open(os.path.join(OUT_DIR, 'g_index.json'), 'w', encoding='utf-8') as f:
    json.dump(idx, f, ensure_ascii=False)
print('索引:', idx)

# ---------- B / C 类 ----------
for name, src in (('g_b_list.json', diff), ('g_c_list.json', conf)):
    fp = os.path.join(OUT_DIR, name)
    with open(fp, 'w', encoding='utf-8') as f:
        json.dump([[file_rel(r['保留路径']), r['保留文件'],
                    file_rel(r['重复文件路径']), r['重复文件名'],
                    r['所在文件夹']] for r in src], f, ensure_ascii=False)
    print('%s: %d 条 -> %.1f KB' % (name, len(src), os.path.getsize(fp) / 1024))

print('全部完成。')