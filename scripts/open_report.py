# -*- coding: utf-8 -*-
"""
打开最近一次生成的预览报告（index.html）。
读取本脚本同目录下的 _last_report.txt（由 build_g_report.py 写入，UTF-8）。
用 os.startfile 打开，可正确处理含中文的路径。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(HERE, '_last_report.txt')

if not os.path.exists(p):
    print('没有可用的报告。请先运行一次扫描（照片查重.bat 的选项 1/2/3）。')
    sys.exit(0)

path = open(p, encoding='utf-8').read().strip()
if not path or not os.path.exists(path):
    print('记录的报告路径不存在（可能被移动/删除，或上次扫描没跑完）：')
    print('   ', path or '(空)')
    print('请重新运行一次扫描（照片查重.bat 的选项 1/2/3 或多盘版 6/7），')
    print('或手动打开上次扫描输出目录里的 index.html。')
    sys.exit(0)

try:
    os.startfile(path)
    print('已打开报告：', path)
except Exception as e:
    print('自动打开失败：', e)
    print('请手动打开：', path)
