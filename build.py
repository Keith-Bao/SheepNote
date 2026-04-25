"""
SheepNote 打包脚本
用法: python build.py [--bump]
  --bump : 自动递增 patch 版本号 (例如 4.2 → 4.3)，默认不递增
"""
import re, subprocess, sys, os

SRC = os.path.join(os.path.dirname(__file__), "sticky_note.py")

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
    with open(SRC, encoding="utf-8") as f:
        text = f.read()
    # 更新常量
    text = re.sub(r'^(_VERSION\s*=\s*")([^"]+)(")',
                  lambda m: f'{m.group(1)}{new_ver}{m.group(3)}',
                  text, flags=re.MULTILINE)
    # 更新 docstring 中的版本号
    text = re.sub(r'(SheepNote — 桌面便签小组件 v)[0-9.]+',
                  lambda m: f'{m.group(1)}{new_ver}', text)
    with open(SRC, "w", encoding="utf-8") as f:
        f.write(text)

def main():
    BASE = os.path.dirname(os.path.abspath(__file__))
    bump = "--bump" in sys.argv
    ver = read_version()
    if bump:
        ver = bump_version(ver)
        write_version(ver)
        print(f"版本已更新至 v{ver}")
    else:
        print(f"当前版本 v{ver}（使用 --bump 自动递增）")

    ico = os.path.join(BASE, "sheep.ico")
    ico_args = ["--icon", ico, "--add-data", f"{ico};."] if os.path.exists(ico) else []

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--onefile", "--windowed",
        "--distpath", os.path.join(BASE, "dist"),
        "--workpath", os.path.join(BASE, "build"),
        "--specpath", BASE,
        "--name", "SheepNote",
        *ico_args,
        SRC,
    ]
    print("运行:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    exe = os.path.join(BASE, "dist", "SheepNote.exe")
    print(f"\n打包完成 → {exe}")

if __name__ == "__main__":
    main()