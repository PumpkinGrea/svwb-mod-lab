"""Windows desktop entry point for the local card artwork editor."""
import argparse
import io
import json
import os
from pathlib import Path
import sys
import traceback

from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QThreadPool, Qt, QTimer
from PySide6.QtGui import QColor, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QSlider, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)
from modtool.core import ModManager, fit_image
from modtool.catalog import empty_catalog, validate_catalog
from modtool.updater import IndexStore
from modtool.localmeta import LocalReader
from modtool.jobs import Work
from modtool.management_ui import ManagementDialog
from modtool.management import scan_backups, restore_entries


def app_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def data_dir():
    internal = Path(getattr(sys, "_MEIPASS", app_dir())) / "app-data"
    return internal if internal.is_dir() else app_dir() / "input/mod-app-data"


class Preview(QLabel):
    def __init__(self, caption):
        super().__init__(caption)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(240, 300)
        self.setStyleSheet("background:#171b23;border:1px solid #3d4658;border-radius:8px;color:#abb7c9")
        self.original = None

    def show_image(self, image):
        if image is None:
            self.original = None
            self.clear()
            return
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        self.original = QPixmap()
        self.original.loadFromData(buffer.getvalue())
        self.refresh()

    def refresh(self):
        if self.original:
            self.setPixmap(self.original.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()


class Window(QMainWindow):
    def __init__(self, game_dir=None, auto_check=True):
        super().__init__()
        self.setWindowTitle("SVWB 卡图工坊 · 本地测试版")
        self.resize(1280, 860)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.jobs = set()
        self.manager = None
        self.selected = None
        self.document = None
        self.imported = None
        self.current_sha = None
        self.busy = False
        self.management_open = False
        self.allow_auto = auto_check
        self.settings = QSettings("SVWBModLab", "CardMod")
        self.index = empty_catalog()
        self.by_texture = {card["texture_id"]: card for card in self.index["cards"]}
        self.base = (data_dir() / "bundle-base.bin").read_bytes()
        root = QWidget()
        outer = QVBoxLayout(root)
        self.setCentralWidget(root)
        top = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("将整个程序目录放进游戏目录，或在这里选择游戏目录")
        self.path.setReadOnly(True)
        self.browse = QPushButton("选择游戏目录")
        self.browse.clicked.connect(self.choose_game)
        top.addWidget(QLabel("游戏位置"))
        top.addWidget(self.path, 1)
        top.addWidget(self.browse)
        outer.addLayout(top)
        self.note = QLabel()
        self.note.setWordWrap(True)
        outer.addWidget(self.note)
        update_tools = QHBoxLayout()
        self.auto_update = QCheckBox("启动时刷新本地索引")
        self.auto_update.setChecked(self.settings.value("local_auto_refresh", True, type=bool))
        self.auto_update.toggled.connect(lambda value: self.settings.setValue("local_auto_refresh", value))
        self.initialize_button = QPushButton("检查磁盘读取")
        self.initialize_button.clicked.connect(self.initialize_local)
        self.update_button = QPushButton("刷新本地索引")
        self.update_button.clicked.connect(lambda: self.update_index(False))
        self.rollback_button = QPushButton("回退上份索引")
        self.rollback_button.clicked.connect(self.rollback_index)
        self.guide_button = QPushButton("使用说明")
        self.guide_button.clicked.connect(self.show_guide)
        for control in (self.auto_update, self.initialize_button, self.update_button, self.rollback_button, self.guide_button):
            update_tools.addWidget(control)
        outer.addLayout(update_tools)
        splitter = QSplitter()
        outer.addWidget(splitter, 1)
        sidebar = QWidget()
        left = QVBoxLayout(sidebar)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索中文卡名 / 卡牌ID / 纹理ID")
        self.search.textChanged.connect(self.schedule_filter)
        self.cached = QCheckBox("仅显示本地已缓存的卡图")
        self.cached.setChecked(True)
        self.cached.toggled.connect(self.filter_cards)
        self.count = QLabel()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self.select_card)
        left.addWidget(self.search)
        left.addWidget(self.cached)
        left.addWidget(self.count)
        left.addWidget(self.list, 1)
        splitter.addWidget(sidebar)
        main = QWidget()
        right = QVBoxLayout(main)
        self.details = QLabel("先选择游戏目录，再搜索并选择卡图。")
        self.details.setWordWrap(True)
        right.addWidget(self.details)
        previews = QHBoxLayout()
        self.before = Preview("原图")
        self.after = Preview("替换预览")
        for title, preview in (("恢复基准（首次备份 / 当前本地图）", self.before), ("当前卡图 / 替换预览", self.after)):
            column = QVBoxLayout()
            column.addWidget(QLabel(title))
            column.addWidget(preview, 1)
            previews.addLayout(column, 1)
        right.addLayout(previews, 1)
        self.image_path = QLabel("未导入图片；右侧显示游戏缓存中当前的卡图。")
        self.image_path.setWordWrap(True)
        right.addWidget(self.image_path)
        tools = QHBoxLayout()
        self.import_button = QPushButton("导入替换图片")
        self.import_button.clicked.connect(self.import_image)
        self.mode = QComboBox()
        self.mode.addItem("填满并裁剪", "cover")
        self.mode.addItem("完整保留 / 黑边", "contain")
        self.mode.addItem("拉伸至原图尺寸", "stretch")
        self.mode.currentIndexChanged.connect(self.update_preview)
        tools.addWidget(self.import_button)
        tools.addWidget(self.mode)
        right.addLayout(tools)
        controls = QGridLayout()
        self.zoom = self.slider(100, 300, 100)
        self.horizontal = self.slider(0, 100, 50)
        self.vertical = self.slider(0, 100, 50)
        for row, (label, slider) in enumerate((("缩放 1–3 倍", self.zoom), ("水平裁剪位置", self.horizontal), ("垂直裁剪位置", self.vertical))):
            controls.addWidget(QLabel(label), row, 0)
            controls.addWidget(slider, row, 1)
        right.addLayout(controls)
        actions = QHBoxLayout()
        self.apply_button = QPushButton("备份并应用替换")
        self.restore_button = QPushButton("恢复选中卡图")
        self.restore_all_button = QPushButton("一键恢复全部")
        self.apply_button.clicked.connect(self.apply)
        self.restore_button.clicked.connect(self.restore)
        self.restore_all_button.clicked.connect(self.restore_all)
        self.manage_button = QPushButton("修改与备份管理")
        self.manage_button.clicked.connect(self.show_management)
        for button in (self.apply_button, self.restore_button, self.restore_all_button, self.manage_button):
            actions.addWidget(button)
        right.addLayout(actions)
        splitter.addWidget(main)
        splitter.setSizes([350, 900])
        self.status = QLabel("就绪")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.filter_cards)
        self.setStyleSheet("QMainWindow{background:#f4f6fa} QPushButton{padding:8px} QLineEdit{padding:7px} QListWidget{font-size:13px}")
        self.controls = [self.browse, self.search, self.cached, self.list, self.import_button,
                         self.mode, self.zoom, self.horizontal, self.vertical, self.apply_button,
                         self.restore_button, self.restore_all_button, self.auto_update,
                         self.initialize_button, self.update_button, self.rollback_button, self.manage_button]
        self.update_index_note()
        if game_dir:
            self.set_game(game_dir)
        else:
            candidate = app_dir()
            if (candidate / "ShadowverseWB.exe").exists():
                self.set_game(candidate)
            elif (candidate.parent / "ShadowverseWB.exe").exists():
                self.set_game(candidate.parent)
        self.refresh_enabled()

    def slider(self, minimum, maximum, value):
        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.valueChanged.connect(self.update_preview)
        return slider

    def choose_game(self):
        path = QFileDialog.getExistingDirectory(self, "选择 ShadowverseWB 游戏安装目录")
        if path:
            self.set_game(path)

    def set_game(self, path):
        try:
            manager = ModManager(path, self.base)
        except Exception as exc:
            self.error(str(exc))
            return
        self.manager = manager
        self.index_store = IndexStore(manager.game_dir)
        index, warning = self.index_store.load()
        self.install_index(index)
        self.path.setText(str(manager.game_dir))
        self.filter_cards()
        if warning:
            self.status.setText(f"{warning}；已回退到可用索引。")
        if self.allow_auto:
            QTimer.singleShot(1200, self.automatic_update)

    def update_index_note(self):
        ident = self.index["version"]
        label = ident[6:22] if ident.startswith("local:") else "未建立（请刷新本地索引）"
        self.note.setText(f"本地索引指纹：{label} · 全程离线 · 应用/恢复前须关闭游戏")
        self.note.setToolTip("依据所选游戏的 meta 清单和缓存主数据生成；指纹不是 CDN 数字资源版本号。")

    def initialize_local(self):
        if not self.manager or self.busy:
            return
        def completed(message):
            self.status.setText(message)
            self.update_index()
        self.run_job(LocalReader(self.manager.game_dir).initialize, completed, "正在解析磁盘配置并验证本地清单…")

    def install_index(self, index):
        self.clear_selection()
        self.index = validate_catalog(index)
        self.by_texture = {card["texture_id"]: card for card in self.index["cards"]}
        self.update_index_note()
        self.details.setText("请选择并核对卡图。共用纹理可能影响多条卡牌记录。")

    def automatic_update(self):
        if not self.manager or not self.auto_update.isChecked() or not self.allow_auto:
            return
        if self.busy or self.imported is not None or self.management_open:
            QTimer.singleShot(5000, self.automatic_update)
            return
        self.update_index(True)

    def update_index(self, automatic=False):
        if not self.manager or self.busy:
            return
        if not automatic and self.imported is not None and not self.confirm("更新索引将清除尚未应用的图片预览，但不修改游戏缓存或备份。继续？"):
            return
        store, current = self.index_store, self.index
        def completed(result):
            if result["updated"]:
                self.install_index(result["index"])
                self.filter_cards()
            self.status.setText(result["message"])
        def failed(message):
            message = f"本地索引刷新失败，保留现有索引（可能已过时）：{message}"
            if automatic:
                self.status.setText(message)
            else:
                self.error(message)
        self.run_job(lambda: store.update(current, force=not automatic), completed,
                     "正在读取本地 meta 清单与缓存主数据…（不联网）", on_error=failed)

    def rollback_index(self):
        if not self.manager or self.busy:
            return
        if not self.confirm("将搜索索引回退到上一份。不会恢复、替换游戏卡图，也不会修改原始备份。继续？"):
            return
        def completed(index):
            self.install_index(index)
            self.filter_cards()
            self.status.setText("已回退上份本地索引；游戏资源与备份未改变。下次启动仍会尝试匹配本地清单。")
        self.run_job(lambda: self.index_store.rollback(self.index), completed, "正在回退索引…")

    def show_guide(self):
        path = data_dir() / "USER_GUIDE.md"
        if not path.is_file():
            path = app_dir() / "USER_GUIDE.md"
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.error(f"无法读取使用说明：{exc}")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("SVWB 卡图工坊 · 使用说明")
        dialog.resize(880, 720)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setMarkdown(content)
        layout.addWidget(browser)
        close = QPushButton("关闭")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def show_management(self):
        if not self.manager or self.busy:
            return
        dialog = ManagementDialog(self)
        self.management_open = True
        try:
            dialog.exec()
        finally:
            self.management_open = False
        if dialog.changed and not self.busy:
            # Refresh an existing preview without discarding an imported replacement.
            if self.selected:
                imported = self.imported
                image_label = self.image_path.text()
                def refreshed(result):
                    self.loaded(result)
                    if imported is not None:
                        self.imported = imported
                        self.image_path.setText(image_label)
                        self.update_preview()
                self.run_job(lambda: self.manager.read(self.selected["asset"]),
                             refreshed, "正在更新恢复后的卡图预览…")
            else:
                self.status.setText("管理操作已完成；备份保留。")
        dialog.deleteLater()

    def schedule_filter(self):
        self.timer.start(180)

    def filter_cards(self):
        if not self.manager or self.busy:
            return
        query = "".join(self.search.text().split()).casefold()
        self.list.clear()
        for card in self.index["cards"]:
            text = f"{card['name']} {card['texture_id']} {' '.join(map(str,card['card_ids']))}"
            if query and query not in "".join(text.split()).casefold():
                continue
            exists = self.manager.target(card["asset"]).is_file()
            if self.cached.isChecked() and not exists:
                continue
            item = QListWidgetItem(f"{card['name']}\n纹理 {card['texture_id']} · {'已缓存' if exists else '未缓存'}")
            # Qt QVariant cannot represent unsigned 64-bit checksums in nested dictionaries.
            item.setData(Qt.UserRole, card["texture_id"])
            item.setToolTip(card["relation"])
            self.list.addItem(item)
        self.count.setText(f"找到 {self.list.count()} 张纹理；同组候选请通过预览确认。")
        self.refresh_enabled()

    def clear_selection(self):
        self.selected = None
        self.document = None
        self.imported = None
        self.current_sha = None
        self.before.show_image(None)
        self.after.show_image(None)
        self.image_path.setText("未导入图片")

    def select_card(self, item, previous=None):
        self.clear_selection()
        if not item:
            self.refresh_enabled()
            return
        self.selected = self.by_texture[item.data(Qt.UserRole)]
        card = self.selected
        self.details.setText(f"{card['name']}\n纹理编号：{card['texture_id']} · {card['relation']}\n卡牌 ID：{', '.join(map(str,card['card_ids'])) or '未关联'}")
        self.run_job(lambda: self.manager.read(card["asset"]), self.loaded,
                     "正在只读解析本地卡图…")

    def loaded(self, result):
        self.document, image, self.current_sha = result
        self.before.show_image(self.document.image())
        self.after.show_image(image)
        self.imported = None
        self.image_path.setText("右侧显示当前游戏缓存。导入图片后，右侧切换为待应用预览。")
        baseline = " · 首次应用需确认本地恢复基准，未认证为官方原图" if self.document.asset.get("fingerprint_source") == "unconfirmed_local" else ""
        self.status.setText(f"{self.manager.state(self.selected['asset'])} · {image.width}×{image.height} · 格式 {self.document.texture.m_TextureFormat}{baseline}")

    def import_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择替换图片", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        try:
            with Image.open(path) as image:
                image.load()
                from PIL import ImageOps
                self.imported = ImageOps.exif_transpose(image).convert("RGBA")
            self.image_path.setText(f"待应用图片：{path}")
            self.zoom.setValue(100)
            self.horizontal.setValue(50)
            self.vertical.setValue(50)
            self.update_preview()
        except Exception as exc:
            self.error(str(exc))
        self.refresh_enabled()

    def prepared_image(self):
        return fit_image(self.imported, (self.document.texture.m_Width, self.document.texture.m_Height),
                         self.mode.currentData(), self.zoom.value() / 100,
                         (self.horizontal.value() / 100, self.vertical.value() / 100))

    def update_preview(self, *args):
        if self.imported is not None and self.document:
            self.after.show_image(self.prepared_image())

    def confirm(self, text):
        return QMessageBox.question(self, "确认文件修改", text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def apply(self):
        if not self.confirm("请确认游戏已关闭。\n将只修改选中的纹理缓存；首次原文件会永久保留在游戏目录的 SVWBModData/backups 中。\n是否应用？"):
            return
        card = self.selected
        trust_local = self.document.asset.get("fingerprint_source") == "unconfirmed_local"
        if trust_local and not self.confirm("完全离线模式无法证明当前文件是未修改的官方原图。\n如果其他工具曾修改它，恢复只能回到当前状态。\n请核对左侧预览；确认把当前本地文件作为首次恢复基准并应用？"):
            return
        image = self.prepared_image()
        expected = self.current_sha
        context = {"name": card["name"], "texture_id": card["texture_id"], "index_version": self.index["version"]}
        self.run_job(lambda: self.manager.apply(card["asset"], image, expected, trust_local=trust_local, context=context),
                     lambda result: self.reload("替换成功；重新打开游戏查看效果。"), "正在编码、打包、备份并应用…")

    def reload(self, message):
        if self.selected:
            self.loaded(self.manager.read(self.selected["asset"]))
        self.status.setText(message)

    def restore(self):
        if self.confirm("关闭游戏后，将所选卡图恢复到首次备份的原始文件。继续？"):
            asset = self.selected["asset"]
            self.run_job(lambda: self.manager.restore(asset), lambda result: self.reload("原卡图已恢复并校验。"), "正在恢复原卡图…")

    def restore_all(self):
        if not self.confirm("关闭游戏后，恢复本工具在当前游戏目录中修改过的全部卡图。\n外部发生变化的文件将跳过，不会强制覆盖。继续？"):
            return
        def done(result):
            restored, errors = result
            self.reload(f"已恢复 {restored} 张卡图；跳过/失败 {len(errors)} 项。")
            if errors:
                QMessageBox.warning(self, "部分资源未恢复", "\n".join(errors))
        manager, cards = self.manager, list(self.index["cards"])
        def operation():
            rows = scan_backups(manager, cards)
            restored, errors = restore_entries(manager, cards, [row for row in rows if row["restorable"]])
            errors.extend(f"{row['id']}: {row['reason']}" for row in rows if row["state"] not in ("modified", "restored"))
            return restored, errors
        self.run_job(operation, done, "正在检查备份并恢复全部…")

    def run_job(self, function, callback, message, on_error=None):
        if self.busy:
            return
        self.busy = True
        self.refresh_enabled()
        self.status.setText(message)
        job = Work(function)
        self.jobs.add(job)
        def finish(result, failed=False):
            self.busy = False
            self.jobs.discard(job)
            try:
                if failed:
                    (on_error or self.error)(result)
                else:
                    callback(result)
            except Exception as exc:
                self.error(str(exc))
            self.refresh_enabled()
        job.signals.success.connect(lambda result: finish(result))
        job.signals.failure.connect(lambda error: finish(error, True))
        self.pool.start(job)

    def refresh_enabled(self):
        for control in self.controls:
            control.setEnabled(not self.busy)
        ready = not self.busy and self.document is not None
        self.import_button.setEnabled(ready)
        self.apply_button.setEnabled(ready and self.imported is not None)
        self.restore_button.setEnabled(ready and self.manager.metadata(self.selected["asset"]) is not None)
        self.restore_all_button.setEnabled(not self.busy and self.manager is not None)
        self.manage_button.setEnabled(not self.busy and self.manager is not None)
        self.update_button.setEnabled(not self.busy and self.manager is not None)
        self.initialize_button.setEnabled(not self.busy and self.manager is not None)
        self.rollback_button.setEnabled(not self.busy and self.manager is not None
                                        and self.index_store.has_previous())

    def error(self, message):
        self.status.setText(message)
        QMessageBox.warning(self, "未完成操作", message)

    def closeEvent(self, event):
        if self.busy:
            QMessageBox.information(self, "正在处理", "请等待当前读取或写入完成后再关闭窗口。")
            event.ignore()
        else:
            super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-dir")
    parser.add_argument("--smoke-test", help="Run a read-only packaged startup check, write JSON and exit")
    parser.add_argument("--verify-disk", action="store_true", help="Also rebuild the local index during the startup check")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in ((QPalette.Window, "#f4f6fa"), (QPalette.WindowText, "#202938"),
                        (QPalette.Base, "#ffffff"), (QPalette.AlternateBase, "#edf1f7"),
                        (QPalette.Text, "#202938"), (QPalette.Button, "#e8edf5"),
                        (QPalette.ButtonText, "#202938"), (QPalette.Highlight, "#3478d4"),
                        (QPalette.HighlightedText, "#ffffff"), (QPalette.PlaceholderText, "#6b7280")):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#8d96a6"))
    app.setPalette(palette)
    try:
        window = Window(args.game_dir, auto_check=not bool(args.smoke_test))
        if args.smoke_test:
            # Showing the populated list can select its first item and launch
            # an unrelated preview worker. The check owns its reads and must
            # not quit Qt while that worker is still running.
            window.list.blockSignals(True)
            if args.verify_disk and window.manager:
                window.install_index(window.index_store.update(window.index)["index"])
                window.filter_cards()
            result = {"catalog_rows": len(window.index["cards"]), "version": window.index["version"],
                      "source": window.index.get("source"), "game_detected": window.manager is not None}
            if window.manager and window.index["cards"]:
                card = next(c for c in window.index["cards"] if c["texture_id"] == "109741100")
                doc, image, _ = window.manager.read(card["asset"])
                window.before.show_image(doc.image())
                window.after.show_image(image)
                result["image_size"] = list(image.size)
                sample = image.copy()
                from PIL import ImageDraw
                ImageDraw.Draw(sample).rectangle((0, 0, 120, 120), fill=(255, 0, 180, 255))
                encoded, checked_image = doc.rebuild(sample)
                result["repack_verified"] = checked_image.size == image.size and len(encoded) > 256
            window.show()
            def finish():
                screenshot = str(Path(args.smoke_test).with_suffix(".png"))
                window.grab().save(screenshot)
                Path(args.smoke_test).write_text(json.dumps(result, indent=2), encoding="utf-8")
                app.quit()
            QTimer.singleShot(500, finish)
        else:
            window.show()
        code = app.exec()
        # Dispose Qt objects while QApplication is alive, rather than relying
        # on frozen interpreter shutdown and its unpredictable finalizer order.
        window.pool.waitForDone()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        return code
    except Exception:
        details = traceback.format_exc()
        if args.smoke_test:
            Path(args.smoke_test).write_text(json.dumps({"error": details}), encoding="utf-8")
        else:
            QMessageBox.critical(None, "启动失败", "缺少本地基础参数或运行依赖。\n\n" + details)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
