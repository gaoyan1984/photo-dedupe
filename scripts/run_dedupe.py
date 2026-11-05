# -*- coding: utf-8 -*-
"""
照片查重 —— 一键管道
用法: python run_dedupe.py <目标盘符或目录> [工作目录]
例  : python run_dedupe.py F:\
      python run_dedupe.py "F:\我的照片"
只读：不移动、不重命名、不删除任何文件。
"""
import os, sys, json, csv, time, hashlib, urllib.parse, html
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageFile, ImageChops

ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = None

# ============ 参数 ============
# 支持三种指定方式，可混用：
#   1) 命令行位置参数：python run_dedupe.py "F:\" "E:\照片"
#   2) --paths "F:\;E:\照片;D:\单反"     （分号分隔，含盘符与子目录均可）
#   3) 不给任何参数 → 进入交互式选路径菜单
# 坑（2026-10-25 修）：原来用 for+enumerate 解析，--paths 的值会被
# positional 分支（elif not a.startswith('-')）再追加一遍整串，
# 导致 TARGETS 混入 "G:\;H:\" 这种没拆开的路径，直接「路径不存在」退出。
# 改成 while 手动推进，消费掉选项的值后 i+=2 跳过。
ARGS = sys.argv[1:]
TARGETS = []            # 最终要扫描的路径列表
WORK = None             # 输出目录
_i = 0
while _i < len(ARGS):
    a = ARGS[_i]
    if a in ('--paths', '-p') and _i + 1 < len(ARGS):
        TARGETS += [x.strip().strip('"') for x in ARGS[_i + 1].split(';') if x.strip()]
        _i += 2
        continue
    elif a.startswith('--paths='):
        TARGETS += [x.strip().strip('"') for x in a.split('=', 1)[1].split(';') if x.strip()]
    elif a in ('--work', '-w') and _i + 1 < len(ARGS):
        WORK = ARGS[_i + 1]
        _i += 2
        continue
    elif a.startswith('--work='):
        WORK = a.split('=', 1)[1]
    elif not a.startswith('-'):
        TARGETS.append(a)
    _i += 1


def list_drives():
    """列出可用磁盘（Windows）。
    坑：Windows 的 os 没有 statvfs，容量要用 shutil.disk_usage。"""
    import string, shutil
    res = []
    for c in string.ascii_uppercase:
        d = '%s:\\' % c
        if not os.path.exists(d):
            continue
        try:
            u = shutil.disk_usage(d)
            res.append((d, u.total / 1024**3, u.free / 1024**3))
        except Exception:
            res.append((d, 0.0, 0.0))
    return res


def interactive_pick():
    """交互式选路径：先选盘，再选该盘下的文件夹（可多选）。
    输入 0 返回上级菜单；直接回车用序号选；多个用空格分隔。
    """
    while True:
        drives = list_drives()
        if not TARGETS:
            print('\n' + '=' * 54)
            print('  照片查重 · 选择要扫描的磁盘')
            print('=' * 54)
            for i, (d, tot, free) in enumerate(drives, 1):
                print('  [%d] %-4s 总 %6.1f GB  可用 %6.1f GB' % (i, d, tot, free))
            print('  [0] 手动输入路径')
            print('=' * 54)
            raw = input('请选择（可多选，空格分隔，如 "1 2"；直接回车=只查C盘）: ').strip()
            if not raw:
                TARGETS.append('C:\\')
                break
            if raw == '0':
                p = input('请输入文件夹路径: ').strip().strip('"')
                if p:
                    TARGETS.append(p)
                continue
            bad = []
            for tok in raw.split():
                if tok.isdigit() and 1 <= int(tok) <= len(drives):
                    TARGETS.append(drives[int(tok) - 1][0])
                else:
                    bad.append(tok)
            if bad:
                print('[提示] 无效项已忽略: %s' % ' '.join(bad))
            if TARGETS:
                break
            continue
        # 已选盘 -> 选子文件夹
        cur = TARGETS[0]
        print('\n  当前磁盘: %s' % cur)
        try:
            subs = sorted(d for d in os.listdir(cur)
                          if os.path.isdir(os.path.join(cur, d))
                          and d.lower() not in SKIP)
        except OSError:
            TARGETS.clear()
            continue
        if not subs:
            print('  （该盘下没有子文件夹，将直接扫描整盘）')
            break
        print('-' * 54)
        for i, s in enumerate(subs, 1):
            print('  [%d] %s' % (i, s))
        print('  [0] 返回磁盘列表（重选）')
        print('  [直接回车] 扫描已选的整个磁盘/文件夹，不细分')
        print('-' * 54)
        raw = input('要加入扫描的文件夹序号（空格分隔多选；0=返回；回车=就这些）: ').strip()
        if raw == '0':
            TARGETS.clear()
            continue
        if not raw:
            break
        for tok in raw.split():
            if tok.isdigit() and 1 <= int(tok) <= len(subs):
                TARGETS.append(os.path.join(cur, subs[int(tok) - 1]))
    return TARGETS


# 注意：交互菜单只在 main() 里、且命令行确实没给路径时才触发。
# 不要放到模块顶层——否则别人 import 这个脚本时会被强制进入菜单而卡死。

# ============ 环境自检 ============
def check_env():
    errs = []
    try:
        import PIL
        # 坑：版本号是字符串，"12.3.0" < "9" 为 True，会把新版误判成"过低"。
        # 必须按数字逐段比较。
        try:
            parts = [int(x) for x in PIL.__version__.split('.')[:2]]
            major = parts[0]
        except (ValueError, IndexError):
            major = 0
        if major < 9:
            errs.append('Pillow 版本过低: %s' % PIL.__version__)
    except ImportError:
        errs.append('缺少 Pillow')
    py = sys.executable
    if 'AppData\\Local\\Microsoft\\WindowsApps' in py:
        errs.append('当前是系统 Python，缺依赖，请换用隔离环境解释器')
    return errs

# ============ 阶段 1：扫描 ============
EXT = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.gif', '.bmp', '.webp',
       '.tif', '.tiff', '.raw', '.cr2', '.nef', '.arw', '.dng', '.raf', '.orf'}
SKIP = {'$recycle.bin', 'system volume information', '$windows.~bt'}

def scan(roots):
    """roots: 单个路径或路径列表。多根时按文件绝对路径去重，
    避免选了 E:\\ 和 E:\\照片 这种重叠范围导致同一文件被扫两次。"""
    if isinstance(roots, str):
        roots = [roots]
    seen = set()
    out = []
    for root in roots:
        for dp, dns, fns in os.walk(root, topdown=True, onerror=lambda e: None):
            dns[:] = [d for d in dns
                      if d.lower() not in SKIP and not d.lower().startswith('$')]
            for fn in fns:
                if os.path.splitext(fn)[1].lower() not in EXT:
                    continue
                full = os.path.join(dp, fn)
                key = os.path.normcase(os.path.abspath(full))
                if key in seen:
                    continue
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                if st.st_size == 0:
                    continue
                seen.add(key)
                out.append({'path': full, 'dir': dp, 'name': fn,
                            'size': st.st_size, 'mtime': int(st.st_mtime)})
    return out

def get_size(it):
    try:
        with Image.open(it['path']) as im:
            it['w'], it['h'] = im.size
    except Exception:
        it['bad'] = True
    return it

# ============ 阶段 2：MD5 精确查重 ============
def md5_of(path, chunk=1 << 20):
    h = hashlib.md5()
    try:
        with open(path, 'rb') as f:
            while True:
                b = f.read(chunk)
                if not b: break
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()

def md5_groups(files):
    by_size = defaultdict(list)
    for it in files:
        by_size[it['size']].append(it)
    cand = [x for g in by_size.values() if len(g) > 1 for x in g]
    print('   大小相同候选: %d' % len(cand))
    by_md5 = defaultdict(list)
    t0 = time.time()
    for i, it in enumerate(cand, 1):
        m = md5_of(it['path'])
        if m:
            it['md5'] = m
            by_md5[m].append(it)
        if i % 5000 == 0 or i == len(cand):
            el = time.time() - t0
            print('      MD5 进度 %d/%d，已用 %.0f 秒，预计还需 %.0f 秒'
                  % (i, len(cand), el, el / i * (len(cand) - i)))
    return [g for g in by_md5.values() if len(g) > 1]

# ============ 阶段 3：感知哈希 ============
# 说明：这里的耗时几乎全在 JPEG/PNG 解码上（CPU 密集），
# 不是 Python 循环慢。单进程约 17 分钟 / 6572 张。
# 提速手段：① 提高线程数 ② 先按尺寸过滤（分辨率差太多的不可能是同一张）
MIN_EDGE_RATIO = 0.25   # 短边比小于此值直接跳过配对

def phash(path):
    """先转灰度再 draft，保证结果与标准 dHash 一致；tobytes() 比 getdata() 快"""
    try:
        with Image.open(path) as im:
            im = im.convert('L')
            im.draft('L', (17, 16))
            if im.size != (17, 16):
                im = im.resize((17, 16), Image.LANCZOS)
            px = im.tobytes()
            n = len(px)
            avg = sum(px) / n
            ah = 0
            for p in px:
                ah = (ah << 1) | (1 if p > avg else 0)
            dh = 0
            for r in range(16):
                b = r * 17
                for c in range(16):
                    dh = (dh << 1) | (1 if px[b + c] > px[b + c + 1] else 0)
            return dh, ah
    except Exception:
        return None

def ham(a, b):
    return bin(a ^ b).count('1')

def similar_pairs(files, dmax=10, amax=12, workers=12):
    """workers 建议 8-16；照片是 CPU 密集解码，线程数受限于 CPU 核数"""
    # 坑（2026-10-25）：19.6 万张全量哈希要跑 4 小时，原来一句进度都不打，
    # 用户盯着「[3/5] 感知哈希扫描全量」以为卡死。改成每 5000 张报一次进度+ETA。
    n_all = len(files)
    done = [0]
    t0 = time.time()

    def phash_p(path):
        r = phash(path)
        done[0] += 1
        d = done[0]
        if d % 5000 == 0 or d == n_all:
            el = time.time() - t0
            print('      哈希进度 %d/%d，已用 %.0f 秒，预计还需 %.0f 秒'
                  % (d, n_all, el, el / d * (n_all - d)))
        return r

    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(phash_p, [f['path'] for f in files]))
    valid = []
    for f, r in zip(files, res):
        if r:
            f['dh'], f['ah'] = r
            valid.append(f)
    print('      哈希完成: %d 张' % len(valid))

    buckets = defaultdict(list)
    for idx, f in enumerate(valid):
        buckets[f['ah'] >> (64 - 24)].append(idx)
    pairs = []
    seen = set()
    for lst in buckets.values():
        if len(lst) < 2:
            continue
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                x, y = lst[i], lst[j]
                pr = (x, y) if x < y else (y, x)
                if pr in seen:
                    continue
                seen.add(pr)
                a, b = valid[x], valid[y]
                if ham(a['dh'], b['dh']) > dmax:
                    continue
                # 面积比 + 短边比双重过滤，避免大图配小图
                sa, sb = a['w'] * a['h'], b['w'] * b['h']
                if sa and sb and max(sa, sb) / min(sa, sb) > 6:
                    continue
                ea, eb = min(a['w'], a['h']), min(b['w'], b['h'])
                if ea and eb and min(ea, eb) / max(ea, eb) < MIN_EDGE_RATIO:
                    continue
                pairs.append((a['path'], b['path']))
    return valid, pairs

# ============ 阶段 4：全分辨率严格核验 ============
BIG_OK = 0.05        # 显著差异像素占比阈值(%)
SIZE_OK = 1.03       # 文件大小比阈值

def strict_ok(p1, p2):
    i1, i2 = p1, p2
    sr = max(i1['size'], i2['size']) / max(1, min(i1['size'], i2['size']))
    try:
        a = Image.open(p1['path']).convert('RGB')
        b = Image.open(p2['path']).convert('RGB')
        if a.size != b.size:
            b = b.resize(a.size, Image.LANCZOS)
        st = ImageChops.difference(a, b).convert('L')
        h = st.histogram(); tot = sum(h)
        big = sum(h[30:]) / tot * 100
    except Exception:
        return None
    # 双条件：像素高度一致 + 文件大小接近（防纯色图误并）
    return big < BIG_OK and sr <= SIZE_OK

def build_groups(valid, pairs, md5g):
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb

    info = {f['path']: f for f in valid}
    for a, b in pairs:
        union(a, b)
    for g in md5g:
        ps = [x['path'] for x in g]
        for p in ps[1:]:
            union(ps[0], p)

    # 以组内首元素为代表元做严格核验，剔除不合格成员
    groups = defaultdict(list)
    for k in list(parent.keys()):
        groups[find(k)].append(k)

    # 先收集所有待核验的（代表元, 成员）对，再统一处理。
    # 坑（2026-10-25，G+H 两盘 19.6 万张实测）：原来是串行逐个 strict_ok，
    # 且 MD5 相同的文件（内容必然相同）也要全分辨率解码比对——
    # 备份盘场景下绝大多数正是这种，第 4 步要跑几十个小时，像卡死一样。
    # 两个优化：① MD5 相同直接判过，不解码；② 其余 12 线程并行，带进度和 ETA。
    todo = []
    for members in groups.values():
        uniq = sorted(set(members))
        if len(uniq) < 2:
            continue
        rep = uniq[0]
        for m in uniq[1:]:
            todo.append((rep, m))

    total = len(todo)
    if total == 0:
        return []
    done = [0]
    t0 = time.time()

    def check(item):
        rep, m = item
        ra, ma = info[rep], info[m]
        if ra.get('md5') and ma.get('md5') and ra['md5'] == ma['md5']:
            ok = True                       # 内容必然相同，无需解码
        else:
            ok = strict_ok(ra, ma)
        done[0] += 1
        d = done[0]
        if d % 500 == 0 or d == total:
            el = time.time() - t0
            print('      严格核验 %d/%d，已用 %.0f 秒，预计还需 %.0f 秒'
                  % (d, total, el, el / d * (total - d)))
        return rep, m, ok

    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(check, todo))

    keepmap = defaultdict(list)
    for rep, m, ok in results:
        if ok:
            keepmap[rep].append(m)
    out = []
    for rep, ms in keepmap.items():
        keep = [rep] + sorted(ms)
        if len(keep) > 1:
            out.append(keep)
    return out

# ============ 分类 ============
SOFTWARE_HINTS = ['tencent files', 'wechat files', 'all users', '剪映', 'jianyingpro',
                  '360', 'upupoo', '工具软件', '录屏截屏', 'fscapture',
                  'programdata', 'program files', 'tmmxgq', 'kugou', 'msdia']

def kind(path):
    pl = path.lower()
    return 'software' if any(k in pl for k in SOFTWARE_HINTS) else 'personal'

# ============ 主流程 ============
def main():
    t0 = time.time()
    errs = check_env()
    if errs:
        print('[环境问题] ' + '; '.join(errs))
        sys.exit(1)

    roots = [os.path.abspath(p) for p in TARGETS]
    if not roots:
        # 命令行没给路径 → 进交互菜单
        try:
            interactive_pick()
        except (EOFError, KeyboardInterrupt):
            print('\n已取消。')
            return
        roots = [os.path.abspath(p) for p in TARGETS]
    missing = [p for p in roots if not os.path.isdir(p)]
    if missing:
        print('[错误] 路径不存在: %s' % '; '.join(missing))
        sys.exit(1)
    if not roots:
        print('[错误] 没有可扫描的路径。')
        sys.exit(1)

    # 输出目录：显式 --work 时尊重用户指定目录；否则默认在「扫描根目录」下
    # 新建「照片查重报告」子文件夹统一存放全部产物（报告/缩略图/CSV/JSON），
    # 避免把一堆文件直接撒在盘根、显得很乱。
    REPORT_SUBDIR = '照片查重报告'
    work = WORK if WORK else os.path.join(roots[0], REPORT_SUBDIR)
    os.makedirs(work, exist_ok=True)
    target_label = ' + '.join(roots)

    print('[1/5] 扫描 %s ...' % target_label)
    files = scan(roots)
    if not files:
        print('[结果] 未找到任何图片文件。')
        return
    print('      共 %d 个图片，%.2f GB' % (len(files), sum(f['size'] for f in files) / 1024**3))

    print('[2/5] 读取分辨率 + MD5 精确查重 ...')
    files = list(ThreadPoolExecutor(max_workers=8).map(get_size, files))
    files = [f for f in files if not f.get('bad')]
    md5g = md5_groups(files)
    print('      MD5 一致组: %d' % len(md5g))

    print('[3/5] 感知哈希扫描全量 ...')
    valid, pairs = similar_pairs(files)
    print('      候选相似对: %d' % len(pairs))

    print('[4/5] 全分辨率严格核验 ...')
    groups = build_groups(valid, pairs, md5g)
    info = {f['path']: f for f in valid}
    personal = [g for g in groups if sum(kind(p) == 'personal' for p in g) > len(g) / 2]
    software = [g for g in groups if g not in personal]
    print('      确认重复 %d 组 / 疑似 %d 组' % (len(software), len(personal)))

    print('[5/5] 生成报告与预览 ...')
    rows = []
    for label, gs in [('确认真重复', software), ('疑似(需人工确认)', personal)]:
        for gi, grp in enumerate(sorted(gs, key=lambda x: -max(info[p]['size'] for p in x)), 1):
            items = [info[p] for p in grp]
            kp = min(items, key=lambda x: (x['mtime'], x['path']))
            others = sorted([x for x in items if x['path'] != kp['path']],
                            key=lambda x: (x['mtime'], x['path']))
            rc = sum(x['size'] for x in others)
            cross = len({x['dir'] for x in items}) > 1
            for x in others:
                rows.append({
                    '组号': gi, '类别': label, '本组文件数': len(items),
                    '保留文件': kp['name'], '保留路径': kp['path'],
                    '重复文件名': x['name'], '重复文件路径': x['path'],
                    '所在文件夹': x['dir'], '是否跨文件夹': '是' if cross else '否',
                    '单张大小KB': round(x['size'] / 1024, 1),
                    '本组可释放KB': round(rc / 1024, 1),
                    '修改时间': time.strftime('%Y-%m-%d %H:%M', time.localtime(x['mtime'])),
                })

    if not rows:
        print('[结果] 未发现任何重复图片。硬盘很干净！')
        return

    csvp = os.path.join(work, '重复照片明细_全部.csv')
    with open(csvp, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    total_kb = sum(r['单张大小KB'] for r in rows)
    dupset = {r['重复文件路径'] for r in rows}
    summary = {
        'target': target_label, 'time': time.strftime('%Y-%m-%d %H:%M'),
        'total_photos': len(valid),
        'total_gb': round(sum(f['size'] for f in valid) / 1024**3, 2),
        'dir_count': len({f['dir'] for f in valid}),
        'confirmed_groups': len(software), 'confirmed_redundant': sum(1 for r in rows if r['类别'] == '确认真重复'),
        'confirmed_mb': round(sum(r['单张大小KB'] for r in rows if r['类别'] == '确认真重复') / 1024, 2),
        'suspect_groups': len(personal),
        'suspect_mb': round(sum(r['单张大小KB'] for r in rows if r['类别'] != '确认真重复') / 1024, 2),
        'reclaim_mb': round(total_kb / 1024, 2),
        'elapsed_sec': int(time.time() - t0),
    }
    json.dump(summary, open(os.path.join(work, 'summary.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    make_clickable(work, valid, rows, summary)
    make_link_csv(work, valid, rows)

    print()
    print('=' * 52)
    for k, v in summary.items():
        print('  %-22s %s' % (k, v))
    print('=' * 52)
    print('输出目录: %s' % work)
    for f in ['重复照片明细_全部.csv', '全部照片清单_可点击.html',
              '全部照片清单_带链接.csv', 'summary.json']:
        print('  · %s' % f)
    print('  · index.html / a.html / b.html / c.html (报告页，由「报告生成器」写入)')
    print('※ 本工具只读，未移动/重命名/删除任何文件。')

    # 记录本次输出目录，供批处理（照片查重.bat）在扫描结束后自动调用报告生成器
    try:
        _lw = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_last_work.txt')
        with open(_lw, 'w', encoding='utf-8') as _fh:
            _fh.write(work)
    except Exception:
        pass


# ============ 可点击清单（全部照片，file:// 链接） ============
def make_clickable(work, valid, rows, summary):
    E = html.escape
    def flink(p):
        return 'file:///' + urllib.parse.quote(p.replace('\\', '/'), safe='/:')
    dupset = {r['重复文件路径'] for r in rows}
    bydir = defaultdict(list)
    for x in sorted(valid, key=lambda y: (y['dir'].lower(), y['name'].lower())):
        bydir[x['dir']].append(x)
    dirsize = defaultdict(float)
    for x in valid:
        dirsize[x['dir']] += x['size'] / 1024 / 1024

    blocks = []
    for d, items in sorted(bydir.items(), key=lambda x: -len(x[1])):
        trs = ''.join(
            '<tr class="%s"><td class="n">%d</td>'
            '<td><a class="lk2" href="%s" title="%s">%s</a></td>'
            '<td class="c dim">%d×%d</td><td class="n">%.0f</td>'
            '<td class="dim">%s</td></tr>'
            % ('dup' if p['path'] in dupset else '', i + 1,
               flink(p['path']), E(p['path']), E(p['name']),
               p['w'], p['h'], p['size'] / 1024,
               time.strftime('%Y-%m-%d %H:%M', time.localtime(p['mtime'])))
            for i, p in enumerate(items))
        blocks.append(
            '<details class="dir"><summary>'
            '<span class="dn">📁 %s</span><span class="dm">%d 张 · %.1f MB</span>'
            '<span class="dt">%d 张重复</span></summary>'
            '<table><thead><tr><th class="c">#</th><th>文件名（点击打开）</th>'
            '<th class="c">分辨率</th><th class="n">KB</th><th>修改时间</th></tr></thead>'
            '<tbody>%s</tbody></table></details>'
            % (E(d), len(items), dirsize[d],
               sum(1 for p in items if p['path'] in dupset), trs))

    HTML = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
            '<title>照片清单 · 可点击</title><style>'
            '*{margin:0;padding:0;box-sizing:border-box}'
            'body{background:#0f1115;color:#e6e8eb;font-family:"Microsoft YaHei",sans-serif;padding:26px 18px;font-size:14px}'
            '.w{max-width:1420px;margin:0 auto}h1{font-size:24px;font-weight:600;margin-bottom:5px}'
            '.s{color:#8b949e;font-size:13px;margin-bottom:18px}'
            '.tip{background:#141c2b;border:1px solid #24406b;border-radius:8px;padding:13px 17px;font-size:13.5px;color:#a9c7f5;margin-bottom:20px}'
            '.tip b{color:#4a9eff}'
            '.bar{display:flex;gap:12px;align-items:center;margin-bottom:16px;flex-wrap:wrap}'
            'input[type=search]{background:#171a21;border:1px solid #30363d;border-radius:7px;padding:8px 13px;color:#e6e8eb;font-size:13.5px;width:290px;outline:none}'
            'input[type=search]:focus{border-color:#4a9eff}'
            'table{width:100%;border-collapse:collapse;font-size:13px;background:#171a21}'
            'th{background:#1f2430;color:#8b949e;font-weight:500;text-align:left;padding:9px 12px;font-size:12px}'
            'td{padding:7px 12px;border-bottom:1px solid #1c2029}'
            'tbody tr:hover{background:#1b2020}'
            '.c{text-align:center}.n{text-align:right;white-space:nowrap}.dim{color:#6e7681;font-size:12px}'
            'a.lk2{color:#c9d1d9;text-decoration:none;border-bottom:1px dotted #2d5a8a;font-size:12.5px;font-family:Consolas,monospace}'
            'a.lk2:hover{color:#7ec0ff;border-bottom-style:solid}'
            'details.dir{background:#171a21;border:1px solid #262b35;border-radius:8px;margin-bottom:8px;overflow:hidden}'
            'summary{cursor:pointer;padding:12px 15px;display:flex;gap:12px;align-items:center}'
            'summary:hover{background:#1b2028}'
            '.dn{font-family:Consolas,monospace;font-size:13px}.dm{font-size:12px;color:#8b949e}'
            '.dt{font-size:11.5px;color:#f0a63c;margin-left:auto}'
            'details.dir table{background:#14171d}tr.dup td:first-child{border-left:2px solid #f0a63c}'
            '.foot{margin-top:26px;padding-top:15px;border-top:1px solid #262b35;font-size:12.5px;color:#6e7681}'
            '</style></head><body><div class="w">'
            '<h1>照片清单 · 点击路径直接打开</h1>'
            '<div class="s">@@TARGET@@　|　@@TOTAL@@ 张图片　|　@@DIRS@@ 个文件夹</div>'
            '<div class="tip">💡 下方<b>文件名都是链接，单击直接打开照片</b>（默认用系统看图程序）。'
            '重复副本行左边有<b style="color:#f0a63c">橙色标记</b>。点文件夹标题展开。</div>'
            '<div class="bar"><input type="search" id="q" placeholder="搜索文件名或文件夹…" oninput="f2(this.value)">'
            '<span class="dm">共 @@TOTAL@@ 张</span></div>'
            '<div>@@BLOCKS@@</div>'
            '<div class="foot">生成于 @@TIME@@　|　本页为只读索引，点击链接不会移动或删除任何文件</div>'
            '</div><script>'
            'function f2(v){v=v.toLowerCase().trim();var n=0;'
            'document.querySelectorAll("details.dir").forEach(function(d){var hit=d.querySelector(".dn").textContent.toLowerCase().indexOf(v)>=0;'
            'if(!hit){d.querySelectorAll("tbody tr").forEach(function(tr){'
            'if(tr.textContent.toLowerCase().indexOf(v)<0)tr.classList.add("hide");else{tr.classList.remove("hide");hit=true;}});}'
            'if(hit&&v!==""){d.classList.remove("hide");d.open=true;n++;}else d.classList.add("hide");});'
            'document.querySelector(".bar .dm").textContent=v===""?"共 @@TOTAL@@ 张":"匹配 "+n+" 个文件夹";}'
            '</script></body></html>')

    out = HTML
    for k, v in {'@@TARGET@@': E(summary['target']), '@@TOTAL@@': str(summary['total_photos']),
                 '@@DIRS@@': str(summary['dir_count']),
                 '@@TIME@@': summary['time'],
                 '@@BLOCKS@@': ''.join(blocks)}.items():
        out = out.replace(k, v)
    # hide 类补充
    out = out.replace('tbody tr:hover{background:#1b2020}',
                      'tbody tr:hover{background:#1b2028}.hide{display:none}')
    open(os.path.join(work, '全部照片清单_可点击.html'), 'w', encoding='utf-8').write(out)


# ============ 带链接 CSV ============
def make_link_csv(work, valid, rows):
    dupset = {r['重复文件路径'].replace('/', '\\') for r in rows}
    with open(os.path.join(work, '全部照片清单_带链接.csv'), 'w',
              encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['序号', '文件名', '所在文件夹', '完整路径', '点击打开',
                    '分辨率', '大小KB', '修改时间', '是否重复副本'])
        for i, x in enumerate(sorted(valid, key=lambda y: (y['dir'].lower(), y['name'].lower())), 1):
            full = x['path'].replace('/', '\\')
            w.writerow([i, x['name'], x['dir'], full,
                        '=HYPERLINK("%s","点击查看")' % full.replace('"', '""'),
                        '%d×%d' % (x['w'], x['h']), round(x['size'] / 1024, 1),
                        time.strftime('%Y-%m-%d %H:%M', time.localtime(x['mtime'])),
                        '是' if full in dupset else ''])


# ============ 缩略图 ============
def make_thumbs(info, rows, thumbs):
    need = {}
    for r in rows:
        need[r['保留路径']] = 'keep'
        need[r['重复文件路径']] = 'dup'
    def one(item):
        path = item[0]
        h = hashlib.md5(path.encode('utf-8')).hexdigest()[:16] + '.jpg'
        out = os.path.join(thumbs, h)
        try:
            if not (os.path.exists(out) and os.path.getsize(out) > 0):
                with Image.open(path) as im:
                    im = im.convert('RGB'); im.thumbnail((720, 720), Image.LANCZOS)
                    im.save(out, 'JPEG', quality=82, optimize=True)
            return {'path': path, 'thumb': h, 'ok': True}
        except Exception:
            return {'path': path, 'thumb': None, 'ok': False}
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(one, need.items()))
    json.dump(res, open(os.path.join(thumbs, '_map.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)
    print('      缩略图 %d 张' % sum(1 for r in res if r['ok']))


# ============ 预览选择页 ============
def make_index(work, thumbs, info, rows, summary, software, personal):
    E = html.escape
    def fs(p):
        try: return os.path.getsize(p)
        except OSError: return 0
    def flink(p):
        return 'file:///' + urllib.parse.quote(p.replace('\\', '/'), safe='/:')

    tmap = {t['path']: t for t in
            json.load(open(os.path.join(thumbs, '_map.json'), encoding='utf-8'))}
    groups = defaultdict(list)
    for r in rows:
        groups[(r['类别'], r['组号'], r['保留路径'])].append(r)
    order = sorted(groups.items(), key=lambda x: (0 if '疑似' in x[0][0] else 1,
                  -max(fs(p) for p in [y['重复文件路径'] for y in x[1]] + [x[0][2]])))
    sz = {}
    for r in rows:
        sz[r['保留路径']] = fs(r['保留路径'])
        sz[r['重复文件路径']] = fs(r['重复文件路径'])

    cards = []
    for gi, ((cat, gid, keep), rs) in enumerate(order, 1):
        is_s = '疑似' in cat
        free = sum(fs(r['重复文件路径']) for r in rs)
        dirs = {r['所在文件夹'] for r in rs} | {os.path.dirname(keep)}
        items = []
        def pick(path, is_keep):
            t = tmap.get(path)
            th = ('<img src="thumbs/%s" loading="lazy" alt="">' % t['thumb']) \
                 if t and t.get('thumb') else '<div class="nopic">无预览</div>'
            wh = '%d×%d' % (info[path]['w'], info[path]['h']) if path in info else '—'
            return ('<div class="pick%s" data-p="%s"><div class="ph">%s</div>'
                    '<div class="pi"><div class="fn">%s</div>'
                    '<div class="pp" title="%s">%s</div>'
                    '<div class="mt">%.0f KB　%s</div></div>'
                    '<label class="rad"><input type="checkbox">'
                    '<span>%s</span></label></div>'
                    % (' keep-mark on' if is_keep else '', E(path), th,
                       E(os.path.basename(path)), E(path), E(os.path.dirname(path)),
                       fs(path) / 1024, wh,
                       '保留' if is_keep else '移出'))
        items.append(pick(keep, True))
        for r in rs:
            items.append(pick(r['重复文件路径'], False))
        dlabel = (E(list(dirs)[0][:60]) if len(dirs) == 1
                  else E(list(dirs)[0][:48]) + ' 等 %d 处' % len(dirs))
        cards.append(
            '<div class="grp%s" id="g%d" data-keep="%s">'
            '<div class="gh" onclick="var g=this.parentNode;'
            'var o=g.querySelectorAll(\'.pick\').some(function(x){return !x.classList.contains(\'on\')});'
            'picksOf(g).forEach(function(p){p.classList.toggle(\'on\',o)});paint(g);tot();">'
            '<span class="gfold" onclick="event.stopPropagation();'
            'foldGroup(%d);" title="折叠/展开本组">▼</span>'
            '<span class="gcheck" title="整组全选/全不选" '
            'style="width:15px;height:15px;border:1.5px solid #6e7681;border-radius:3px;'
            'display:inline-block;flex-shrink:0;cursor:pointer"></span>'
            '<span class="bd %s">%s</span><span class="gid">组 #%s</span>'
            '<span class="gm">%d 个文件 · 冗余 %.0f KB</span>'
            '<span class="gl" title="%s">%s</span>'
            '<button class="mini" data-act="fold">折叠本组</button>'
            '<button class="mini" data-act="best">智能推荐</button>'
            '<button class="mini" data-act="keep">全留</button>'
            '<button class="mini" data-act="drop">全移</button>'
            '</div>'
            '<div class="grid">%s</div>'
            '<div class="gsel"><span>已选保留：<b class="cur">—</b></span>'
            '<span class="free">将释放 %.0f KB</span></div></div>'
            % (' sus' if is_s else '', gi, E(keep), gi,
               'sus' if is_s else 'ok', '疑似连拍' if is_s else '确认重复',
               gi, len(rs) + 1, free,
               E(' ｜ '.join(sorted(dirs))), dlabel,
               ''.join(items), free))

    tpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates', 'picker.html')
    if not os.path.exists(tpl):          # 兜底：脚本被复制到别处时也能找到
        tpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'picker.html')
    HTML = open(tpl, encoding='utf-8').read()
    out = HTML
    for k, v in {
        '@@GROUPS@@': str(len(groups)),
        '@@FILES@@': str(len({r['重复文件路径'] for r in rows} | {r['保留路径'] for r in rows})),
        '@@CARDS@@': ''.join(cards),
        '@@SZ@@': json.dumps(sz, ensure_ascii=False),
        '@@TOTAL@@': str(summary['total_photos']),
        '@@DIRS@@': str(summary['dir_count']),
        '@@TOTALGB@@': str(summary['total_gb']),
        '@@TARGET@@': E(summary['target']),
        '@@TIME@@': summary['time'],
        '@@CFGB@@': str(summary['confirmed_groups']),
        '@@SUSGB@@': str(summary['suspect_groups']),
    }.items():
        out = out.replace(k, v)
    out_name = 'index.html'
    open(os.path.join(work, out_name), 'w', encoding='utf-8').write(out)


if __name__ == '__main__':
    main()