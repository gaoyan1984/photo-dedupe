# -*- coding: utf-8 -*-
"""
按清单把重复副本移走（不是直接删除）
用法：
    python apply_cleanup.py <处理清单.txt>                 # 预览，不执行
    python apply_cleanup.py <处理清单.txt> --execute        # 移入 Windows 回收站
    python apply_cleanup.py <处理清单.txt> --to <备份目录> --execute
                                                            # 移到备份文件夹（推荐大批量用）

两种模式怎么选：
  · 回收站：小批量（几百个以内）方便，系统"还原"即可找回
  · 备份文件夹：大批量（几千个）更安全。回收站有容量配额，装不下时
    Windows 会自动永久清掉更早的回收项，可能把别的东西一起丢了。
    同盘移动是瞬时的、不额外占空间，确认没问题后手动删备份文件夹即可。

安全设计：
  1. 默认只预览，不动手
  2. 无论哪种模式都可还原，不是不可逆抹除
  3. 执行前自动备份一份清单
  4. 跳过"疑似"组（那是要人判断的，绝不自动动）
  5. 小批次执行，中途出问题损失可控
"""
import sys, os, time, shutil, ctypes
from ctypes import wintypes

args = sys.argv[1:]
TO = None
if '--to' in args:
    i = args.index('--to')
    if i + 1 < len(args):
        TO = args[i + 1]
        args = args[:i] + args[i + 2:]
DO = '--execute' in args

# 新增：--delete 模式（永久直接删除，不进回收站，不可恢复）
DELETE = '--delete' in args
if DELETE:
    args = [a for a in args if a != '--delete']
    TO = None

# 新增：--latest 模式（批处理按 5 时由 find_latest_list.py 把最新清单路径
# 写入同目录的 _latest_list.txt，这里直接读，彻底避开中文路径经 GBK 失真）。
latest = '--latest' in args
if latest:
    args = [a for a in args if a != '--latest']
    _marker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '_latest_list.txt')
    if not os.path.exists(_marker):
        print('没有找到自动清单（_latest_list.txt）。请先运行批处理的 [5] 选项，'
              '或把清单 txt 拖到批处理图标上。')
        sys.exit(1)
    LIST = open(_marker, encoding='utf-8-sig').read().splitlines()[0].strip()
else:
    LIST = args[0] if args else ''

if not LIST or not os.path.exists(LIST):
    print('用法: python apply_cleanup.py <处理清单.txt> [--latest] [--to <备份目录>] [--execute] [--delete]')
    sys.exit(1)

def dest_of(p, root):
    """备份模式下保持原目录结构。
    坑：这批文件本来就是跨文件夹的同名重复，摊平到一个目录会互相覆盖，
    必须按原路径建子目录，否则一半文件会凭空消失。
    root 若不带盘符（如 "_照片去重备份_可手动删除"），则按每个文件"自己所在的盘"
    放置备份，实现 I盘→I盘、H盘→H盘 的同盘移动。"""
    drive, tail = os.path.splitdrive(p)
    root_drive, root_tail = os.path.splitdrive(root)
    if not root_drive:
        base = drive + '\\' + root_tail.lstrip('\\/')
    else:
        base = root
    return os.path.join(base, tail.lstrip('\\/'))

# ---------- 解析清单 ----------
targets, keeps = [], []
for line in open(LIST, encoding='utf-8-sig'):
    line = line.rstrip('\n')
    if line.startswith('[保留]'):
        keeps.append(line[4:].strip())
    elif line.startswith('[移出]'):
        targets.append(line[4:].strip())

print('=' * 56)
print('清单解析: 保留 %d 个, 移出 %d 个' % (len(keeps), len(targets)))
print('=' * 56)

if not targets:
    print('没有要移出的文件，清单可能有误。')
    sys.exit(0)

# ---------- 安全检查 ----------
missing = [t for t in targets if not os.path.exists(t)]
print('\n不存在(跳过): %d' % len(missing))
for m in missing[:5]:
    print('   ', m)

valid = [t for t in targets if os.path.exists(t)]

# 坑：只认「文件」，绝不整目录移动。
# 清单里混进一个目录路径的话，shutil.move 会把整个文件夹搬走——
# 那是"清单写 1 条、实际动了几百个文件"，属于失控。这里一律跳过。
asdir = [t for t in valid if os.path.isdir(t)]
if asdir:
    print('\n★ 清单里有 %d 条指向「目录」而不是文件，已跳过不处理：' % len(asdir))
    for d in asdir[:5]:
        print('   ', d)
valid = [t for t in valid if os.path.isfile(t)]

# 检查是否会删掉别的组的正本
keepset = set(keeps)
conflict = [t for t in valid if t in keepset]
print('冲突: 既是正本又要移出 %d 个' % len(conflict))
if conflict:
    print('  ★ 有冲突，中止执行！')
    sys.exit(1)

total = sum(os.path.getsize(t) for t in valid)
print('\n待移出: %d 个文件, %.2f MB' % (len(valid), total / 1024**2))

if not DO:
    print('\n【预览模式】以上是将会执行的操作，没有任何文件被改动。')
    if DELETE:
        print('确认无误后执行（永久删除，不可恢复）：')
        print('  python apply_cleanup.py "%s" --delete --execute' % LIST)
        print('\n前 10 条预览:')
        for t in valid[:10]:
            print('   ', t)
    elif TO:
        print('确认无误后执行：')
        print('  python apply_cleanup.py "%s" --to "%s" --execute' % (LIST, TO))
        print('\n前 5 条将移动到:')
        for t in valid[:5]:
            print('   %s\n     -> %s' % (t, dest_of(t, TO)))
    else:
        print('确认无误后加 --execute 参数执行（移入回收站）：')
        print('  python apply_cleanup.py "%s" --execute' % LIST)
        print('\n前 10 条预览:')
        for t in valid[:10]:
            print('   ', t)
    sys.exit(0)

to_drive = os.path.splitdrive(TO)[0] if TO else ''
if TO and not to_drive:
    # 无盘符：按各自文件所在盘备份（I盘→I盘，H盘→H盘），不存在跨盘问题，跳过检查
    pass
elif TO and to_drive[0].upper() != os.path.splitdrive(valid[0])[0][0].upper():
    print('\n★ 提示：备份目录在 %s 盘，源文件在 %s 盘。' % (to_drive[0], valid[0][0]))
    print('  跨盘是"复制"，会占用双份空间且很慢。建议备份目录放同一个盘，')
    print('  或改用不带盘符的备份目录名（如 _照片去重备份_可手动删除）实现同盘备份。')
    if '--force' not in args:
        print('  如确要继续，加 --force 参数。')
        sys.exit(1)

# ---------- 备份清单 ----------
bak = os.path.join(os.path.dirname(LIST),
                   '删除备份_%s.txt' % time.strftime('%Y%m%d_%H%M%S'))
with open(bak, 'w', encoding='utf-8') as f:
    f.write('执行时间: %s\n' % time.strftime('%Y-%m-%d %H:%M'))
    f.write('共 %d 个文件\n\n' % len(valid))
    for t in valid:
        f.write(t + '\n')
print('\n备份清单已存: %s' % bak)

# ---------- 回收站 API ----------
class SHFILEOPSTRUCT(ctypes.Structure):
    _fields_ = [('hwnd', wintypes.HWND),
                ('wFunc', wintypes.UINT),
                ('pFrom', wintypes.LPCWSTR),
                ('pTo', wintypes.LPCWSTR),
                ('fFlags', ctypes.c_uint16),
                ('fAnyOperationsAborted', wintypes.BOOL),
                ('hNameMappings', ctypes.c_void_p),
                ('lpszProgressTitle', wintypes.LPCWSTR)]

FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004

def recycle(paths):
    """移入回收站。返回成功数"""
    # 传给 API 必须是双\0 结尾的列表
    buf = '\0'.join(paths) + '\0\0'
    op = SHFILEOPSTRUCT()
    op.wFunc = FO_DELETE
    op.pFrom = buf
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
    ok = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return ok, not op.fAnyOperationsAborted

# ---------- 执行 ----------
MODE = 'DELETE' if DELETE else ('MOVE' if TO else 'RECYCLE')
BATCH = 100 if DELETE else (50 if TO else 10)  # 直接删除 os.remove 最快，批次放大
done, fail, skipped = 0, 0, 0
deleted_files, failed_files = [], []  # 直接删除模式下记录明细
n_batches = (len(valid) + BATCH - 1) // BATCH

if TO and os.path.splitdrive(TO)[0]:
    os.makedirs(TO, exist_ok=True)
    # 目标重名冲突预检：备份里已经有同名文件就先报出来，别覆盖
    clash = [t for t in valid if os.path.exists(dest_of(t, TO))]
    if clash:
        print('\n★ 备份目录里已存在同名文件 %d 个，将跳过不覆盖：' % len(clash))
        for c in clash[:5]:
            print('   ', dest_of(c, TO))
        if '--force' not in args:
            print('  确认可覆盖请加 --force（本脚本不会覆盖，只会跳过）。')

for i in range(0, len(valid), BATCH):
    batch = valid[i:i + BATCH]
    if i % (BATCH * 20) == 0 or i + BATCH >= len(valid):
        print('\n批次 %d/%d: 累计 %d 成功' % (i // BATCH + 1, n_batches, done))
    if MODE == 'DELETE':
        for p in batch:
            try:
                os.remove(p)
                print('   已删除:', p)
                done += 1
                deleted_files.append(p)
            except Exception as e:
                print('   ★ 失败:', p, e)
                fail += 1
                failed_files.append((p, str(e)))
    elif MODE == 'MOVE':
        for p in batch:
            d = dest_of(p, TO)
            if os.path.exists(d):
                skipped += 1
                continue
            try:
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.move(p, d)
                done += 1
            except Exception as e:
                print('   ★ 失败:', p, e)
                fail += 1
    else:
        ok, completed = recycle(batch)
        for p in batch:
            if os.path.exists(p):
                print('   ★ 失败:', p)
                fail += 1
            else:
                done += 1

# 直接删除模式下写明细日志（清楚明细）
if MODE == 'DELETE' and (deleted_files or failed_files):
    log_path = os.path.join(os.path.dirname(LIST),
                            '直接删除记录_%s.txt' % time.strftime('%Y%m%d_%H%M%S'))
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write('直接删除时间: %s\n' % time.strftime('%Y-%m-%d %H:%M'))
        f.write('成功: %d 个，失败: %d 个，总量: %.2f MB\n\n'
                % (done, fail, total / 1024**2))
        f.write('--- 成功删除 ---\n')
        for p in deleted_files:
            f.write(p + '\n')
        if failed_files:
            f.write('\n--- 失败 ---\n')
            for p, e in failed_files:
                f.write('%s\t%s\n' % (p, e))
    print('\n直接删除明细已存: %s' % log_path)

print('\n' + '=' * 56)
if MODE == 'DELETE':
    print('完成: %d 个已永久删除, %d 个失败' % (done, fail))
    print('释放空间约 %.2f MB' % (total / 1024**2))
    print('\n★ 警告：文件已直接删除，不进回收站，不可恢复。')
elif MODE == 'MOVE':
    print('完成: %d 个已移到备份文件夹, %d 个失败, %d 个跳过(备份里已有)'
          % (done, fail, skipped))
    print('\n备份位置: 各源文件所在盘根下的 %s（I盘、H盘各一个）' % TO)
    print('目录结构按原样保留，要还原就整体拖回去。')
    print('★ 注意：同盘移动不会立刻释放空间，')
    print('  确认没问题后手动删掉这些备份文件夹（每个源盘各一个），才真正腾出 %.2f GB。'
          % (total / 1024**3))
else:
    print('完成: %d 个已移入回收站, %d 个失败' % (done, fail))
    print('释放空间约 %.2f MB' % (total / 1024**2))
    print('\n★ 文件在回收站里，如误删可在 Windows 回收站点"还原"找回。')
    print('  注意回收站有容量上限，装不下时系统会清掉更早的回收项。')
print('备份清单: %s' % bak)