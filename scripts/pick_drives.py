# -*- coding: utf-8 -*-
r"""
多盘选择助手（每个盘可单独指定路径）
用法：python pick_drives.py 2|3
      例如 pick_drives.py 2 或 pick_drives.py 3
交互式列出可用磁盘 → 选 2/3 个盘 → 为每个盘指定要扫描的文件夹
（直接回车=整个盘）→ 写入 _multi_paths.txt（UTF-8，分号分隔）。

历史坑（2026-10-25）：原来只写盘符（G:\;H:\），而 run_dedupe.py 的
参数解析又把 --paths 的值重复追加了一遍，导致「路径不存在: G:\;H:\」
多盘扫描从来没能真正跑起来。两处都已修（见 run_dedupe.py 注释）。
"""
import os
import sys
import string
import shutil


def list_drives():
    """列出可用磁盘（Windows）。"""
    res = []
    for c in string.ascii_uppercase:
        d = '%s:\\' % c
        if not os.path.exists(d):
            continue
        try:
            u = shutil.disk_usage(d)
            res.append((d, u.total / 1024 ** 3, u.free / 1024 ** 3))
        except Exception:
            res.append((d, 0.0, 0.0))
    return res


def ask_path(drive):
    """为某个盘询问要扫描的路径；直接回车=整个盘。

    坑：用户可能输入带引号/尾巴带空格/只输盘符/输相对路径，
    统一 normalize；路径不存在就重新问，避免又出现
    「路径不存在」让整个扫描白跑一趟。
    """
    while True:
        try:
            raw = input('  %s 要扫描哪个文件夹？[直接回车=整个 %s]: '
                        % (drive, drive)).strip()
        except EOFError:
            return drive
        if not raw:
            return drive
        p = raw.strip().strip('"').strip()
        if len(p) == 2 and p[1] == ':':      # 只输了盘符 "G:"
            p = p + '\\'
        if not os.path.isabs(p):             # 相对路径按该盘根解析
            p = os.path.join(drive, p)
        p = os.path.normpath(p)
        if os.path.isdir(p):
            return p
        print('    ✗ 路径不存在：%s' % p)
        print('      请重新输入（或直接回车用整个 %s）' % drive)


def main():
    if len(sys.argv) < 2:
        print('用法: python pick_drives.py 2|3')
        sys.exit(1)
    try:
        count = int(sys.argv[1])
    except ValueError:
        print('参数必须是数字 2 或 3')
        sys.exit(1)
    if count not in (2, 3):
        print('目前只支持选择 2 个或 3 个盘')
        sys.exit(1)

    drives = list_drives()
    if len(drives) < count:
        print('可用磁盘只有 %d 个，不够选 %d 个' % (len(drives), count))
        sys.exit(1)

    print('=' * 60)
    print('  照片查重 · 选择 %d 个要一起扫描的磁盘' % count)
    print('=' * 60)
    for i, (d, tot, free) in enumerate(drives, 1):
        print('  [%d] %-4s 总 %6.1f GB  可用 %6.1f GB' % (i, d, tot, free))
    print('=' * 60)
    print('  请输入 %d 个序号，空格分隔，例如：1 3' % count)

    while True:
        raw = input('请选择: ').strip()
        if not raw:
            print('未选择，已取消。')
            sys.exit(1)
        tokens = raw.split()
        bad = [t for t in tokens if not t.isdigit()]
        if bad:
            print('  无效输入 "%s"，请重新输入数字序号。' % ' '.join(bad))
            continue
        idxs = [int(t) for t in tokens]
        if len(idxs) != count:
            print('  必须且只能选 %d 个盘，你选了 %d 个。' % (count, len(idxs)))
            continue
        if any(i < 1 or i > len(drives) for i in idxs):
            print('  序号超出范围，请输入 1-%d 之间的数字。' % len(drives))
            continue
        break

    chosen = [drives[i - 1][0] for i in idxs]
    print('=' * 60)
    print('  已选择: %s' % '  '.join(chosen))
    print('  接下来为每个盘指定要扫描的文件夹（只查某子目录时有用）:')
    paths = [ask_path(d) for d in chosen]

    joined = ';'.join(paths)
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_multi_paths.txt')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(joined)
    print('  将一起扫描: %s' % '  '.join(paths))


if __name__ == '__main__':
    main()
