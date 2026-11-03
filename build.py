import json
import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, "dist")
NAME = "网络实验陪练"
OUT = os.path.join(DIST, NAME)

COPY_APP = ["app.py", "ai.py", "ailab.py", "ensp_kit.py", "doctor.py", "mcp_server.py",
            "gen_kb.py", "labs", "kb", "quiz", "web"]
SKIP_LIB = {"test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3",
            "distutils", "pydoc_data", "site-packages", "turtledemo"}

LAUNCH = """@echo off
cd /d "%~dp0app"
start "" "%~dp0runtime\\pythonw.exe" app.py
exit
"""

CHECK = """@echo off
cd /d "%~dp0app"
chcp 65001 >nul
"%~dp0runtime\\python.exe" doctor.py
echo.
pause
"""

STOP = """@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
if exist "app\\app.pid" (
  set /p PID=<"app\\app.pid"
  if defined PID taskkill /PID !PID! /F >nul 2>&1
  del "app\\app.pid" >nul 2>&1
)
exit
"""

README = """网络实验陪练 · 绿色版

1. 双击「启动.bat」，浏览器会自动打开界面。
2. 第一次用先双击「环境自检.bat」，四项全绿才说明能搭实验。
3. 生成实验要用 DeepSeek，在界面上点右上角「实验助教」，把 API Key 粘进去。
4. 关掉：双击「停止.bat」，或者任务管理器结束 pythonw。

需要自己装的东西：华为 eNSP（含 VirtualBox 5.2.x）。本程序不附带任何华为软件和镜像。

数据都在 app\\workspace 里，整个文件夹拷到别的电脑可以直接用。
"""


def size_of(p):
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def copy_runtime(src, dst):
    os.makedirs(dst, exist_ok=True)
    for f in ("python.exe", "pythonw.exe", "python313.dll", "vcruntime140.dll",
              "vcruntime140_1.dll", "python3.dll"):
        s = os.path.join(src, f)
        if os.path.exists(s):
            shutil.copy2(s, dst)
    lib_src, lib_dst = os.path.join(src, "Lib"), os.path.join(dst, "Lib")
    shutil.copytree(lib_src, lib_dst, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*SKIP_LIB, "__pycache__", "*.pyc"))
    dll_src, dll_dst = os.path.join(src, "DLLs"), os.path.join(dst, "DLLs")
    shutil.copytree(dll_src, dll_dst, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("*.lib", "__pycache__"))


def main():
    os.makedirs(OUT, exist_ok=True)

    print("复制运行时…")
    copy_runtime(sys.base_prefix, os.path.join(OUT, "runtime"))

    print("复制程序…")
    app_dir = os.path.join(OUT, "app")
    os.makedirs(app_dir, exist_ok=True)
    for name in COPY_APP:
        s = os.path.join(BASE, name)
        d = os.path.join(app_dir, name)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.topo",
                                                          "*.state.json", "*.progress.json"))
        elif os.path.exists(s):
            shutil.copy2(s, d)

    cfg = {"api_key": "", "model": "deepseek-flash", "base_url": "https://api.deepseek.com",
           "temperature": 0.4, "ensp_path": "", "vbox_path": ""}
    json.dump(cfg, open(os.path.join(app_dir, "config.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    os.makedirs(os.path.join(app_dir, "workspace", "hist"), exist_ok=True)

    manual = os.path.join(BASE, "使用手册.md")
    if os.path.exists(manual):
        shutil.copy2(manual, os.path.join(app_dir, "使用手册.md"))
        shutil.copy2(manual, os.path.join(OUT, "使用手册.md"))
    course = os.path.join(BASE, "course.json")
    if os.path.exists(course):
        shutil.copy2(course, os.path.join(app_dir, "course.json"))

    with open(os.path.join(OUT, "启动.bat"), "w", encoding="gbk", newline="\r\n") as f:
        f.write(LAUNCH)
    with open(os.path.join(OUT, "环境自检.bat"), "w", encoding="gbk", newline="\r\n") as f:
        f.write(CHECK)
    with open(os.path.join(OUT, "停止.bat"), "w", encoding="gbk", newline="\r\n") as f:
        f.write(STOP)
    with open(os.path.join(OUT, "使用说明.txt"), "w", encoding="gbk", newline="\r\n") as f:
        f.write(README)

    mb = size_of(OUT) / 1024 / 1024
    print(f"完成：{OUT}")
    print(f"体积：{mb:.1f} MB")


if __name__ == "__main__":
    main()
