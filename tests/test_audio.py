"""Real copied audio fixtures; tests never write to the installed game."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modtool.audio import (Package, VoiceManager, event_hash, wem_info, decode_wem,
                           convert_audio_file)
from modtool.core import ModManager, ModError, sha

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / 'audio-export/dx_10974110-jp/dx_10974110.pck'


class EventTests(unittest.TestCase):
    def test_known_wwise_event_id(self):
        self.assertEqual(event_hash('Play_dx_10974110_1'), 572566656)

    def test_invalid_package_and_fake_wem(self):
        for data in (b'', b'AKPK'+b'\0'*100, b'RIFF'+b'\0'*20):
            with self.assertRaises(ModError): Package(data)
            with self.assertRaises(ModError): wem_info(data)


@unittest.skipUnless(SAMPLE.is_file(), 'Requires ignored local audio sample')
class AudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='svwb-audio-test-')
        self.addCleanup(self.temp.cleanup)
        game = Path(self.temp.name)
        (game / 'ShadowverseWB.exe').touch()
        (game / 'ShadowverseWB_Data/Persistent/dat').mkdir(parents=True)
        self.manager = VoiceManager(ModManager(game, b''))
        live = patch.object(self.manager, 'verify_live_asset')
        self.live = live.start()
        self.addCleanup(live.stop)
        self.data = SAMPLE.read_bytes()
        self.asset = {'hash':'VOICEPACKTEST12345', 'key':0, 'size':len(self.data),
                      'name':'sound/Windows/d/Japanese(JP)/dx_10974110.pck'}
        self.card = {'name':'测试卡牌', 'card_id':10974110, 'language':'Japanese(JP)',
            'asset':self.asset, 'events':[{'name':'Play_dx_10974110_1',
                'event_id':572566656, 'label':'登场'}]}
        target=self.manager.target(self.asset);target.parent.mkdir(parents=True);target.write_bytes(self.data)
        for name in ('modtool.core.require_game_closed','modtool.audio.require_game_closed'):
            p=patch(name);p.start();self.addCleanup(p.stop)
        self.pack=Package(self.data)
        self.media=[e['id'] for e in self.pack.entries if e['kind']=='media']

    def test_repack_preserves_banks_and_other_media_and_decodes(self):
        a,b=self.media[:2]
        rebuilt=Package(self.pack.replace({a:self.pack.media(b)}))
        for entry in self.pack.entries:
            other=next(e for e in rebuilt.entries if (e['kind'],e['id'])==(entry['kind'],entry['id']))
            expected=self.pack.media(b) if entry['kind']=='media' and entry['id']==a else self.pack.content(entry)
            self.assertEqual(rebuilt.content(other),expected)
        output=Path(self.temp.name)/'decoded.wav'
        decode_wem(rebuilt.media(a),output)
        self.assertGreater(output.stat().st_size,100)
        self.assertEqual(rebuilt.event_media(),self.pack.event_media())

    def test_common_audio_import_converts_and_roundtrips(self):
        clip=self.manager.clips(self.card)[0][0]
        media_id=clip['media_id']
        source_wem=self.pack.media(media_id)
        source_path=Path(self.temp.name)/'source.wav'
        decode_wem(source_wem,source_path)
        original_info=wem_info(source_wem)
        converted,info=convert_audio_file(source_path,original_info)
        self.assertEqual((info['codec'],info['rate'],info['channels']),
                         (original_info['codec'],original_info['rate'],2))
        self.manager.apply_clip(self.card,media_id,converted,self.manager.clips(self.card)[1],str(source_path))
        rebuilt=Package(self.manager.target(self.asset).read_bytes())
        self.assertEqual(wem_info(rebuilt.media(media_id)),info)
        output=Path(self.temp.name)/'converted.wav'
        decode_wem(rebuilt.media(media_id),output)
        self.assertGreater(output.stat().st_size,100)

    def test_apply_partial_restore_preserves_other_replacement(self):
        mapping=self.pack.event_media();events=[]
        for event_id,media in mapping.items():
            events.append({'name':str(event_id),'event_id':event_id,'label':'测试'})
        self.card['events']=events
        a,b,c=self.media[:3]
        expected=self.manager.clips(self.card)[1]
        self.manager.apply_clip(self.card,a,self.pack.media(c),expected,'a.wem')
        expected=self.manager.clips(self.card)[1]
        self.manager.apply_clip(self.card,b,self.pack.media(c),expected,'b.wem')
        expected=self.manager.clips(self.card)[1]
        self.manager.restore_clip(self.card,a,expected)
        now=Package(self.manager.target(self.asset).read_bytes())
        self.assertEqual(now.media(a),self.pack.media(a))
        self.assertEqual(now.media(b),self.pack.media(c))
        self.assertEqual(self.manager.backup_bytes(self.asset,self.manager.metadata(self.asset)),self.data)
        expected=self.manager.clips(self.card)[1]
        self.manager.restore_clip(self.card,b,expected)
        self.assertEqual(self.manager.target(self.asset).read_bytes(),self.data)
        history=self.manager.metadata(self.asset)['history']
        self.assertEqual([h['action'] for h in history],['replace','replace','restore_clip','restore_clip'])

    def test_stale_preview_and_external_changes_refused(self):
        media=self.manager.clips(self.card)[0][0]['media_id']
        with self.assertRaises(ModError):
            self.manager.apply_clip(self.card,media,self.pack.media(self.media[0]),'0'*64,'x.wem')
        self.assertFalse(self.manager.backup_dir(self.asset).exists())
        self.manager.apply_clip(self.card,media,self.pack.media(self.media[0]),sha(self.data),'x.wem')
        self.manager.target(self.asset).write_bytes(b'external update')
        with self.assertRaises(ModError):self.manager.read_package(self.asset)
        with self.assertRaises(ModError):self.manager.restore(self.asset)
        self.assertFalse(self.manager.inventory([self.card])[0]['restorable'])

    def test_pack_restore_and_outdated_index(self):
        media=self.manager.clips(self.card)[0][0]['media_id']
        self.manager.apply_clip(self.card,media,self.pack.media(self.media[0]),sha(self.data),'x.wem')
        rows=self.manager.inventory([self.card])
        self.assertTrue(rows[0]['restorable'])
        changed=dict(self.card,asset=dict(self.asset,hash='NEWVOICEPACK12345'))
        self.assertFalse(self.manager.inventory([changed])[0]['restorable'])
        self.assertEqual(self.manager.restore_packs([self.card],rows),(1,[]))
        self.assertEqual(self.manager.target(self.asset).read_bytes(),self.data)

    def test_update_after_preview_refuses_write(self):
        self.live.side_effect = ModError('游戏清单已更新')
        with self.assertRaises(ModError):
            self.manager.apply_clip(self.card,308972096,self.pack.media(self.media[0]),sha(self.data),'x.wem')
        self.assertEqual(self.manager.target(self.asset).read_bytes(),self.data)
        self.assertFalse(self.manager.backup_dir(self.asset).exists())


if __name__ == '__main__':unittest.main()
