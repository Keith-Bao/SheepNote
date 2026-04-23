# SheepNote 便签

一个轻量的 Windows 桌面便签小组件，无需安装，双击即用。

## 功能

- 多便签：可新建多张便签，各自独立
- 任务管理：添加 / 勾选 / 删除任务，支持内联编辑
- 颜色主题：5 个预设颜色 + 自定义色盘，每张便签单独设置
- 字体大小 / 透明度：滑块实时调节，持久保存
- 便签列表：一键查看所有便签，控制显示 / 隐藏
- 置顶 / 锁定：锁定后内容只读，防误触
- 数据持久化：关闭窗口只是隐藏，重新打开原样恢复
- 单实例唤醒：再次双击 exe 可唤醒所有隐藏便签

## 使用

直接双击 `便签.exe`，无需安装 Python 环境。

## 从源码构建

```bash
pip install pyinstaller
python -m PyInstaller --noconsole --onefile --name "便签" --version-file version_info.txt sticky_note.py
```

## 作者

大绵羊 / Keith Bao
