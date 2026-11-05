# -*- coding: utf-8 -*-
"""
给大报告的 g_folders 数据补一个倒排索引 dupIdx：
    { 文件夹: [该文件夹「持有副本」的簇编号...] }

为什么需要它：
  byFolder 是「这个文件夹参与到的所有重复组」（可能是正本，也可能是副本）。
  152 个文件夹里有 55 个副本数为 0 —— 它们参与了上千组，但拿的一直是正本，
  副本都在别的文件夹。所以「全选本文件夹副本」对这些文件夹点了必然没反应，
  用户会以为按钮坏了。
  有了 dupIdx，页面就能：
    - 按钮上直接显示「（无副本）」并置灰
    - 提供「只看我的副本」视图，勾选后立刻看得到打勾效果

用法：
    python build_dup_index.py <报告目录>
会就地更新该目录下的 g_folders.js 和 g_folders.json（先备份为 .bak）。
"""
import json
import os
import shutil
import sys


def strip_js(s):
    return s[s.index('=') + 1:].rstrip().rstrip(';')


def main():
    if len(sys.argv) < 2:
        print('用法: python build_dup_index.py <报告目录>')
        return 2
    d = sys.argv[1]
    fj = os.path.join(d, 'g_folders.js')
    ij = os.path.join(d, 'g_index.js')
    if not os.path.exists(fj):
        print('找不到 %s' % fj)
        return 2

    with open(fj, encoding='utf-8') as f:
        raw = f.read()
    FDATA = json.loads(strip_js(raw))
    with open(ij, encoding='utf-8') as f:
        IDX = json.loads(strip_js(f.read()))

    chunks = IDX['chunks']
    flat = []
    for i in range(chunks):
        p = os.path.join(d, 'g_p%03d.js' % i)
        with open(p, encoding='utf-8') as f:
            flat.extend(json.loads(strip_js(f.read())))
    if len(flat) != IDX['total']:
        print('!! 簇数量对不上：分片里 %d，索引里 %d' % (len(flat), IDX['total']))
        return 2

    def dir_of(p):
        i = max(p.rfind('\\'), p.rfind('/'))
        return p[:i] if i > 0 else p

    dupIdx = FDATA.get('dupIdx') or {}
    if not dupIdx:
        for g, c in enumerate(flat):
            for p in c['dups']:
                dupIdx.setdefault(dir_of(p), []).append(g)

        # 自检：dupIdx[dir] 里的副本数必须等于 folders 声明的 ndup
        bad = 0
        for dirname, nclus, ndup, mb in FDATA['folders']:
            n = 0
            for g in dupIdx.get(dirname, []):
                n += sum(1 for p in flat[g]['dups'] if dir_of(p) == dirname)
            if n != ndup:
                bad += 1
                if bad <= 5:
                    print('!! 不一致 %s 声明 %d 实算 %d' % (dirname, ndup, n))
        if bad:
            print('!! 共 %d 处不一致，已放弃写入' % bad)
            return 2

    # fstat：每个文件夹的参与情况汇总，给页面顶部的「这个文件夹什么情况」横幅用。
    #   keep = 该文件夹持有正本的组数
    #   dest = 它参与的那些组，副本都落在哪些文件夹里（及数量）
    # 为什么需要：用户点开 G:\xiangpian\2007-8-25 会看到「副本」卡片，
    # 就以为这个文件夹有副本，点「全选本文件夹副本」没反应就以为坏了。
    # 实际上那 11 组的副本全在 2007-8-25夏家胡同 —— 卡片的小字文件夹名他根本没看。
    # 横幅必须直接把「副本都在哪个文件夹」写出来。
    fstat = {}
    for dirname, nclus, ndup, mb in FDATA['folders']:
        gis = FDATA['byFolder'].get(dirname, [])
        keep = 0
        dest = {}
        for g in gis:
            c = flat[g]
            if dir_of(c['keeppath']) == dirname:
                keep += 1
            for p in c['dups']:
                od = dir_of(p)
                if od != dirname:
                    dest[od] = dest.get(od, 0) + 1
        fstat[dirname] = {'keep': keep, 'dest': dest}

    FDATA['dupIdx'] = dupIdx
    FDATA['fstat'] = fstat
    for name in ('g_folders.js', 'g_folders.json'):
        p = os.path.join(d, name)
        if not os.path.exists(p):
            continue
        shutil.copy2(p, p + '.bak')
        body = json.dumps(FDATA, ensure_ascii=False, separators=(', ', ': '))
        if name.endswith('.js'):
            body = 'window.FDATA=' + body + ';'
        with open(p, 'w', encoding='utf-8') as f:
            f.write(body)

    zero = sum(1 for f in FDATA['folders'] if f[2] == 0)
    print('已写入 dupIdx + fstat')
    print('  有副本的文件夹 %d 个，副本数为 0 的 %d 个' % (len(dupIdx), zero))
    print('  自检通过（原文件已备份为 .bak）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
