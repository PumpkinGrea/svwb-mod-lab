"""Card voice browser, local playback and explicit guarded modifications."""
import json
from pathlib import Path
import tempfile

from PySide6.QtCore import Qt, QThreadPool, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QComboBox, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QSplitter, QWidget, QTextBrowser)

from .audio import (VoiceManager, voice_catalog, wem_info, decode_wem,
                    convert_audio_file, MAX_WEM, IMPORT_FORMATS)
from .core import sha, ModError
from .jobs import Work


class VoiceDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('卡牌语音 · 试听与替换')
        self.resize(1180, 800)
        self.manager = VoiceManager(parent.manager)
        self.cards, self.visible, self.clips = [], [], []
        self.card = None
        self.fingerprint = None
        self.imported = None
        self.busy = False
        self.jobs = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.temporary = tempfile.TemporaryDirectory(prefix='svwb-listen-', ignore_cleanup_errors=True)
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.output.setVolume(0.7)
        self.player.errorOccurred.connect(lambda *args: self.status.setText('试听失败：' + self.player.errorString()))
        layout = QVBoxLayout(self)
        note = QLabel('从本地清单读取卡牌与语音。仅修改所选媒体，保持其他语音与事件不变。应用和恢复前请关闭游戏。')
        note.setWordWrap(True)
        layout.addWidget(note)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索中文名 / 卡牌 ID（包含未缓存卡图的卡牌）')
        if parent.selected and parent.selected['card_ids']:
            self.search.setText(str(parent.selected['card_ids'][0]))
        self.languages = QComboBox()
        self.languages.addItem('全部语言', '')
        self.refresh = QPushButton('刷新本地语音')
        filters.addWidget(self.search, 1); filters.addWidget(self.languages); filters.addWidget(self.refresh)
        layout.addLayout(filters)
        split = QSplitter()
        self.card_list, self.clip_list = QListWidget(), QListWidget()
        split.addWidget(self.card_list); split.addWidget(self.clip_list)
        split.setSizes([460, 650]); layout.addWidget(split, 1)
        self.details = QLabel('正在读取本地语音目录…')
        self.details.setWordWrap(True); layout.addWidget(self.details)
        buttons = QHBoxLayout()
        self.original = QPushButton('试听原音')
        self.current = QPushButton('试听当前语音')
        self.stop = QPushButton('停止试听')
        self.export = QPushButton('导出原 WEM')
        self.import_button = QPushButton('导入替换音频')
        self.listen_import = QPushButton('试听待替换')
        for button in (self.original,self.current,self.stop,self.export,self.import_button,self.listen_import):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.source_label = QLabel('可导入 WAV、MP3、FLAC、OGG 或 WEM；常见格式会自动转换为 Wwise Vorbis。')
        self.source_label.setWordWrap(True); layout.addWidget(self.source_label)
        actions = QHBoxLayout()
        self.apply_button = QPushButton('备份并替换选中语音')
        self.restore_button = QPushButton('恢复选中语音')
        self.restore_pack_button = QPushButton('恢复当前语音包')
        self.manage_button = QPushButton('语音记录与恢复管理')
        for button in (self.apply_button,self.restore_button,self.restore_pack_button,self.manage_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.status = QLabel('读取中…'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.controls = [self.search,self.languages,self.refresh,self.card_list,self.clip_list,
                         self.original,self.current,self.export,self.import_button,self.listen_import,
                         self.apply_button,self.restore_button,self.restore_pack_button,self.manage_button]
        self.search.textChanged.connect(self.filter_cards)
        self.languages.currentIndexChanged.connect(self.filter_cards)
        self.refresh.clicked.connect(self.load_catalog)
        self.card_list.currentRowChanged.connect(self.select_card)
        self.clip_list.currentRowChanged.connect(self.select_clip)
        self.original.clicked.connect(lambda: self.play_clip(True))
        self.current.clicked.connect(lambda: self.play_clip(False))
        self.stop.clicked.connect(self.player.stop)
        self.export.clicked.connect(self.export_original)
        self.import_button.clicked.connect(self.import_audio)
        self.listen_import.clicked.connect(self.play_import)
        self.apply_button.clicked.connect(self.apply)
        self.restore_button.clicked.connect(self.restore_clip)
        self.restore_pack_button.clicked.connect(self.restore_pack)
        self.manage_button.clicked.connect(self.manage)
        self.load_catalog()

    def job(self, function, callback, message):
        if self.busy:
            return
        self.player.stop()
        self.busy = True; self.status.setText(message); self.enabled()
        work = Work(function); self.jobs.add(work)
        def finish(result, failed=False):
            self.busy = False; self.jobs.discard(work)
            try:
                if failed: self.error(result)
                else: callback(result)
            except Exception as exc: self.error(str(exc))
            self.enabled()
        work.signals.success.connect(lambda value: finish(value))
        work.signals.failure.connect(lambda value: finish(value, True))
        self.pool.start(work)

    def enabled(self):
        for control in self.controls: control.setEnabled(not self.busy)
        ready = not self.busy and self.clip() is not None
        for control in (self.original,self.current,self.export,self.import_button,self.restore_button):
            control.setEnabled(ready)
        self.listen_import.setEnabled(ready and self.imported is not None)
        self.apply_button.setEnabled(ready and self.imported is not None)
        self.restore_pack_button.setEnabled(not self.busy and self.card is not None and self.fingerprint is not None)

    def error(self, message):
        self.status.setText(str(message)); QMessageBox.warning(self,'语音操作未完成',str(message))

    def confirm(self, text):
        return QMessageBox.question(self,'确认语音文件修改',text,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes

    def load_catalog(self):
        def loaded(cards):
            self.cards = cards
            self.languages.blockSignals(True); self.languages.clear(); self.languages.addItem('全部语言','')
            for language in sorted({c['language'] for c in cards}): self.languages.addItem(language,language)
            self.languages.blockSignals(False); self.filter_cards()
            self.status.setText(f'已读取 {len(cards)} 条卡牌/语言记录；未缓存语音会标注。')
        self.job(lambda: voice_catalog(self.manager),loaded,'正在只读解析本地清单和语音主数据…')

    def filter_cards(self, *args):
        if self.busy: return
        self.player.stop(); self.card_list.clear(); self.visible=[]
        query=''.join(self.search.text().split()).casefold(); language=self.languages.currentData()
        for card in self.cards:
            if language and card['language']!=language: continue
            if query and query not in ''.join(f"{card['name']} {card['card_id']}".split()).casefold(): continue
            cached=self.manager.target(card['asset']).is_file()
            self.visible.append(card)
            self.card_list.addItem(f"{card['name']} · {card['card_id']}\n{card['language']} · {'已缓存' if cached else '未缓存'}")
        self.select_card(-1)

    def select_card(self, row):
        self.player.stop(); self.clips=[]; self.clip_list.clear(); self.imported=None; self.card=None; self.fingerprint=None
        self.source_label.setText('可导入 WAV、MP3、FLAC、OGG 或 WEM；常见格式会自动转换为 Wwise Vorbis。')
        if row<0 or row>=len(self.visible): self.enabled(); return
        self.card=self.visible[row]
        self.reload()

    def reload(self):
        card=self.card
        def loaded(result):
            self.clips,self.fingerprint=result
            self.clip_list.clear()
            for clip in self.clips:
                item=QListWidgetItem(f"{clip['label']} · {clip['seconds']:.2f} 秒 · {'已替换' if clip['changed'] else '原音'}\n{clip['name']} · 媒体 {clip['media_id']}")
                self.clip_list.addItem(item)
            self.details.setText(f"{card['name']} · {card['language']} · {len(self.clips)} 条事件/媒体。相同媒体编号代表同一音频，替换会同时影响关联事件和共用该包的卡牌。")
            self.imported=None; self.source_label.setText('可导入 WAV、MP3、FLAC、OGG 或 WEM；常见格式会自动转换为 Wwise Vorbis。')
            self.status.setText('语音已刷新；选中一条试听或替换。')
        self.job(lambda:self.manager.clips(card),loaded,'正在解析声音库和事件关联…')

    def clip(self):
        row=self.clip_list.currentRow()
        return self.clips[row] if 0<=row<len(self.clips) else None

    def select_clip(self, *args):
        self.player.stop(); self.imported=None; self.source_label.setText('可导入 WAV、MP3、FLAC、OGG 或 WEM；常见格式会自动转换为 Wwise Vorbis。'); self.enabled()

    def play_bytes(self, data):
        destination=Path(self.temporary.name)/(sha(data)+'.wav')
        def decoded(path):
            self.player.setSource(QUrl.fromLocalFile(str(path)));self.player.play();self.status.setText('正在试听…')
        self.job(lambda:decode_wem(data,destination),decoded,'正在解码语音…')

    def play_clip(self, original):
        clip=self.clip()
        if not clip:return
        try:
            current,baseline,fingerprint,_=self.manager.read_package(self.card['asset'])
            if fingerprint!=self.fingerprint:raise ModError('语音包已变化，请重新选择卡牌。')
            self.play_bytes((baseline if original else current).media(clip['media_id']))
        except Exception as exc:self.error(str(exc))

    def export_original(self):
        clip=self.clip()
        if not clip:return
        path,_=QFileDialog.getSaveFileName(self,'导出原始 WEM',f"{clip['name']}--{clip['media_id']}.wem",'Wwise 音频 (*.wem)')
        if not path:return
        try:
            data=self.manager.read_package(self.card['asset'])[1].media(clip['media_id'])
            from .core import atomic_write
            atomic_write(path,data);self.status.setText('已导出原始 WEM；游戏文件未修改。')
        except Exception as exc:self.error(str(exc))

    def import_audio(self):
        path,_=QFileDialog.getOpenFileName(self,'选择替换音频','','音频 (*.wav *.mp3 *.flac *.ogg *.wem);;所有文件 (*.*)')
        if not path:return
        clip=self.clip()
        if not clip:return
        try:
            source=Path(path)
            original=self.manager.read_package(self.card['asset'])[1].media(clip['media_id']);old=wem_info(original)
            if old['channels']==1 and source.suffix.lower() in IMPORT_FORMATS:
                QMessageBox.information(self,'单声道原音','当前原音是单声道。此编码器的游戏兼容配置为双声道，导入时会将单声道复制到左右声道；采样率会匹配原音。')
            self.imported=None
            self.source_label.setText('正在转换并校验所选音频…')
            def prepare():
                if source.suffix.lower()=='.wem':
                    if source.stat().st_size>MAX_WEM:raise ModError('WEM 文件超过 32 MB。')
                    data=source.read_bytes();info=wem_info(data)
                else:
                    data,info=convert_audio_file(source,old)
                channels_match=(old['channels']==info['channels'] or old['channels']==1 and info['channels']==2)
                if info['codec']!=old['codec'] or info['rate']!=old['rate'] or not channels_match:
                    raise ModError(f"编码后需要 Vorbis、{old['rate']} Hz；允许 {old['channels']} 声道原音保持声道数，或单声道转双声道。")
                dest=Path(self.temporary.name)/(sha(data)+'.wav')
                decode_wem(data,dest)
                return data,info
            def loaded(result):
                data,info=result
                self.imported=(data,str(source));self.source_label.setText(f"待替换：{source.name} · {info['seconds']:.2f} 秒 · {info['rate']} Hz · {info['channels']} 声道");self.status.setText('导入校验通过，可试听或应用。')
            self.job(prepare,loaded,'正在解码并转换音频，随后校验 WEM…')
        except Exception as exc:self.error(str(exc))

    def play_import(self):
        if self.imported:self.play_bytes(self.imported[0])

    def apply(self):
        clip=self.clip()
        if not clip or not self.imported:return
        if not self.confirm('请关闭游戏。首次操作将把当前本地语音包保存为恢复基准；无法保证该文件未被其他工具修改。\n替换会影响所有引用此媒体的事件及卡牌。备份将永久保留。继续？'):return
        card,media,expected=self.card,clip['media_id'],self.fingerprint
        data,path=self.imported
        self.job(lambda:self.manager.apply_clip(card,media,data,expected,path),lambda _:self.reload(),'正在备份、重打包并校验语音…')

    def restore_clip(self):
        clip=self.clip()
        if not clip:return
        if not self.confirm('关闭游戏后，仅恢复该媒体，保留同包其他媒体的替换。共用此媒体的事件会一起恢复。继续？'):return
        card,media,expected=self.card,clip['media_id'],self.fingerprint
        self.job(lambda:self.manager.restore_clip(card,media,expected),lambda _:self.reload(),'正在恢复选中语音…')

    def restore_pack(self):
        if not self.card:return
        if not self.confirm('恢复当前整包的首次备份，会恢复该包内所有卡牌/事件的语音替换。继续？'):return
        try:
            rows=[r for r in self.manager.inventory(self.cards) if r['id']==self.card['asset']['hash'] and r['restorable']]
            if not rows:raise ModError('没有可恢复的包，请查看记录管理。')
            def done(result):
                if result[1]:raise ModError('；'.join(result[1]))
                self.reload()
            self.job(lambda:self.manager.restore_packs(self.cards,rows),done,'正在校验并恢复整包…')
        except Exception as exc:self.error(str(exc))

    def manage(self):
        dialog=VoiceManagement(self);dialog.exec();dialog.deleteLater()
        if self.card:self.reload()

    def closeEvent(self,event):
        if self.busy:
            QMessageBox.information(self,'正在处理','请等待当前操作完成后关闭。');event.ignore();return
        self.release_player();super().closeEvent(event)

    def release_player(self):
        if self.player is not None:
            self.player.stop();self.player.setSource(QUrl())
            from shiboken6 import delete
            delete(self.player);self.player=None
        self.temporary.cleanup()

    def reject(self):
        if self.busy:return
        self.release_player();super().reject()


class VoiceManagement(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner=owner;self.rows=[];self.busy=False
        self.setWindowTitle('语音替换记录与恢复');self.resize(960,680)
        layout=QVBoxLayout(self)
        self.search=QLineEdit();self.search.setPlaceholderText('筛选卡名 / 语言 / 文件标识')
        layout.addWidget(self.search)
        self.list=QListWidget();self.list.setSelectionMode(QListWidget.ExtendedSelection);layout.addWidget(self.list,1)
        self.history=QTextBrowser();layout.addWidget(self.history,1)
        bar=QHBoxLayout();self.refresh=QPushButton('刷新记录');self.restore=QPushButton('恢复选中语音包');self.all=QPushButton('恢复全部可恢复语音包')
        for b in (self.refresh,self.restore,self.all):bar.addWidget(b)
        layout.addLayout(bar);self.message=QLabel();self.message.setWordWrap(True);layout.addWidget(self.message)
        self.search.textChanged.connect(self.filter);self.refresh.clicked.connect(self.load)
        self.list.currentRowChanged.connect(self.show_history)
        self.restore.clicked.connect(lambda:self.restore_rows(False));self.all.clicked.connect(lambda:self.restore_rows(True))
        self.load()

    def load(self):
        try:self.rows=self.owner.manager.inventory(self.owner.cards);self.filter()
        except Exception as exc:self.owner.error(str(exc))

    def filter(self,*args):
        self.list.clear();query=self.search.text().casefold()
        for i,row in enumerate(self.rows):
            label=f"{row['name']} · {row['status']}\n{row['id']} · {row.get('modified_at') or '未知时间'}"
            if query and query not in label.casefold():continue
            item=QListWidgetItem(label);item.setData(Qt.UserRole,i);item.setToolTip(row['reason']);self.list.addItem(item)
        self.message.setText(f'共 {len(self.rows)} 包，{sum(r["restorable"] for r in self.rows)} 包可恢复。全部恢复不受筛选影响。')

    def show_history(self,*args):
        item=self.list.currentItem();self.history.clear()
        if not item:return
        row=self.rows[item.data(Qt.UserRole)]
        try:
            asset=row.get('asset')
            record=self.owner.manager.metadata(asset) if asset else {}
            self.history.setPlainText(row['reason']+'\n\n'+json.dumps((record or {}).get('history',[]),ensure_ascii=False,indent=2))
        except Exception as exc:self.history.setPlainText(str(exc))

    def restore_rows(self,all_rows):
        rows=[r for r in self.rows if r['restorable']] if all_rows else [self.rows[i.data(Qt.UserRole)] for i in self.list.selectedItems() if self.rows[i.data(Qt.UserRole)]['restorable']]
        if not rows:return
        if not self.owner.confirm(f'关闭游戏后，恢复 {len(rows)} 个完整语音包。包内全部替换会恢复。继续？'):return
        self.busy=True
        for c in (self.search,self.list,self.refresh,self.restore,self.all):c.setEnabled(False)
        def done(result):
            self.busy=False
            for c in (self.search,self.list,self.refresh,self.restore,self.all):c.setEnabled(True)
            self.load();self.message.setText(f'已恢复 {result[0]} 包；失败/跳过 {len(result[1])} 包。'+'；'.join(result[1]))
        def operation():
            try:return self.owner.manager.restore_packs(self.owner.cards,rows)
            except Exception as exc:return 0,[str(exc)]
        self.owner.job(operation,done,'正在恢复语音包…')

    def reject(self):
        if not self.busy:super().reject()

    def closeEvent(self,event):
        if self.busy:event.ignore()
        else:super().closeEvent(event)
