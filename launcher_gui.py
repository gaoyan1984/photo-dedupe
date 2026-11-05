# -*- coding: utf-8 -*-
"""
照片查重工具 · 图形界面启动器
=====================================================================
替代原来的「照片查重.bat」命令行菜单，把所有功能做成中文按钮，
双击即可使用，全程不需要看黑窗口、不需要输命令。

功能对应原 bat 菜单：
  [扫描查重]      -> run_dedupe.py  <目录/盘符>   （只读，不动任何文件）
  [生成报告]      -> build_g_report.py            （A/B/C 三套 HTML 预览）
  [打开上次报告]  -> open_report.py               （用浏览器打开）
  [清理·预览]     -> apply_cleanup.py <清单>        （只看不动）
  [清理·移回收站] -> apply_cleanup.py <清单> --execute
  [清理·备份]     -> apply_cleanup.py <清单> --to <目录> --execute
  [清理·永久删]   -> apply_cleanup.py <清单> --delete --execute

打包说明（PyInstaller）：
  工具脚本（scripts/）和模板（templates/）在 _MEIPASS 里是只读的，
  而脚本运行时要往自己目录写 _last_work.txt / _last_report.txt，
  所以本启动器会把它们复制到一个可写目录（exe 旁边 _pd_runtime/）再运行。
"""
import os
import sys
import runpy
import threading
import shutil
import subprocess
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ===================== 资源目录（必须可写） =====================
if getattr(sys, 'frozen', False):
    _SRC = sys._MEIPASS          # 打包后：资源被解压到临时只读区
    _FROZEN = True
else:
    _SRC = os.path.dirname(os.path.abspath(__file__))
    _FROZEN = False


def ensure_runtime(force=False):
    """把 scripts / templates 放到可写目录。
    force=True 时强制覆盖（首次或资源更新）；False 时若目标已存在且非空则
    跳过拷贝，避免 GUI 启动的扫描子进程每次都重复复制一遍。"""
    if not _FROZEN:
        return _SRC              # 开发模式：项目目录本身可写，直接用
    base = os.path.dirname(sys.executable)   # exe 所在目录，可写
    rt = os.path.join(base, '_pd_runtime')
    os.makedirs(rt, exist_ok=True)
    for sub in ('scripts', 'templates'):
        src = os.path.join(_SRC, sub)
        dst = os.path.join(rt, sub)
        if not os.path.isdir(src):
            continue
        if os.path.isdir(dst) and os.listdir(dst) and not force:
            continue             # 已存在，跳过拷贝
        if os.path.isdir(dst):
            try:
                shutil.rmtree(dst)
            except Exception:
                pass             # 被占用等清不掉：下面按文件覆盖补齐
        try:
            shutil.copytree(src, dst, dirs_exist_ok=True)
        except Exception:
            # 个别文件被占用：逐文件复制，忽略失败项，保证其余资源刷新到位
            for root, _dirs, files in os.walk(src):
                rel = os.path.relpath(root, src)
                ddst = os.path.join(dst, rel)
                try:
                    os.makedirs(ddst, exist_ok=True)
                except Exception:
                    pass
                for f in files:
                    s = os.path.join(root, f)
                    d = os.path.join(ddst, f)
                    try:
                        shutil.copy2(s, d)
                    except Exception:
                        pass
    return rt


RUNTIME = ensure_runtime()
SCRIPTS = os.path.join(RUNTIME, 'scripts')
try:
    os.chdir(RUNTIME)            # 工作目录固定到可写区，避免相对路径事故
except Exception:
    pass

CN_FONT = ("Microsoft YaHei", 10)
CN_FONT_B = ("Microsoft YaHei", 10, "bold")

# 多选：GUI 中选中的待扫描路径
SELECTED = []
# 当前扫描子进程（subprocess.Popen），供「停止」按钮硬终止
_CURRENT_PROC = None
# 子进程无控制台标志（窗口化的 exe 本身不会弹黑窗，加了更稳妥）
_CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# ===================== stdout 重定向到文本框 =====================
class TxtWriter:
    def __init__(self, widget):
        self.widget = widget
        self.lines = 0

    def write(self, s):
        if s:
            self.widget.after(0, self._append, s)

    def _append(self, s):
        try:
            self.widget.insert('end', s)
            self.widget.see('end')
            self.lines += s.count('\n') + 1
            # 控制长度，避免扫几万行把内存撑爆
            if self.lines > 4000:
                self.widget.delete('1.0', '1000.0')
                self.lines -= 1000
        except Exception:
            pass

    def flush(self):
        pass


_OUT = None


def bind_out(widget):
    global _OUT
    _OUT = widget
    sys.stdout = TxtWriter(widget)
    sys.stderr = TxtWriter(widget)


def _log(msg):
    if _OUT is not None:
        _OUT.after(0, lambda: (_OUT.insert('end', msg + '\n'), _OUT.see('end')))


# ===================== 运行脚本 =====================
def run_script(name, args):
    script = os.path.join(SCRIPTS, name)
    if not os.path.exists(script):
        _log('【错误】找不到脚本：' + script)
        return
    old = sys.argv
    sys.argv = [name] + list(args)
    try:
        runpy.run_path(script, run_name='__main__')
    except SystemExit:
        pass
    except Exception:
        traceback.print_exc()
    finally:
        sys.argv = old


def run_in_thread(fn, *a):
    threading.Thread(target=fn, args=a, daemon=True).start()


# ===================== 具体功能 =====================
def list_drives():
    """列出本机可用磁盘（Windows），返回 [(盘符, 总GB, 可用GB), ...]。"""
    import string
    import shutil
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


def scan_via_subprocess(paths):
    """用「子进程」跑扫描，这样「停止」按钮能真正终止它。
    扫描成功（返回码 0）后，再在本进程内生成并打开报告；被停止/异常则不生成。"""
    global _CURRENT_PROC
    # 若已有任务在跑，先把它终止掉再开新的
    old = _CURRENT_PROC
    if old is not None and old.poll() is None:
        try:
            old.terminate()
        except Exception:
            pass
        try:
            old.wait(timeout=3)
        except Exception:
            pass

    quoted = ';'.join(paths)
    _log('=' * 60)
    _log('开始扫描（多选）共 %d 个路径：' % len(paths))
    for p in paths:
        _log('   · ' + p)
    _log('（只读扫描，不会修改 / 移动 / 删除任何文件）')
    _log('=' * 60)

    # 冻结（EXE）时 sys.executable 本身就是入口；开发模式需显式带上本脚本路径
    entry = [sys.executable] if _FROZEN else [sys.executable, os.path.abspath(__file__)]
    cmd = entry + ['--child', 'run_dedupe.py', '--paths', quoted]
    try:
        _CURRENT_PROC = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
            creationflags=_CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except Exception as e:
        _log('【错误】启动扫描子进程失败：' + str(e))
        return

    def reader():
        global _CURRENT_PROC
        # 记录本 reader 归属的进程，避免新扫描启动时把它误当成新进程而清空
        proc = _CURRENT_PROC
        try:
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                sys.stdout.write(line)
        except Exception:
            pass
        rc = proc.wait()
        if rc == 0:
            _log('-' * 60)
            _log('扫描完成，正在生成 A/B/C 报告 …')
            run_script('build_g_report.py', [])
            run_script('open_report.py', [])
            _log('【完成】扫描与报告已全部结束。')
        else:
            _log('-' * 60)
            _log('【已停止 / 异常结束】（返回码 %s），本次未生成报告。' % rc)
        if _CURRENT_PROC is proc:
            _CURRENT_PROC = None

    threading.Thread(target=reader, daemon=True).start()


def stop_current():
    """硬终止正在运行的扫描子进程（终止后不会生成报告）。"""
    global _CURRENT_PROC
    if _CURRENT_PROC is not None and _CURRENT_PROC.poll() is None:
        _log('⛔ 收到停止指令，正在终止扫描进程 …')
        try:
            _CURRENT_PROC.terminate()
        except Exception:
            try:
                _CURRENT_PROC.kill()
            except Exception:
                pass
    else:
        _log('当前没有正在运行的扫描任务。')


def do_open_last():
    _log('打开上一次生成的报告 …')
    run_script('open_report.py', [])


def _pick_list():
    return filedialog.askopenfilename(
        title='选择清理清单 txt',
        filetypes=[('清理清单', '*.txt'), ('所有文件', '*.*')])


def do_clean_preview():
    p = _pick_list()
    if not p:
        return
    _log('=' * 60)
    _log('预览清理清单（只看不动，不改动任何文件）：')
    _log('清单：' + p)
    _log('=' * 60)
    run_script('apply_cleanup.py', [p])


def do_clean_execute(mode):
    p = _pick_list()
    if not p:
        return
    if mode == 'recycle':
        args = [p, '--execute']
        tip = '把清单里的重复副本移入 Windows 回收站（可从回收站还原）'
    elif mode == 'delete':
        args = [p, '--delete', '--execute']
        tip = '永久删除清单里的重复副本（不可恢复！）'
    elif mode == 'backup':
        to = filedialog.askdirectory(title='选择备份文件夹（重复副本会移到这里）')
        if not to:
            _log('未选择备份文件夹，已取消。')
            return
        args = [p, '--to', to, '--execute']
        tip = '把清单里的重复副本移动到备份文件夹：\n' + to + '\n（同盘移动，不额外占空间）'
    else:
        return
    if not messagebox.askyesno('请确认操作', '即将执行：\n' + tip + '\n\n确定执行吗？'):
        _log('已取消。')
        return
    _log('=' * 60)
    _log('执行：' + tip)
    run_script('apply_cleanup.py', args)
    _log('【完成】清理执行结束。')


def do_latest_find():
    _log('自动查找最新的清理清单 …')
    run_script('find_latest_list.py', [])


# ===================== 界面 =====================
def build_gui(root):
    root.title('照片查重工具  （只读扫描 · 一键报告 · 安全清理）')
    root.geometry('820x690')
    try:
        root.iconbitmap()
    except Exception:
        pass

    # 顶部说明
    tk.Label(root, text='照片查重工具', font=("Microsoft YaHei", 16, "bold"),
             fg='#1f6feb').pack(pady=(10, 2))
    tk.Label(root, text='双击即用，无需命令行。先扫描、看报告，确认后再清理。',
             font=CN_FONT, fg='#555').pack(pady=(0, 8))

    # 按钮区
    frm = ttk.Frame(root)
    frm.pack(fill='x', padx=14, pady=4)

    style = ttk.Style()
    try:
        style.configure('TButton', font=CN_FONT)
    except Exception:
        pass

    def btn(parent, text, cmd, w=18):
        b = ttk.Button(parent, text=text, command=cmd, width=w)
        b.pack(side='left', padx=5, pady=4)
        return b

    # 第一行：扫描（多选文件夹 / 磁盘）
    row1 = ttk.LabelFrame(frm, text='① 扫描查重（只读，不删任何文件 · 可多选文件夹/磁盘）', padding=8)
    row1.pack(fill='x', padx=14, pady=4)

    # —— 已选路径列表 ——
    sel_frame = ttk.Frame(row1)
    sel_frame.pack(fill='x', pady=(0, 6))
    listbox = tk.Listbox(sel_frame, height=4, font=("Microsoft YaHei", 9),
                         selectmode='extended', bg='#0f1419', fg='#d6e0ea')
    lb_sb = ttk.Scrollbar(sel_frame, command=listbox.yview)
    listbox.configure(yscrollcommand=lb_sb.set)
    listbox.pack(side='left', fill='both', expand=True, padx=(0, 6))
    lb_sb.pack(side='right', fill='y')

    def refresh_listbox():
        listbox.delete(0, 'end')
        for p in SELECTED:
            listbox.insert('end', p)

    def add_folder():
        p = filedialog.askdirectory(title='选择要扫描的文件夹')
        if not p:
            return
        if p not in SELECTED:
            SELECTED.append(p)
            refresh_listbox()
        else:
            _log('已在列表里：' + p)

    def remove_selected():
        for i in reversed(list(listbox.curselection())):
            del SELECTED[i]
        refresh_listbox()

    def clear_sel():
        SELECTED.clear()
        refresh_listbox()

    def pick_drives():
        drives = list_drives()
        if not drives:
            messagebox.showinfo('提示', '未检测到可用磁盘。')
            return
        top = tk.Toplevel(root)
        top.title('选择要扫描的磁盘（可多选）')
        top.geometry('420x%d' % (64 + len(drives) * 28 + 56))
        top.transient(root)
        vars = {}
        tk.Label(top, text='勾选要扫描的磁盘（可多选）：',
                 font=CN_FONT_B).pack(pady=(10, 4))
        for d, tot, free in drives:
            v = tk.BooleanVar()
            vars[d] = v
            tk.Checkbutton(top,
                           text='%s   总 %.1f GB · 可用 %.1f GB' % (d, tot, free),
                           variable=v, font=CN_FONT, anchor='w'
                           ).pack(fill='x', padx=18, pady=2)
        bf = ttk.Frame(top)
        bf.pack(pady=12)

        def ok():
            for d, v in vars.items():
                if v.get() and d not in SELECTED:
                    SELECTED.append(d)
            refresh_listbox()
            top.destroy()

        ttk.Button(bf, text='确定', command=ok, width=12).pack(side='left', padx=10)
        ttk.Button(bf, text='取消', command=top.destroy, width=12).pack(side='left', padx=10)
        top.grab_set()
        top.wait_window(top)

    # —— 选择按钮行 ——
    sel_btn = ttk.Frame(row1)
    sel_btn.pack(fill='x', pady=(0, 6))
    btn(sel_btn, '添加文件夹', add_folder, w=14)
    btn(sel_btn, '添加磁盘', pick_drives, w=14)
    btn(sel_btn, '移除选中', remove_selected, w=14)
    btn(sel_btn, '清空列表', clear_sel, w=14)

    # —— 扫描控制按钮行 ——
    scan_btn = ttk.Frame(row1)
    scan_btn.pack(fill='x')

    def start_scan():
        if not SELECTED:
            messagebox.showinfo('提示', '请先「添加文件夹」或「添加磁盘」，至少选一个路径。')
            return
        run_in_thread(scan_via_subprocess, list(SELECTED))

    btn(scan_btn, '开始扫描', start_scan, w=14)
    btn(scan_btn, '停止扫描', stop_current, w=14)

    # 第二行：报告
    row2 = ttk.LabelFrame(frm, text='② 报告', padding=8)
    row2.pack(fill='x', padx=14, pady=4)
    btn(row2, '生成报告', lambda: run_in_thread(lambda: run_script('build_g_report.py', [])))
    btn(row2, '打开上次报告', lambda: run_in_thread(do_open_last))

    # 第三行：清理
    row3 = ttk.LabelFrame(frm, text='③ 清理重复副本（先看预览，确认后再执行）', padding=8)
    row3.pack(fill='x', padx=14, pady=4)
    btn(row3, '预览清单', do_clean_preview)
    btn(row3, '移入回收站', lambda: run_in_thread(do_clean_execute, 'recycle'))
    btn(row3, '备份到文件夹', lambda: run_in_thread(do_clean_execute, 'backup'))
    btn(row3, '永久删除(危险)', lambda: run_in_thread(do_clean_execute, 'delete'))

    # 第四行：工具
    row4 = ttk.LabelFrame(frm, text='④ 实用工具', padding=8)
    row4.pack(fill='x', padx=14, pady=4)
    btn(row4, '找最新清理清单', lambda: run_in_thread(do_latest_find))

    # 输出区
    tk.Label(root, text='运行日志：', font=CN_FONT_B, anchor='w').pack(
        padx=16, pady=(8, 0), fill='x')
    txt = tk.Text(root, font=("Microsoft YaHei", 9), wrap='word',
                  bg='#0f1419', fg='#d6e0ea')
    sb = ttk.Scrollbar(root, command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    txt.pack(side='left', fill='both', expand=True, padx=(16, 0), pady=(2, 10))
    sb.pack(side='right', fill='y', padx=(0, 16), pady=(2, 10))
    bind_out(txt)

    # 状态栏
    status = tk.Label(root, text='就绪。点击上方按钮开始。', font=CN_FONT,
                      anchor='w', relief='sunken')
    status.pack(side='bottom', fill='x')

    _log('提示：扫描大容量硬盘（几万张照片）可能需要几分钟，请耐心等待，日志会实时滚动。')


def main():
    # 无 GUI 自测模式（仅供打包后验证资源目录，不创建窗口）
    if '--headless' in sys.argv or os.environ.get('PD_HEADLESS'):
        print('HEADLESS 模式：验证资源目录')
        print('RUNTIME =', RUNTIME)
        print('SCRIPTS =', SCRIPTS)
        import glob
        n = len(glob.glob(os.path.join(SCRIPTS, '*.py')))
        print('scripts 下 .py 文件数 =', n)
        print('templates 存在 =', os.path.isdir(os.path.join(RUNTIME, 'templates')))
        return

    # 子进程模式：GUI 以独立子进程方式调用本 exe 跑某个脚本（用于可终止的扫描）。
    # 直接用 runpy 运行，异常 / sys.exit 会向上抛出，从而决定进程退出码：
    #   0 = 扫描成功；非 0 = 出错，或被终止（terminate 让其非 0 退出）。
    if '--child' in sys.argv:
        idx = sys.argv.index('--child')
        rest = sys.argv[idx + 1:]
        if rest:
            name = rest[0]
            args = rest[1:]
            script = os.path.join(SCRIPTS, name)
            if not os.path.exists(script):
                print('【错误】找不到脚本：' + script)
                sys.exit(2)
            sys.argv = [name] + list(args)
            runpy.run_path(script, run_name='__main__')
        return

    # 每次启动强制刷新可写区的脚本/模板，保证更新 exe 后用到的是最新资源
    # （扫描子进程仍走 force=False 跳过，避免每次扫描都重复拷贝）
    ensure_runtime(force=True)

    root = tk.Tk()
    try:
        # 让对话框也用中文界面
        root.tk.call('tk', 'useinputmethods', '1')
    except Exception:
        pass
    build_gui(root)
    root.mainloop()


if __name__ == '__main__':
    main()
