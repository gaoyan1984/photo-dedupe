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


def ensure_runtime():
    """把 scripts / templates 放到可写目录。"""
    if not _FROZEN:
        return _SRC              # 开发模式：项目目录本身可写，直接用
    base = os.path.dirname(sys.executable)   # exe 所在目录，可写
    rt = os.path.join(base, '_pd_runtime')
    os.makedirs(rt, exist_ok=True)
    for sub in ('scripts', 'templates'):
        src = os.path.join(_SRC, sub)
        dst = os.path.join(rt, sub)
        if os.path.isdir(src):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
    return rt


RUNTIME = ensure_runtime()
SCRIPTS = os.path.join(RUNTIME, 'scripts')
try:
    os.chdir(RUNTIME)            # 工作目录固定到可写区，避免相对路径事故
except Exception:
    pass

CN_FONT = ("Microsoft YaHei", 10)
CN_FONT_B = ("Microsoft YaHei", 10, "bold")

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
def do_scan(folder):
    _log('=' * 60)
    _log('开始扫描：' + folder)
    _log('（只读扫描，不会修改 / 移动 / 删除任何文件）')
    _log('=' * 60)
    run_script('run_dedupe.py', [folder])
    _log('-' * 60)
    _log('生成 A/B/C 预览报告 …')
    run_script('build_g_report.py', [])
    _log('-' * 60)
    _log('打开报告 …')
    run_script('open_report.py', [])
    _log('【完成】扫描与报告已结束。')


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
    root.geometry('760x560')
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

    # 第一行：扫描
    row1 = ttk.LabelFrame(frm, text='① 扫描查重（只读，不删任何文件）', padding=8)
    row1.pack(fill='x', padx=14, pady=4)
    btn(row1, '扫描（选文件夹）',
        lambda: run_in_thread(do_scan, filedialog.askdirectory(title='选择要扫描的文件夹 / 盘符')))
    btn(row1, '快速扫 F 盘', lambda: run_in_thread(do_scan, 'F:\\'))
    btn(row1, '快速扫 E 盘', lambda: run_in_thread(do_scan, 'E:\\'))

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
