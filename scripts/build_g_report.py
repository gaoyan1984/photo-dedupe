# -*- coding: utf-8 -*-
"""
照片查重 · 预览报告生成器（可移植版）

读取 run_dedupe.py 产出的「重复照片明细_全部.csv」
在**同一输出目录**下生成四页 HTML 报告：
    index.html   总览
    a.html       A 类 · 同名重复（可放心清理）
    b.html       B 类 · 异名相似（需逐张看图）
    c.html       C 类 · 确认真重复

以及配套数据文件 g_index.js / g_folders.js / g_b_list.js / g_c_list.js / g_pNNN.js
和缩略图 v2_*.jpg（run_dedupe 默认全部放在「扫描根目录/照片查重报告」子文件夹下，可整体拷贝）。四页 HTML 通过相对路径 <script src> 加载这些数据，
整个报告目录可整体拷贝、双击 index.html 即可看（file:// 下 fetch JSON 会被 CORS 拦，
所以数据一律包成 window.XXX 的 .js 文件）。

用法：
    python build_g_report.py [输出目录]
不传参数时，自动读取本脚本同目录下的 _last_work.txt（由 run_dedupe.py 写入）。

全程只读：只读取原图生成缩略图，绝不修改/移动/删除任何原始照片。
"""
import sys
import os
import csv
import json
import time
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from io import BytesIO
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, 'report_templates')
REPORT_FILES = ['index.html', 'a.html', 'b.html', 'c.html']

THUMB_W = 72        # 缩略图边长
THUMB_QUAL = 60     # JPEG 质量
CHUNK = 200         # 每个分片多少个簇
THUMB_WORKERS = 8   # 解码并发线程数


def find_work():
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        return sys.argv[1]
    lw = os.path.join(HERE, '_last_work.txt')
    if os.path.exists(lw):
        try:
            w = open(lw, encoding='utf-8').read().strip()
            if w and os.path.isdir(w):
                return w
        except Exception:
            pass
    return None


def file_rel(p):
    return 'file:///' + quote(p.replace('\\', '/'), safe='/:')

def fmt_size(mb):
    return ('%.2f GB' % (mb / 1024)) if mb >= 1024 else ('%.2f MB' % mb)


def main():
    work = find_work()
    if not work:
        print('未找到扫描输出目录。请先运行一次扫描（照片查重.bat 的选项 1/2/3），')
        print('或手动指定：python build_g_report.py <输出目录>')
        return 1
    work = os.path.normpath(work)

    SRC = os.path.join(work, '重复照片明细_全部.csv')
    if not os.path.exists(SRC):
        print('未在该目录找到「重复照片明细_全部.csv」：%s' % work)
        print('可能本次扫描未发现重复，或未执行过扫描。跳过报告生成。')
        # 清掉上一次遗留的报告指针，避免打开到旧报告
        lr = os.path.join(HERE, '_last_report.txt')
        if os.path.exists(lr):
            try:
                os.remove(lr)
            except Exception:
                pass
        return 0

    OUT_DIR = work
    THUMB_DIR = OUT_DIR          # 报告与缩略图同目录（已统一在 run_dedupe 生成的子文件夹下）
    os.makedirs(OUT_DIR, exist_ok=True)

    rows = list(csv.DictReader(open(SRC, encoding='utf-8-sig')))
    same = [r for r in rows if '疑似' in r['类别'] and r['保留文件'] == r['重复文件名']]
    diff = [r for r in rows if '疑似' in r['类别'] and r['保留文件'] != r['重复文件名']]
    conf = [r for r in rows if '确认真重复' in r['类别']]

    print('CSV 读入 %d 行：同名疑似 %d / 异名疑似 %d / 确认 %d'
          % (len(rows), len(same), len(diff), len(conf)))

    # ---------- A 类聚簇 ----------
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

    # ---------- 展平需要缩略图的路径，统一编号 ----------
    all_paths = []
    for c in clusters:
        all_paths.append(c['keeppath'])
        all_paths.extend(c['dups'])

    def add_pair(r, box):
        all_paths.append(r['保留路径'])
        all_paths.append(r['重复文件路径'])
        box.append((len(all_paths) - 2, len(all_paths) - 1))

    b_tids, c_tids = [], []
    for r in diff:
        add_pair(r, b_tids)
    for r in conf:
        add_pair(r, c_tids)

    n = len(all_paths)
    print('A类 簇 %d / 副本 %d / %.2f GB / B+C 需缩略图 %d 张'
          % (len(clusters), total_dups, total_mb / 1024, n))

    # ---------- A/B/C 三类体积汇总 ----------
    b_mb = sum(float(r['单张大小KB']) for r in diff) / 1024.0
    c_mb = sum(float(r['单张大小KB']) for r in conf) / 1024.0

    # 扫描总量（来自 run_dedupe 的 summary.json，给总览副标题）
    sj = os.path.join(work, 'summary.json')
    total_imgs = total_gb = None
    if os.path.exists(sj):
        try:
            s = json.load(open(sj, encoding='utf-8'))
            total_imgs = s.get('total_photos')
            total_gb = s.get('total_gb')
        except Exception:
            pass

    # ---------- 分片编号（与 all_paths 顺序一致） ----------
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

    n_chunks = (len(clusters) + CHUNK - 1) // CHUNK
    sizes = []
    for i in range(n_chunks):
        lo = i * CHUNK
        sizes.append(build_one(lo, min(lo + CHUNK, len(clusters))))

    # ---------- A 类文件夹索引 ----------
    def _dir_of(p):
        i = max(p.rfind('\\'), p.rfind('/'))
        return p[:i] if i > 0 else p

    by_folder = defaultdict(list)
    for gi, c in enumerate(clusters):
        for d in set([_dir_of(c['keeppath'])] + [_dir_of(p) for p in c['dups']]):
            by_folder[d].append(gi)

    folder_stat = []
    for d, gis in by_folder.items():
        mb = 0.0
        ndup = 0
        for gi in gis:
            c = clusters[gi]
            each = c['mb'] / len(c['dups'])
            for p in c['dups']:
                if _dir_of(p) == d:
                    ndup += 1
                    mb += each
        folder_stat.append([d, len(gis), ndup, round(mb, 2)])

    folder_stat.sort(key=lambda x: -x[3])
    with open(os.path.join(OUT_DIR, 'g_folders.js'), 'w', encoding='utf-8') as f:
        f.write('window.FDATA=')
        f.write(json.dumps({'folders': folder_stat,
                            'byFolder': {d: v for d, v in by_folder.items()}},
                           ensure_ascii=False))
        f.write(';')
    print('g_folders.js: %d 个文件夹 -> %.1f KB'
          % (len(folder_stat), os.path.getsize(os.path.join(OUT_DIR, 'g_folders.js')) / 1024))

    # ---------- 索引（总览用） ----------
    idx = {
        'total': len(clusters),
        'dups': total_dups,
        'mb': round(total_mb, 2),
    'chunk': CHUNK,
    'chunks': n_chunks,
    'chunkKB': round(max(sizes) / 1024) if sizes else 0,
    'partKB': round(sum(sizes) / 1024),
        'thumbN': 0,
        'thumbMB': 0.0,
        'a_groups': len(clusters),
        'a_dups': total_dups,
        'a_folders': len(folder_stat),
        'a_mb_s': fmt_size(total_mb),
        'b_n': len(diff),
        'b_mb': round(b_mb, 2),
        'b_mb_s': fmt_size(b_mb),
        'c_n': len(conf),
        'c_mb': round(c_mb, 2),
        'c_mb_s': fmt_size(c_mb),
        'total_imgs': total_imgs,
        'total_gb': total_gb,
    }
    with open(os.path.join(OUT_DIR, 'g_index.js'), 'w', encoding='utf-8') as f:
        f.write('window.IDX=')
        f.write(json.dumps(idx, ensure_ascii=False))
        f.write(';')
    print('索引:', idx)

    # ---------- B / C 类 ----------
    def bc_list(src, tids):
        out = []
        for r, (kt, dt) in zip(src, tids):
            out.append([file_rel(r['保留路径']), r['保留文件'],
                        file_rel(r['重复文件路径']), r['重复文件名'],
                        r['所在文件夹'], kt, dt])
        return out

    blist = bc_list(diff, b_tids)
    with open(os.path.join(OUT_DIR, 'g_b_list.js'), 'w', encoding='utf-8') as f:
        f.write('window.BLIST=')
        f.write(json.dumps(blist, ensure_ascii=False))
        f.write(';')
    print('g_b_list.js: %d 条 -> %.1f KB' % (len(blist), os.path.getsize(os.path.join(OUT_DIR, 'g_b_list.js')) / 1024))

    clist = bc_list(conf, c_tids)
    with open(os.path.join(OUT_DIR, 'g_c_list.js'), 'w', encoding='utf-8') as f:
        f.write('window.CLIST=')
        f.write(json.dumps(clist, ensure_ascii=False))
        f.write(';')
    print('g_c_list.js: %d 条 -> %.1f KB' % (len(clist), os.path.getsize(os.path.join(OUT_DIR, 'g_c_list.js')) / 1024))

    print('=== 数据文件已全部写好，报告立即可用；下面开始生成缩略图（较慢，后台进行）===')

    # ---------- 复制四页 HTML 模板 ----------
    copied = 0
    for t in REPORT_FILES:
        src = os.path.join(TEMPLATES, t)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(OUT_DIR, t))
            copied += 1
    print('已复制报告页面 %d 个到 %s' % (copied, OUT_DIR))

    # 数据文件 + 页面已就绪，先把报告入口写好，方便立即打开；缩略图随后后台补齐。
    with open(os.path.join(HERE, '_last_report.txt'), 'w', encoding='utf-8') as f:
        f.write(os.path.join(OUT_DIR, 'index.html'))

    # ---------- 缩略图（最后做，慢；生成期间页面图逐步出现） ----------
    def thumb_file(i):
        return os.path.join(THUMB_DIR, 'v2_%05d.jpg' % i)

    def make_thumb(arg):
        i, path = arg
        tf = thumb_file(i)
        try:
            im = Image.open(path)
            im.draft('RGB', (THUMB_W * 4, THUMB_W * 4))
            im = im.convert('RGB')
            im.thumbnail((THUMB_W, THUMB_W))
            buf = BytesIO()
            im.save(buf, 'JPEG', quality=THUMB_QUAL, optimize=False)
            tmp = tf + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(buf.getvalue())
            os.replace(tmp, tf)
            return i, True
        except Exception:
            return i, False

    # 断点续做：已存在且非空（>=1字节）的缩略图直接跳过，中断后重跑只补缺失的。
    todo = [(i, p) for i, p in enumerate(all_paths)
            if not os.path.exists(thumb_file(i)) or os.path.getsize(thumb_file(i)) < 1]
    print('待生成缩略图 %d 张（已存在且有效的将跳过）...' % len(todo))

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

    # 缩略图统计回填索引
    tnames = [f for f in os.listdir(THUMB_DIR) if f.startswith('v2_') and f.endswith('.jpg')]
    thumb_total = sum(os.path.getsize(os.path.join(THUMB_DIR, f)) for f in tnames)
    idx['thumbN'] = len(tnames)
    idx['thumbMB'] = round(thumb_total / 1024 ** 2, 1)
    with open(os.path.join(OUT_DIR, 'g_index.js'), 'w', encoding='utf-8') as f:
        f.write('window.IDX=')
        f.write(json.dumps(idx, ensure_ascii=False))
        f.write(';')

    # 记录报告入口，供批处理自动打开
    with open(os.path.join(HERE, '_last_report.txt'), 'w', encoding='utf-8') as f:
        f.write(os.path.join(OUT_DIR, 'index.html'))

    print('全部完成。报告目录：%s' % OUT_DIR)
    return 0


if __name__ == '__main__':
    sys.exit(main())
