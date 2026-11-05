# -*- coding: utf-8 -*-
"""
清理清单「起飞前安全检查」：会不会删错、会不会一组一张都不剩。

回答的就是用户最担心的那件事：
  「会不会交叉删除，正本也被删除，结果一个照片一张都没有留下」

核心检查（每条都给结论）：
  1. 每个重复组：删掉清单里的之后，**还剩几张**？剩 0 张 = 这张照片彻底没了
  2. 有没有把「正本」（每组默认保留的那张）也列进清单
  3. 清单里的路径是否都真实存在 / 有没有混进目录 / 有没有重复行
  4. 清单里有没有不属于任何重复组的路径（无法核验来源，单独列出）
  5. 删除后每组剩余数量分布 + 可释放空间

用法：
    python verify_cleanup_list.py <清单.txt> <报告目录>
退出码 0 = 可以放心执行；1 = 发现问题，先别执行。
"""
import os
import sys
from collections import Counter


def dir_of(p):
    i = max(p.rfind('\\'), p.rfind('/'))
    return p[:i] if i > 0 else p


def norm_dir(p):
    """坑：从 Git Bash / MSYS 传进来的路径，反斜杠会被自动改成正斜杠
       （实测 'G:\\xiangpian\\高岩照片' 进来变成 'G:/xiangpian/高岩照片'），
       不归一化就永远匹配不上，模拟结果会假得离谱还看不出来。"""
    return os.path.normpath(p.strip().strip('"').replace('/', '\\'))


def dn(dd, n=52):
    """长路径截尾巴，保留盘符和末尾文件夹名"""
    if len(dd) <= n:
        return dd
    return dd[:6] + '…' + dd[-(n - 8):]


def strip_js(s):
    return s[s.index('=') + 1:].rstrip().rstrip(';')


def load_list(path):
    """只认行首是 [移出] 的行——和 apply_cleanup.py 保持完全一致，
       否则会把标题/说明行也当成要删的文件。"""
    rows, dup_lines, unknown = [], 0, []
    seen = set()
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        for ln, line in enumerate(f, 1):
            s = line.rstrip('\r\n')
            if not s.startswith('[移出]'):
                continue
            p = s[4:].strip()
            if p in seen:
                dup_lines += 1
                continue
            seen.add(p)
            rows.append(p)
    return rows, dup_lines


def main():
    if len(sys.argv) < 3:
        print('用法: python verify_cleanup_list.py <清单.txt> <报告目录>')
        return 2
    listp, d = sys.argv[1], sys.argv[2]
    if not os.path.exists(listp):
        print('找不到清单:', listp)
        return 2

    targets, dup_lines = load_list(listp)
    print('清单: %s' % listp)
    print('待移出条目: %d 条（重复行 %d 条已合并）' % (len(targets), dup_lines))
    print()

    # ---------- 载入重复组 ----------
    idx_p = os.path.join(d, 'g_index.js')
    if not os.path.exists(idx_p):
        print('报告目录里没有 g_index.js，无法逐组核验；只做文件级检查')
        clusters = None
    else:
        IDX = __import__('json').loads(strip_js(open(idx_p, encoding='utf-8').read()))
        flat = []
        for i in range(IDX['chunks']):
            fp = os.path.join(d, 'g_p%03d.js' % i)
            if os.path.exists(fp):
                flat.extend(__import__('json').loads(strip_js(open(fp, encoding='utf-8').read())))
        clusters = flat
        print('已载入重复组 %d 组（分片 %d 个）' % (len(clusters), IDX['chunks']))
        print()

    tset = set(targets)

    # ---------- 1. 文件级检查 ----------
    print('=' * 66)
    print('【1】文件级检查')
    print('=' * 66)
    missing = [p for p in targets if not os.path.exists(p)]
    asdir = [p for p in targets if os.path.isdir(p)]
    rel = [p for p in targets if not os.path.isabs(p)]
    wild = [p for p in targets if any(c in p for c in '*?')]
    print('  路径不存在        : %d' % len(missing))
    print('  指向目录（危险）  : %d' % len(asdir))
    print('  相对路径          : %d' % len(rel))
    print('  含通配符          : %d' % len(wild))
    for p in missing[:5]:
        print('      不存在: %s' % p)
    for p in asdir[:5]:
        print('      是目录: %s' % p)

    if clusters is None:
        print('\n无重复组数据，到此结束')
        return 0

    # ---------- 2. 逐组核验：会不会删光 ----------
    print()
    print('=' * 66)
    print('【2】逐组核验 —— 会不会一组一张都不剩')
    print('=' * 66)
    total_files = 0
    total_del = 0
    wipe = []          # 整组被删光
    keep_hit = []      # 正本也在清单里
    remain_dist = Counter()
    del_dist = Counter()
    notfound = []      # 清单里的路径不属于任何组
    matched = set()

    owner = {}
    for g, c in enumerate(clusters):
        members = [c['keeppath']] + list(c['dups'])
        for m in members:
            owner.setdefault(m, []).append(g)

    for g, c in enumerate(clusters):
        members = [c['keeppath']] + list(c['dups'])
        total_files += len(members)
        dels = [m for m in members if m in tset]
        for m in dels:
            matched.add(m)
        total_del += len(dels)
        left = len(members) - len(dels)
        remain_dist[left] += 1
        del_dist[len(dels)] += 1
        if left <= 0:
            wipe.append((g, members))
        elif c['keeppath'] in tset:
            keep_hit.append((g, c['keeppath'], left))

    for p in targets:
        if p not in owner:
            notfound.append(p)

    print('  重复组总数        : %d' % len(clusters))
    print('  涉及文件总数      : %d' % total_files)
    print('  清单命中并删除    : %d' % total_del)
    print('  删除后还剩        : %d' % (total_files - total_del))
    print()
    print('  ★ 整组被删光（一张不剩）: %d 组' % len(wipe))
    for g, m in wipe[:10]:
        print('      组 %d: %s' % (g, ' / '.join(m[:3])))
    print('  ★ 正本也被删掉（但组内还有别的留下）: %d 组' % len(keep_hit))
    for g, kp, left in keep_hit[:10]:
        print('      组 %d 正本 %s（组内还剩 %d 张）' % (g, kp, left))
    print()
    print('  删除后每组剩余张数分布:')
    for k in sorted(remain_dist):
        print('      剩 %d 张 : %d 组' % (k, remain_dist[k]))
    print('  清单里不属于任何重复组的路径: %d 条' % len(notfound))
    for p in notfound[:10]:
        print('      %s' % p)

    # ---------- 3. 空间 ----------
    print()
    print('=' * 66)
    print('【3】空间')
    print('=' * 66)
    mb = 0.0
    for g, c in enumerate(clusters):
        dels = [m for m in ([c['keeppath']] + list(c['dups'])) if m in tset]
        if dels:
            mb += c['mb'] * len(dels) / max(1, len(c['dups']))
    print('  预计释放 %.2f GB（%d 个文件）' % (mb / 1024.0, total_del))

    # ---------- 4. 删完之后，照片留在哪个文件夹 ----------
    print()
    print('=' * 66)
    print('【4】删完之后，照片留在哪个文件夹')
    print('=' * 66)
    print('  注意：每组只留 1 张，留的是「去重算法默认认定的正本」，')
    print('        不一定是你最想保留的那个文件夹。')
    print()
    import collections as C2
    involved = C2.Counter()
    deleted = C2.Counter()
    kept = C2.Counter()
    for g, c in enumerate(clusters):
        members = [c['keeppath']] + list(c['dups'])
        for m in members:
            involved[dir_of(m)] += 1
        for m in members:
            if m in tset:
                deleted[dir_of(m)] += 1
            else:
                kept[dir_of(m)] += 1
    print('  %-52s %8s %8s %8s' % ('文件夹', '涉及', '被删', '留下'))
    rows = sorted(involved.items(), key=lambda kv: -kv[1])[:15]
    for dd, n in rows:
        print('  %-52s %8d %8d %8d' % (dn(dd), n, deleted.get(dd, 0), kept.get(dd, 0)))
    gone = [dd for dd in involved if deleted.get(dd, 0) and kept.get(dd, 0) == 0]
    print()
    print('  会被清空的文件夹（里面涉及到的照片一张不留）: %d 个' % len(gone))
    for dd in gone[:8]:
        print('      %s （原 %d 张全部移走）' % (dn(dd), involved[dd]))

    # ---------- 5. 如果指定正本文件夹，会变成什么样 ----------
    masters = []
    if '--master' in sys.argv:
        i = sys.argv.index('--master')
        masters = [norm_dir(x) for x in sys.argv[i + 1:] if not x.startswith('-')]
    if masters and clusters:
        print()
        print('=' * 66)
        print('【5】假设把下面这些设为「正本文件夹」，情况会变成')
        print('=' * 66)
        for m in masters:
            n = sum(1 for c in clusters
                    for x in [c['keeppath']] + list(c['dups']) if dir_of(x) == m)
            print('    正本文件夹: %s   （涉及 %d 张）' % (m, n))
            if n == 0:
                print('    ★★ 这个文件夹在重复数据里 0 命中，请检查路径是否写对')
        print()
        mset = set(masters)
        new_del, new_keep = set(), Counter()
        for g, c in enumerate(clusters):
            members = [c['keeppath']] + list(c['dups'])
            mine = [m for m in members if dir_of(m) in mset]
            if mine:
                for m in members:
                    if dir_of(m) in mset:
                        new_keep[dir_of(m)] += 1
                    else:
                        new_del.add(m)
            else:
                new_keep[dir_of(c['keeppath'])] += 1
                for m in c['dups']:
                    new_del.add(m)
        mb2 = 0.0
        for g, c in enumerate(clusters):
            members = [c['keeppath']] + list(c['dups'])
            k = sum(1 for m in members if m in new_del)
            if k:
                mb2 += c['mb'] * k / max(1, len(c['dups']))
        print('  待删除: %d 个（比现在 %s %d 个）  预计释放 %.2f GB'
              % (len(new_del),
                 '多' if len(new_del) > len(tset) else '少',
                 abs(len(new_del) - len(tset)), mb2 / 1024.0))
        print()
        print('  %-52s %10s %10s' % ('文件夹', '现在留下', '这样留下'))
        for dd in sorted(set(list(kept) + list(new_keep)),
                         key=lambda x: -involved.get(x, 0))[:12]:
            print('  %-52s %10d %10d'
                  % (dn(dd), kept.get(dd, 0), new_keep.get(dd, 0)))
        print()
        print('  提示：想按这个方案清理，就在报告页上把这些文件夹设为正本文件夹后')
        print('        重新导出清单（别直接改这份 txt）。')

    # ---------- 结论 ----------
    print()
    print('=' * 66)
    bad = len(wipe) or len(asdir) or len(rel) or len(wild) or len(notfound)
    if len(wipe):
        print('结论: 【不能执行】有 %d 组会被删到一张不剩，照片会永久丢失。' % len(wipe))
        return 1
    if len(asdir) or len(rel) or len(wild) or len(notfound):
        print('结论: 【先别执行】清单里有无法核验的条目（目录/相对路径/通配符/来源不明），'
              '上面已列出。')
        return 1
    if missing:
        print('结论: 【可以执行，注意】%d 条路径已不存在，执行时会自动跳过；'
              '不会有一组被删光。' % len(missing))
        return 0
    print('结论: 【可以放心执行】')
    print('   - 每一组都至少保留 1 张，不存在整组删光的情况')
    print('   - 每组的正本都不在删除清单里' if not keep_hit
          else '   - 有 %d 组的正本在清单里，但同组仍有副本保留' % len(keep_hit))
    print('   - 清单里没有目录、相对路径、通配符、来源不明的条目')
    return 0


if __name__ == '__main__':
    sys.exit(main())
