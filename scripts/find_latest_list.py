# -*- coding: utf-8 -*-
"""
找出「最新的那份重复照片处理清单」，并数出里面有几条待移出。

为什么需要它：
  网页导出的清单固定叫 A类重复照片处理清单.txt，浏览器重复下载会自动改名成
  「A类重复照片处理清单 (1).txt」「(2).txt」。批处理原来只按这一串固定名字去找，
  结果**永远命中第一次下载的那份旧清单**——用户刚导出的新清单反而用不上。
  实测就出现过：05:32 的旧清单 5212 条，20:47 的新清单 13522 条，
  按 5 却自动选中旧的那份，条数差了一倍多。

  所以改成：扫目录里所有 *处理清单*.txt，按修改时间排序列出（带序号），
  多份时允许按序号选择（回车=最新那份），并把条数一起告诉批处理，让用户在按下执行前能核对。

输出：
  stdout  <绝对路径>|<待移出条数>      （批处理用 for /f 取这两个字段）
  stderr  候选清单一览（时间 + 条数 + 选中了哪个），直接显示在控制台
找不到就什么都不输出，批处理会退回手工输入路径。
"""
import glob
import os
import sys
import time

PATS = ('*处理清单*.txt', '*重复照片*清单*.txt', '*重复照片处理清单*.txt')


def scan_dirs():
    home = os.path.expanduser('~')
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs = [
        r'E:\WorkBuddy\整理产出',
        os.path.join(home, 'Downloads'),
        os.path.join(home, 'Desktop'),
        os.path.join(home, 'Documents'),
        os.getcwd(),
        here,
    ]
    seen, out = set(), []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for p in PATS:
            for f in glob.glob(os.path.join(d, p)):
                rp = os.path.normpath(f)
                if rp not in seen:
                    seen.add(rp)
                    out.append(rp)
    return out


def count_move(path):
    """只数行首是 [移出] 的行——其他行（标题/分隔/合计/说明）一概不算。"""
    n = 0
    try:
        with open(path, encoding='utf-8-sig', errors='replace') as fh:
            for line in fh:
                if line.rstrip('\r\n').startswith('[移出]'):
                    n += 1
    except Exception:
        return -1
    return n


def main():
    cands = scan_dirs()
    if not cands:
        return 1
    rows = []
    for p in cands:
        n = count_move(p)
        if n <= 0:
            continue          # 空清单/不是清单的 txt，直接跳过
        rows.append((os.path.getmtime(p), os.path.getsize(p), p, n))
    if not rows:
        return 1
    # 最新优先；同一秒导出时取体积大的那份（条目更多的可能性大）
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)

    # 候选清单打到 stderr，给用户看（控制台是 GBK，个别字可能显示成 ?，不影响）
    def say(s):
        sys.stderr.write(s + '\n')
    say('')
    say('  候选清单（按修改时间排序）：')
    for i, (mt2, sz2, p2, n2) in enumerate(rows, 1):
        say('    %d) %s  %6d 条  %s'
            % (i, time.strftime('%m-%d %H:%M', time.localtime(mt2)), n2, p2))

    # 多份清单时允许按序号选择（用户反馈：以前只能默认最新那份，没法选）。
    # 回车 = 第 1 份最新；非交互环境（stdin 被重定向）不提问，直接用最新，避免卡死。
    idx = 0
    if len(rows) > 1:
        try:
            interactive = sys.stdin is not None and sys.stdin.isatty()
        except Exception:
            interactive = False
        if interactive:
            try:
                ans = input('  输入序号选择要用的清单（直接回车=第 1 份最新）：').strip()
            except Exception:
                ans = ''
            if ans:
                if ans.isdigit() and 1 <= int(ans) <= len(rows):
                    idx = int(ans) - 1
                else:
                    say('  输入无效，使用第 1 份（最新）。')
    mt, sz, path, n = rows[idx]
    say('  使用清单 %d/%d（%d 条）：%s' % (idx + 1, len(rows), n, path))
    say('')

    # 把选中结果写成 UTF-8 文件，供批处理和 apply_cleanup 读取。
    # 关键：中文路径若经 stdout(gbk) 传给批处理会变成"?"，python 就打不开文件，
    # 所以走文件、不走 stdout。批处理只判断"文件存不存在"，绝不解析路径字符串。
    marker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         '_latest_list.txt')
    try:
        with open(marker, 'w', encoding='utf-8') as fh:
            fh.write(path + '\n')
            fh.write(str(n) + '\n')
    except Exception:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
