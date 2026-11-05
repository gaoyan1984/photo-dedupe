@echo off
title 照片查重 · 只读分析工具
cd /d "%~dp0"

set "PY=%~dp0python\python.exe"
if not exist "%PY%" set "PY=C:\Users\gaoyan\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem 坑：Python 默认按 stdout 编码输出（Windows 常为 UTF-8），
rem 而 cmd 控制台是 GBK(936)，中文结果会变成乱码甚至整段不显示，
rem 用户看到的就是「窗口一闪就没了」。这里强制 Python 用 GBK 输出。
set "PYTHONIOENCODING=gbk:replace"
set "PYTHONUTF8=0"

if "%~1"=="" goto menu

rem 坑：把「处理清单.txt」拖到本文件图标上时，%~1 原本会被当成扫描路径
rem 传给 run_dedupe.py，于是脚本去扫一个 txt 文件，扫出 0 张照片，
rem 用户看到的是「跑完了但什么都没做」，根本不知道是用法错了。
rem 所以：拖进来的是 .txt 就走清理流程，不是 .txt 才当扫描路径。
if /i "%~x1"==".txt" goto drop_list
"%PY%" -u "%~dp0scripts\run_dedupe.py" %*
goto end

:drop_list
set "LIST=%~1"
echo.
echo   拖入的清单: %LIST%
if not exist "%LIST%" (
  echo   这个文件不存在，请确认后重试。
  goto ask_list
)
goto got_list

:menu
cls
echo.
echo ============================================================
echo                 照片查重  ·  只读分析，不改任何文件
echo ============================================================
echo.
echo   [1] 交互式选择路径（可选 E 盘 / F 盘 / 指定文件夹）
echo.
echo   [2] 快速查 F 盘
echo.
echo   [3] 快速查 E 盘
echo.
echo   [4] 打开上次结果（预览页）
echo.
echo   [5] 执行清理（自动用最新那份清单，可改用拖放）
echo       也可以把清单 txt 直接拖到本文件图标上
echo.
echo   [Q] 退出
echo.
echo ------------------------------------------------------------
set "opt="
set /p opt=Please choose 1-5, Q to quit :
if "%opt%"=="1" goto run_interactive
if "%opt%"=="2" goto run_f
if "%opt%"=="3" goto run_e
if "%opt%"=="4" goto open_last
if "%opt%"=="5" goto do_clean
if "%opt%"=="Q" goto end
if "%opt%"=="q" goto end
rem 无效输入：提示后暂停退出，避免 goto menu 死循环卡住用户
echo   无效选项 "%opt%"，请输入 1-5 或 Q。
goto pause_end

:run_interactive
"%PY%" -u "%~dp0scripts\run_dedupe.py"
goto gen_report

:run_f
"%PY%" -u "%~dp0scripts\run_dedupe.py" "F:\"
goto gen_report

:run_e
"%PY%" -u "%~dp0scripts\run_dedupe.py" "E:\"
goto gen_report

:open_last
if exist "%~dp0scripts\_last_report.txt" (
  "%PY%" -u "%~dp0scripts\open_report.py"
  goto pause_end
)
set "P="
if exist "E:\WorkBuddy\整理产出\重复照片预览\index.html" set "P=E:\WorkBuddy\整理产出\重复照片预览\index.html"
if not defined P if exist "F:\index.html" set "P=F:\index.html"
if not defined P if exist "E:\index.html" set "P=E:\index.html"
if not defined P if exist "%USERPROFILE%\index.html" set "P=%USERPROFILE%\index.html"
if not defined P (
  echo   还没有结果页，请先执行一次查重。
) else (
  echo   打开: %P%
  start "" "%P%"
)
goto pause_end

:do_clean
set "LIST="
rem 坑：网页导出的清单固定叫 A类重复照片处理清单.txt，浏览器重复下载会自动
rem 改名成 "(1).txt" "(2).txt"，只按固定名字找就会永远命中第一次下载的那份旧清单
rem （实测：05:32 的 5212 条 vs 20:47 的 13522 条，条数差一倍多）。
rem 改成扫所有 *处理清单*.txt 按修改时间取最新。
rem 【关键修复】清单路径常含中文，若经 stdout(gbk) 传给批处理会变成"?"，
rem 后续 python 就打不开文件；且 for /f 直接吃命令在部分环境下会让窗口瞬间关闭。
rem 所以让 find_latest_list.py 把结果写成 UTF-8 临时文件，批处理只判断文件存不存在，
rem 绝不解析路径字符串，从根上避开中文乱码和命令子进程崩溃。
set "LATEST=%~dp0scripts\_latest_list.txt"
if exist "%LATEST%" del /q "%LATEST%" 2>nul
"%PY%" -u "%~dp0scripts\find_latest_list.py"
if exist "%LATEST%" (
  set "LIST=__LATEST__"
  goto got_list
)
rem 脚本没写出文件时（例如没找到清单），按候选路径兜底
call :try_list "E:\WorkBuddy\整理产出\A类重复照片处理清单.txt"
call :try_list "E:\WorkBuddy\整理产出\重复照片处理清单.txt"
call :try_list "%USERPROFILE%\Downloads\A类重复照片处理清单.txt"
call :try_list "%USERPROFILE%\Downloads\重复照片处理清单.txt"
call :try_list "%USERPROFILE%\Desktop\A类重复照片处理清单.txt"
call :try_list "%USERPROFILE%\Desktop\重复照片处理清单.txt"

if not defined LIST goto ask_list
goto got_list

rem 坑：网页导出的清单叫「A类重复照片处理清单.txt」，不在候选名单里时用户
rem 只会看到「未找到处理清单」，不知道下一步该怎么办。这里允许手动给路径兜底，
rem 支持把文件直接拖进窗口（拖进来会带引号，下面会去掉）。
:ask_list
echo.
echo   没有自动找到清单文件。
echo.
echo   请把清单 txt 直接拖进本窗口，或粘贴完整路径后回车，例如：
echo     %USERPROFILE%\Downloads\A类重复照片处理清单.txt
echo.
set "LIST="
set /p LIST=清单路径(直接回车取消):
if not defined LIST goto menu
set "LIST=%LIST:"=%"
if not exist "%LIST%" (
  echo.
  echo   找不到这个文件：%LIST%
  echo   请确认路径正确后重新运行本工具。
  goto ask_list
)

:got_list
echo.
if "%LIST%"=="__LATEST__" (
  echo   使用清单: 自动找到的最新一份（候选清单见上方）
  set "APPLY=--latest"
) else (
  echo   使用清单: %LIST%
  set "APPLY=%LIST%"
)
echo.
echo   *** 大批量操作前，强烈建议先选 1 预览，核对每个文件夹保留哪张 ***
echo.
echo   [1] 先预览（只看要动哪些，不动文件）
echo   [2] 确认执行（移入回收站，可还原）
echo   [3] 移到备份文件夹（更安全，不受回收站容量限制）
echo   [4] 直接删除（永久删除，不可恢复，高危慎用）
echo   [Q] 取消
set "ck="
set /p ck=Enter 1 to preview, 2/3/4 to execute, Q to cancel :
if "%ck%"=="1" goto do_preview
if "%ck%"=="2" goto really
if "%ck%"=="3" goto to_backup
if "%ck%"=="4" goto to_delete
if "%ck%"=="Q" goto pause_end
if "%ck%"=="q" goto pause_end
echo   无效选择 "%ck%"，请重选（1/2/3/4/Q）。
goto got_list

:to_backup
echo.
echo   将把清单中的副本移动到备份文件夹（不是删除）：
echo     各源文件所在盘根下的 _照片去重备份_可手动删除（I盘→I盘，H盘→H盘，同盘瞬时移动）
echo   确认无误后手动删掉这个文件夹即可彻底释放空间。
set "okb="
set /p okb=Type YES to continue :
if not "%okb%"=="YES" goto cancelled
echo.
echo   正在移动，请稍候...
echo ------------------------------------------------------------
"%PY%" -u "%~dp0scripts\apply_cleanup.py" %APPLY% --to "_照片去重备份_可手动删除" --execute
echo ------------------------------------------------------------
echo.
echo   执行结束。文件都在备份文件夹里，确认没问题后手动删除即可。
goto pause_end

:to_delete
echo.
echo   警告：将把清单中的文件直接、永久删除，不进回收站，不可恢复！
echo   这是高危操作，只应在备份后且确认无误时使用。
echo   建议先选 1 预览，确认没有误删后再选 4。
set "okd="
set /p okd=Type YES_DELETE to continue (anything else cancels) :
if not "%okd%"=="YES_DELETE" goto cancelled
echo.
echo   正在永久删除，请稍候...
echo ------------------------------------------------------------
"%PY%" -u "%~dp0scripts\apply_cleanup.py" %APPLY% --delete --execute
echo ------------------------------------------------------------
echo.
echo   执行结束。文件已永久删除，不可恢复。
echo   明细清单保存在同目录下"直接删除记录_*.txt"中。
goto pause_end

rem 坑：set /p 不能放在 if (...) 括号块里。
rem cmd 在块内遇到 set /p 后，括号与后续命令的解析会错乱，
rem 表现为「菜单显示出来了，但按数字没反应、后面代码不执行」。
rem 所以这里全部用 goto 平铺，不写嵌套括号块。

:no_list
echo.
echo   未找到处理清单 txt。
echo   请先在预览页点"生成处理清单"再点"下载为 txt"，
echo   浏览器会把文件存进"下载"文件夹，然后再运行本工具。
goto pause_end

:do_preview
"%PY%" -u "%~dp0scripts\apply_cleanup.py" %APPLY%
echo.
echo   ^^^^ 以上只是预览，没有删除任何文件。
echo   确认无误后，重新运行本工具并选 2 才会真正执行。
goto pause_end

:try_list
if not defined LIST if exist "%~1" set "LIST=%~1"
goto :eof

:really
echo.
echo   即将把清单中的重复副本移入 Windows 回收站。
echo   误删可在回收站用"还原"找回，但仍需你确认。
set "ok="
set /p ok=Move listed files to Recycle Bin? Type YES to continue :
if not "%ok%"=="YES" goto cancelled
echo.
echo   正在执行，请稍候...
echo ------------------------------------------------------------
"%PY%" -u "%~dp0scripts\apply_cleanup.py" %APPLY% --execute
echo ------------------------------------------------------------
echo.
echo   执行结束。若误删，可在 Windows 回收站点"还原"找回。
goto pause_end

:cancelled
echo.
echo   已取消，未删除任何文件。
goto pause_end

:gen_report
echo.
echo ------------------------------------------------------------
echo   正在生成预览报告（总览 + A/B/C 三类，四页 HTML）...
echo ------------------------------------------------------------
"%PY%" -u "%~dp0scripts\build_g_report.py"
if exist "%~dp0scripts\_last_report.txt" (
  echo   报告已生成，正在打开预览页...
  "%PY%" -u "%~dp0scripts\open_report.py"
) else (
  echo   本次未发现重复或未生成数据，跳过报告。
)
goto pause_end

:done
echo.
echo ------------------------------------------------------------
goto pause_end

rem 所有需要停留的出口都汇到这里。
rem 坑：以前清理流程走 goto end，而 :end 是文件末尾的空标签，
rem 窗口会直接关闭，用户根本看不到执行结果（反馈为"一闪就没了"）。
:pause_end
echo.
pause

:end
