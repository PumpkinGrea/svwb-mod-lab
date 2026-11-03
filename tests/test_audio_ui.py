import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest
from modtool.audio import Package
from modtool.audio_ui import VoiceDialog, VoiceManagement
from modtool.core import ModManager

ROOT=Path(__file__).resolve().parents[1]
SAMPLE=ROOT/'audio-export/dx_10974110-jp/dx_10974110.pck'

@unittest.skipUnless(SAMPLE.exists(),'Requires local audio fixture')
class VoiceGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def wait(self,dialog):
        deadline=time.monotonic()+15
        while dialog.busy and time.monotonic()<deadline:QTest.qWait(25)
        self.assertFalse(dialog.busy)

    def test_catalog_select_preview_and_management(self):
        with tempfile.TemporaryDirectory() as temporary:
            game=Path(temporary);(game/'ShadowverseWB.exe').touch()
            (game/'ShadowverseWB_Data/Persistent/dat').mkdir(parents=True)
            parent=QWidget();parent.manager=ModManager(game,b'');parent.selected={'card_ids':[10974110]}
            raw=SAMPLE.read_bytes()
            asset={'hash':'VOICEGUITEST12345','key':0,'size':len(raw),'name':'sound/Windows/d/Japanese(JP)/dx_10974110.pck'}
            target=parent.manager.target(asset);target.parent.mkdir(parents=True);target.write_bytes(raw)
            card={'card_id':10974110,'name':'测试卡牌','language':'Japanese(JP)','asset':asset,
                  'events':[{'name':'Play_dx_10974110_1','event_id':572566656,'label':'登场'}]}
            with patch('modtool.audio_ui.voice_catalog',return_value=[card]):
                dialog=VoiceDialog(parent)
                try:
                    self.wait(dialog);self.assertEqual(dialog.card_list.count(),1)
                    dialog.card_list.setCurrentRow(0);self.wait(dialog)
                    self.assertEqual(dialog.clip_list.count(),1)
                    dialog.clip_list.setCurrentRow(0)
                    self.assertTrue(dialog.original.isEnabled())
                    self.assertFalse(dialog.apply_button.isEnabled())
                    dialog.play_clip(True);self.wait(dialog)
                    self.assertFalse(dialog.player.source().isEmpty())
                    dialog.player.stop()
                    management=VoiceManagement(dialog)
                    self.assertEqual(management.list.count(),0)
                    management.close()
                    dialog.search.setText('no matches')
                    self.assertEqual(dialog.card_list.count(),0)
                    self.assertFalse(dialog.original.isEnabled())
                finally:
                    self.wait(dialog);dialog.close();parent.close()
