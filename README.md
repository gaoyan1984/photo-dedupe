# 照片查重工具 · Photo Dedupe

一个**本地、只读、零依赖云服务**的照片/视频查重工具。帮你在一大堆照片里找出重复、相似的图片与视频，生成可交互的网页预览，再按需安全清理（移入回收站 / 移动到备份目录 / 永久删除，均需你确认）。

> 开源许可证：**MIT**（见 [LICENSE](LICENSE)）。代码公开、可随意使用与修改，只需保留署名。

---

## 一、它能做什么

- **多格式支持**：JPG / PNG / HEIC / HEIF / GIF / BMP / WEBP / TIFF，以及佳能 CR2、尼康 NEF、索尼 ARW、DNG 等主流相机 RAW。
- **三种重复判定**：
  - **A 类 · 同名重复**：文件名完全相同（最安全，可放心清理）。
  - **B 类 · 异名相似**：文件名不同但内容一眼能认出是同一张（需逐张看图确认）。
  - **C 类 · 确认真重复**：文件名不同、但经"大小 + 感知哈希 + 逐像素严格比对"三重核验确为同一张。
- **交互式网页预览**（核心功能）：
  - 按"所在文件夹"分组，每组标明正本（保留）与副本（可清理）。
  - 每张照片**完整路径显示在右侧**（不再挤在照片下方，长路径也能看全）。
  - 每个文件夹支持 **「一键展开全部照片」** 与 **「一键收起全部照片」**，几千张也能秒开不卡。
  - 可「设为正本」「勾选清理」「只看我的副本」「导出清单」。
- **只扫描不改动**：扫描阶段绝不移动、重命名、删除任何文件。
- **安全清理**：清理前必须先导出清单并人工确认，默认移入 Windows 回收站（可还原），也可以移动到备份目录或永久删除（需显式 `--delete`）。

---

## 二、运行环境

- **Python 3.8+**
- **Pillow**（唯一第三方依赖，用于图片解码与缩略图）

安装依赖：

```bash
pip install Pillow
```

> 说明：HEIC/HEIF 需要 Pillow 较新版本（≥9）。如需处理 HEIC，确保 Pillow 已支持（或额外安装 `pillow-heif`）。

---

## 三、使用方法

### 1. 扫描查重（只读，不改动任何文件）

```bash
# 扫描单个目录
python scripts/run_dedupe.py "D:/我的照片"

# 同时扫描多个路径（分号分隔）
python scripts/run_dedupe.py --paths "D:/照片;E:/备份照片"

# 指定输出目录
python scripts/run_dedupe.py "D:/我的照片" --work "D:/WorkBuddy/查重结果"

# 不传参数 → 进入交互式选盘/选文件夹菜单（Windows）
python scripts/run_dedupe.py
```

扫描完成后，会在**被扫描目录**下生成 `照片查重报告/` 子文件夹，里面包含明细 CSV 与缩略图。

### 2. 生成网页预览

```bash
python scripts/build_g_report.py
```

不传参数时自动读取上一次扫描的工作目录。生成后**双击 `照片查重报告/index.html`** 即可在浏览器查看（报告数据已打包成 `.js`，可直接用 `file://` 打开，无需起服务器）。

### 3. 安全清理

在预览页勾选要清理的副本 → 导出清单（txt）→ 用脚本处理：

```bash
# 预览（不删任何文件，先看会动哪些）
python scripts/apply_cleanup.py "A类重复照片清单.txt"

# 确认无误后，移入 Windows 回收站（可还原，推荐）
python scripts/apply_cleanup.py "A类重复照片清单.txt" --execute

# 或移动到备份目录（不删，只是搬走）
python scripts/apply_cleanup.py "A类重复照片清单.txt" --to "D:/待删备份" --execute

# 或永久删除（不可恢复，慎用）
python scripts/apply_cleanup.py "A类重复照片清单.txt" --delete --execute
```

> ⚠️ 默认只"预览"，必须显式加 `--execute` 才会真正移动/删除；`--delete` 为永久删除，请务必先备份。

### 4. 多进程加速版（大批量更快）

`scripts/run_dedupe_fast.py` 是官方版的多进程并行加速版，**判定逻辑完全一致、结果逐字节相同**，只是把 MD5 计算、感知哈希、逐像素核验改为多进程，吃满多核、速度更快：

```bash
python scripts/run_dedupe_fast.py "D:/我的照片" --work "D:/WorkBuddy/查重结果"
```

可用环境变量 `DEDUPE_WORKERS` 覆盖并行进程数（默认 8）。

---

## 四、目录结构

```
photo-dedupe/
├── scripts/
│   ├── run_dedupe.py          # 主程序：扫描 + 三重判定
│   ├── run_dedupe_fast.py     # 多进程加速版（判定一致，更快）
│   ├── build_g_report.py      # 生成交互式网页预览
│   ├── apply_cleanup.py       # 安全清理（回收站/移动/删除）
│   ├── verify_cleanup_list.py # 清理前核对清单
│   ├── find_latest_list.py    # 自动定位最新导出清单
│   ├── build_dup_index.py     # 构建重复索引
│   ├── build_big_report.py    # 大报告生成
│   ├── pick_drives.py         # 磁盘选择辅助
│   ├── open_report.py         # 打开报告辅助
│   └── report_templates/      # 预览页 HTML 模板（a/b/c/index）
├── templates/
│   └── picker.html            # 交互选盘界面
├── 照片查重.bat                # Windows 一键启动器（拖文件夹即可）
├── SKILL.md                   # WorkBuddy 技能说明（如使用 WorkBuddy 可参考）
├── LICENSE                    # MIT
└── README.md
```

---

## 五、工作原理（简述）

1. **扫描**：遍历目标目录，按扩展名收集照片/视频，跳过 `$Recycle.Bin` 等系统目录。
2. **第一道筛选**：按文件大小分组，大小不同的一定不是同一张。
3. **第二道筛选**：对同大小的算 MD5 内容哈希，MD5 相同即确为同一文件。
4. **第三道筛选（感知哈希）**：对大小相同但 MD5 不同的，算感知哈希（pHash），相似度高的列为"疑似相似"。
5. **严格核验**：对疑似相似组做**逐像素比对**，超过阈值才判定为"确认真重复"，最大限度避免误判。
6. **生成报告**：把结果写成 CSV + 交互式 HTML 预览。

---

## 六、安全与隐私

- **全程本地运行**，不上传任何照片，不经过任何云服务。
- **扫描只读**：绝不改动你的原始文件。
- **清理需确认**：删除/移动前必须先导出清单并人工确认；默认进回收站可还原。
- 建议清理前对重要照片做一次备份。

---

## 七、常见问题

**Q：HEIC 打不开 / 预览空白？**
A：确保 Pillow ≥ 9，或额外安装 `pillow-heif` 以支持 HEIC/HEIF 解码。

**Q：报告打开是空白？**
A：请**双击 `index.html` 直接打开**（file:// 方式），不要通过某些会拦截本地脚本的环境打开。报告数据已打包成 `.js` 文件，无需起服务器。

**Q：能跨多块硬盘查重吗？**
A：可以，`--paths` 用分号分隔多个盘符/目录即可。

---

## 八、许可证

[MIT License](LICENSE) © 2026 gaoyan1984
