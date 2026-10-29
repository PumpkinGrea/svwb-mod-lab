"""Searchable, asynchronous backup management dialog; never deletes backups."""
from collections import Counter
from datetime import datetime
import os
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QTextBrowser, QVBoxLayout,
)

from .jobs import Work
from .management import scan_backups, restore_entries


STATES = [("全部状态", ""), ("可恢复", "modified"), ("已恢复", "restored"),
          ("外部变更", "external"), ("缓存缺失", "missing"),
          ("索引不匹配 / 可能已更新", "outdated"), ("记录或备份异常", "invalid")]


def display_time(value, estimated=False):
    try:
        text = datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        return text + ("（约）" if estimated else "")
    except (TypeError, ValueError):
        return "未知"


class ManagementDialog(QDialog):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.manager = editor.manager
        self.cards = list(editor.index["cards"])
        self.entries = []
        self.jobs = set()
        self.busy = False
        self.changed = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.setWindowTitle("修改与备份管理")
        self.resize(1180, 760)
        layout = QVBoxLayout(self)
        intro = QLabel("集中管理此游戏目录的修改记录。检查仅读取文件；恢复前须关闭游戏。备份始终保留，不提供删除或强制覆盖。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        if not self.cards:
            warning = QLabel("当前没有可用本地索引：可以按备份指纹检查与恢复，但无法核对资源是否仍被游戏使用。建议先建立本地索引。")
            warning.setWordWrap(True)
            warning.setStyleSheet("color:#a15b00")
            layout.addWidget(warning)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索卡名、纹理编号或缓存标识")
        self.search.textChanged.connect(self.filter_rows)
        self.state_filter = QComboBox()
        for title, state in STATES:
            self.state_filter.addItem(title, state)
        self.state_filter.currentIndexChanged.connect(self.filter_rows)
        self.refresh_button = QPushButton("重新检查")
        self.refresh_button.clicked.connect(self.refresh)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.state_filter)
        filters.addWidget(self.refresh_button)
        layout.addLayout(filters)
        self.summary = QLabel("尚未检查")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["卡名", "纹理编号", "状态", "首次备份", "最近替换", "备份大小"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        layout.addWidget(self.table, 1)
        self.details = QTextBrowser()
        self.details.setMaximumHeight(155)
        self.details.setPlainText("选择一项查看检查结果。按住 Ctrl / Shift 可选择多项。")
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.restore_selected_button = QPushButton("恢复选中项")
        self.restore_selected_button.clicked.connect(self.restore_selected)
        self.restore_all_button = QPushButton("恢复全部可恢复项")
        self.restore_all_button.clicked.connect(self.restore_all_safe)
        self.locate_button = QPushButton("在编辑器中查看")
        self.locate_button.clicked.connect(self.locate)
        self.folder_button = QPushButton("打开备份目录")
        self.folder_button.clicked.connect(self.open_folder)
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.reject)
        for control in (self.restore_selected_button, self.restore_all_button, self.locate_button, self.folder_button, self.close_button):
            actions.addWidget(control)
        layout.addLayout(actions)
        self.status = QLabel("准备检查…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.update_controls()
        QTimer.singleShot(0, self.refresh)

    def selected_entries(self):
        identifiers = {self.table.item(index.row(), 0).data(Qt.UserRole) for index in self.table.selectionModel().selectedRows()}
        return [entry for entry in self.entries if entry["id"] in identifiers]

    def filter_rows(self, *args):
        selected = {entry["id"] for entry in self.selected_entries()}
        query = "".join(self.search.text().split()).casefold()
        state = self.state_filter.currentData()
        self.table.setRowCount(0)
        for entry in self.entries:
            text = "".join(f"{entry['name']} {entry['texture_id']} {entry['id']}".split()).casefold()
            if query not in text or (state and entry["state"] != state):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [entry["name"], entry["texture_id"] or "未知", entry["status"],
                      display_time(entry["created_at"], entry["time_estimated"]),
                      display_time(entry["modified_at"], entry["time_estimated"]),
                      f"{entry['backup_bytes'] / 1024 / 1024:.2f} MB"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(entry["reason"])
                if column == 0:
                    item.setData(Qt.UserRole, entry["id"])
                if column == 2:
                    item.setForeground(QColor("#237449" if entry["restorable"] or entry["state"] == "restored" else "#a15b00"))
                self.table.setItem(row, column, item)
            if entry["id"] in selected:
                # Select whole rows without clearing earlier selections.
                from PySide6.QtCore import QItemSelectionModel
                self.table.selectionModel().select(self.table.model().index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        counts = Counter(entry["state"] for entry in self.entries)
        size = sum(entry["backup_bytes"] for entry in self.entries) / 1024 / 1024
        self.summary.setText(f"共 {len(self.entries)} 项 · 可恢复 {counts['modified']} · 已恢复 {counts['restored']} · 需检查 {len(self.entries) - counts['modified'] - counts['restored']} · 备份 {size:.2f} MB · 当前显示 {self.table.rowCount()} 项")
        if not self.entries:
            self.details.setPlainText("尚无备份记录。首次应用卡图替换后，记录会出现在这里。")
        self.selection_changed()

    def selection_changed(self):
        entries = self.selected_entries()
        if len(entries) == 1:
            entry = entries[0]
            self.details.setPlainText(f"{entry['name']}\n状态：{entry['status']}\n{entry['reason']}\n缓存标识：{entry['id']}\n备份目录：{entry['backup_path']}\n时间带“约”表示至少一项取自旧文件修改时间，不是精确操作历史。")
        elif entries:
            self.details.setPlainText(f"已选择 {len(entries)} 项，其中 {sum(x['restorable'] for x in entries)} 项可恢复。恢复选中项要求每一项均通过检查；可使用状态筛选缩小范围。")
        elif self.entries:
            self.details.setPlainText("选择一项查看检查原因；按住 Ctrl / Shift 可多选。不会自动删除过时或异常备份。")
        self.update_controls()

    def update_controls(self):
        selected = self.selected_entries()
        for control in (self.search, self.state_filter, self.refresh_button, self.table, self.close_button):
            control.setEnabled(not self.busy)
        self.restore_selected_button.setEnabled(not self.busy and bool(selected) and all(x["restorable"] for x in selected))
        self.restore_all_button.setEnabled(not self.busy and any(x["restorable"] for x in self.entries))
        self.locate_button.setEnabled(not self.busy and len(selected) == 1 and selected[0]["texture_id"] in self.editor.by_texture)
        self.folder_button.setEnabled(not self.busy and (self.manager.data_dir / "backups").is_dir())

    def run(self, function, callback, message):
        if self.busy:
            return
        self.busy = True
        self.update_controls()
        self.status.setText(message)
        job = Work(function)
        self.jobs.add(job)
        def finish(result, failed=False):
            self.busy = False
            self.jobs.discard(job)
            try:
                if failed:
                    self.error(result)
                else:
                    callback(result)
            except Exception as exc:
                self.error(str(exc))
            self.update_controls()
        job.signals.success.connect(lambda result: finish(result))
        job.signals.failure.connect(lambda message: finish(message, True))
        self.pool.start(job)

    def refresh(self):
        def complete(entries):
            self.entries = entries
            self.filter_rows()
            self.status.setText("检查完成。旧索引可能过时；游戏更新后请先关闭此页并刷新本地索引，再重新检查。")
        self.run(lambda: scan_backups(self.manager, self.cards), complete, "正在后台核对备份与当前缓存指纹…")

    def confirm(self, text):
        return QMessageBox.question(self, "确认恢复", text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def restore_selected(self):
        self.restore(self.selected_entries(), "选中的")

    def restore_all_safe(self):
        self.restore([entry for entry in self.entries if entry["restorable"]], "全部可恢复的（不受搜索和筛选影响）")

    def restore(self, entries, scope):
        if self.busy or not entries or not all(x["restorable"] for x in entries):
            return
        warning = "\n当前没有本地索引，仅按文件指纹核对。" if not self.cards else ""
        if not self.confirm(f"请确认游戏已完全关闭。\n将恢复{scope} {len(entries)} 项到首次备份状态。\n异常项目不会写入，备份不会删除。{warning}\n继续？"):
            return
        def operation():
            result = restore_entries(self.manager, self.cards, entries)
            return result, scan_backups(self.manager, self.cards)
        def complete(result):
            (restored, errors), self.entries = result
            self.changed = True
            self.filter_rows()
            self.status.setText(f"恢复完成：成功 {restored} 项，跳过 / 失败 {len(errors)} 项；首次备份保留。")
            if errors:
                QMessageBox.warning(self, "部分项目未恢复", "\n".join(errors))
        self.run(operation, complete, "正在复检并恢复已确认项目…")

    def locate(self):
        selected = self.selected_entries()
        if len(selected) != 1:
            return
        if self.editor.imported is not None and not self.editor.confirm("查看管理记录将放弃尚未应用的图片预览。继续？"):
            return
        ident = selected[0]["texture_id"]
        self.accept()
        self.editor.cached.setChecked(False)
        self.editor.search.setText(ident)
        self.editor.filter_cards()
        for row in range(self.editor.list.count()):
            if self.editor.list.item(row).data(Qt.UserRole) == ident:
                self.editor.list.setCurrentRow(row)
                break

    def open_folder(self):
        path = (self.manager.data_dir / "backups").resolve()
        if path.is_dir() and path.is_relative_to(self.manager.data_dir.resolve()):
            try:
                os.startfile(str(path))
            except OSError as exc:
                self.error(str(exc))

    def error(self, message):
        self.status.setText(message)
        QMessageBox.warning(self, "未完成操作", message)

    def done(self, result):
        if self.busy:
            self.status.setText("正在检查或恢复，请等待操作完成后关闭。")
            return
        super().done(result)

    def closeEvent(self, event):
        if self.busy:
            self.status.setText("正在检查或恢复，请等待操作完成后关闭。")
            event.ignore()
        else:
            super().closeEvent(event)
