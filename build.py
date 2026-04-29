"""
SheepNote 打包脚本
用法: python build.py [--bump]
  --bump : 自动递增 patch 版本号 (例如 4.4 → 4.5)，默认不递增
"""
import re, subprocess, sys, os

SRC      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sticky_note.py")
VER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version_info.txt")

def read_version():
    with open(SRC, encoding="utf-8") as f:
        for line in f:
            m = re.match(r'^_VERSION\s*=\s*"([^"]+)"', line)
            if m:
                return m.group(1)
    raise RuntimeError("找不到 _VERSION 常量")

def bump_version(ver: str) -> str:
    parts = ver.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)

def write_version(new_ver: str):
    # 更新 sticky_note.py
    with open(SRC, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r'^(_VERSION\s*=\s*")([^"]+)(")',
                  lambda m: f'{m.group(1)}{new_ver}{m.group(3)}',
                  text, flags=re.MULTILINE)
    text = re.sub(r'(SheepNote — 桌面便签小组件 v)[0-9.]+',
                  lambda m: f'{m.group(1)}{new_ver}', text)
    with open(SRC, "w", encoding="utf-8") as f:
        f.write(text)

    # 更新 version_info.txt
    major, minor = new_ver.split(".")[:2] if "." in new_ver else (new_ver, "0")
    tuple_ver = f"({major}, {minor}, 0, 0)"
    str_ver   = f"{new_ver}.0.0"
    fname     = f"SheepNote-v{new_ver}-Windows.exe"
    with open(VER_FILE, encoding="utf-8") as f:
        vt = f.read()
    vt = re.sub(r'filevers=\([^)]+\)', f'filevers={tuple_ver}', vt)
    vt = re.sub(r'prodvers=\([^)]+\)', f'prodvers={tuple_ver}', vt)
    vt = re.sub(r"(u'FileVersion',\s*u')[^']+(')", lambda m: f"{m.group(1)}{str_ver}{m.group(2)}", vt)
    vt = re.sub(r"(u'ProductVersion',\s*u')[^']+(')", lambda m: f"{m.group(1)}{str_ver}{m.group(2)}", vt)
    vt = re.sub(r"(u'OriginalFilename',\s*u')[^']+(')", lambda m: f"{m.group(1)}{fname}{m.group(2)}", vt)
    with open(VER_FILE, "w", encoding="utf-8") as f:
        f.write(vt)

def main():
    BASE = os.path.dirname(os.path.abspath(__file__))
    bump = "--bump" in sys.argv
    ver  = read_version()
    if bump:
        ver = bump_version(ver)
        write_version(ver)
        print(f"版本已更新至 v{ver}")
    else:
        print(f"当前版本 v{ver}（使用 --bump 自动递增）")

    ico      = os.path.join(BASE, "sheep.ico")
    out_name = f"SheepNote-v{ver}-Windows"
    ico_args = ["--icon", ico, "--add-data", f"{ico};."] if os.path.exists(ico) else []
    ver_args = ["--version-file", VER_FILE] if os.path.exists(VER_FILE) else []

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--onefile", "--windowed",
        "--distpath", os.path.join(BASE, "dist"),
        "--workpath", os.path.join(BASE, "build"),
        "--specpath", BASE,
        "--name", out_name,
        *ico_args,
        *ver_args,
        SRC,
    ]
    print("运行:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    exe = os.path.join(BASE, "dist", f"{out_name}.exe")
    print(f"\n打包完成 → {exe}")
    return exe

if __name__ == "__main__":
    main()
