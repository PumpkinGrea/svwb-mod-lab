"""Offline Wwise PCK media edits. Bank/event structure is preserved unchanged."""
from collections import defaultdict
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import wave

from .core import ModError, ModManager, atomic_write, sha, write_json, require_game_closed
from .formats import parse_master
from .localmeta import LocalReader
from .management import scan_backups

MAX_PACK = 128 * 1024 * 1024
MAX_WEM = 32 * 1024 * 1024
MAX_SOURCE_AUDIO = 128 * 1024 * 1024
WEM_ENCODER_VERSION = '2013.2'
IMPORT_FORMATS = {'.wav', '.mp3', '.flac', '.ogg'}
SLOTS = {39: '登场/联动', 41: '攻击', 42: '进化后攻击', 43: '进化',
         45: '退场', 46: '进化后退场', 47: '衍生物退场', 48: '效果',
         49: '进化后效果', 50: '启动'}


def event_hash(name):
    value = 2166136261
    for byte in name.lower().encode('utf-8'):
        value = ((value * 16777619) ^ byte) & 0xffffffff
    return value


def u32(data, offset):
    if offset < 0 or offset + 4 > len(data):
        raise ModError('音频结构越界，未继续处理。')
    return struct.unpack_from('<I', data, offset)[0]


def wem_info(data):
    if len(data) > MAX_WEM or data[:4] != b'RIFF' or data[8:12] != b'WAVE' or u32(data, 4) + 8 != len(data):
        raise ModError('不是完整的 Wwise WEM 文件；WAV/MP3/OGG 不能改后缀使用。')
    chunks, at = {}, 12
    # Wwise RIFF chunks may be packed without standard RIFF padding.
    while at < len(data):
        if at + 8 > len(data):
            raise ModError('WEM 块头不完整。')
        tag, size = data[at:at+4], u32(data, at+4)
        if tag in chunks or at + 8 + size > len(data):
            raise ModError('WEM 块重复或越界。')
        chunks[tag] = data[at+8:at+8+size]
        at += 8 + size
    fmt = chunks.get(b'fmt ', b'')
    if len(fmt) < 24 or b'data' not in chunks or len(chunks[b'data']) < 8:
        raise ModError('WEM 缺少有效格式或音频块。')
    codec, channels, rate = struct.unpack_from('<HHI', fmt)
    if codec != 0xffff or channels not in (1, 2) or not 8000 <= rate <= 192000:
        raise ModError('仅支持 Wwise Vorbis WEM，且声道数或采样率无效。')
    samples = u32(fmt, 24) if len(fmt) >= 28 else 0
    if not samples or samples / rate > 120:
        raise ModError('语音长度无效或超过 120 秒。')
    return {'codec': codec, 'channels': channels, 'rate': rate, 'samples': samples, 'seconds': samples / rate}


class Package:
    def __init__(self, data):
        if len(data) < 28 or len(data) > MAX_PACK or data[:4] != b'AKPK':
            raise ModError('不是支持的 Wwise PCK。')
        header, endian, langs, banks, media, externals = struct.unpack_from('<6I', data, 4)
        if endian != 1 or header + 8 > len(data) or 28 + langs + banks + media + externals != header + 8:
            raise ModError('PCK 头结构不受支持。')
        self.data, self.header_end, self.entries = data, header + 8, []
        at = 28 + langs
        for kind, length in [('bank', banks), ('media', media), ('external', externals)]:
            count = u32(data, at)
            if length != 4 + count * 20:
                raise ModError('PCK 索引格式不受支持。')
            for i in range(count):
                pos = at + 4 + i * 20
                ident, block, size, offset, language = struct.unpack_from('<5I', data, pos)
                start = block * offset
                if not block or start < self.header_end or start + size > len(data) or not size:
                    raise ModError('PCK 资源范围无效。')
                self.entries.append({'kind': kind, 'id': ident, 'block': block, 'size': size,
                                     'start': start, 'language': language, 'pos': pos})
            at += length
        ordered = sorted(self.entries, key=lambda e: e['start'])
        if any(a['start'] + a['size'] > b['start'] for a, b in zip(ordered, ordered[1:])):
            raise ModError('PCK 包含重叠资源，不支持替换。')
        ids = [e['id'] for e in self.entries if e['kind'] == 'media']
        if len(ids) != len(set(ids)):
            raise ModError('语音包包含多语言重复媒体编号，未猜测替换目标。')

    def content(self, entry):
        return self.data[entry['start']:entry['start'] + entry['size']]

    def media(self, ident):
        matches = [e for e in self.entries if e['kind'] == 'media' and e['id'] == ident]
        if len(matches) != 1:
            raise ModError('媒体编号不存在或不唯一。')
        return self.content(matches[0])

    def replace(self, replacements):
        if not replacements or not set(replacements).issubset({e['id'] for e in self.entries if e['kind'] == 'media'}):
            raise ModError('无效的替换媒体集合。')
        result = bytearray(self.data[:self.header_end])
        for entry in sorted(self.entries, key=lambda e: e['start']):
            payload = replacements.get(entry['id'], self.content(entry)) if entry['kind'] == 'media' else self.content(entry)
            alignment = entry['block']
            if alignment > 1024 * 1024:
                raise ModError('不支持的 PCK 对齐大小。')
            result.extend(b'\0' * ((-len(result)) % alignment))
            start = len(result)
            result.extend(payload)
            if len(result) > MAX_PACK:
                raise ModError('重打包超过大小限制。')
            struct.pack_into('<II', result, entry['pos'] + 8, len(payload), start // alignment)
        rebuilt = Package(bytes(result))
        for before, after in zip(self.entries, rebuilt.entries):
            if any(before[k] != after[k] for k in ('kind', 'id', 'block', 'language')):
                raise ModError('重打包改变了资源身份。')
            expected = replacements.get(before['id'], self.content(before)) if before['kind'] == 'media' else self.content(before)
            if rebuilt.content(after) != expected:
                raise ModError('语音重打包回读不一致。')
        return bytes(result)

    def event_media(self):
        sounds, actions, events = {}, {}, {}
        for entry in self.entries:
            if entry['kind'] != 'bank':
                continue
            bank = self.content(entry)
            if bank[:4] != b'BKHD':
                raise ModError('不支持的声音库头。')
            at = 0
            while at < len(bank):
                size = u32(bank, at + 4)
                body = bank[at+8:at+8+size]
                if len(body) != size:
                    raise ModError('声音库块越界。')
                tag = bank[at:at+4]
                at += 8 + size
                if tag == b'BKHD' and u32(body, 0) != 154:
                    raise ModError('声音库版本变化，需更新事件解析器。')
                if tag != b'HIRC':
                    continue
                pos = 4
                for _ in range(u32(body, 0)):
                    if pos + 5 > len(body):
                        raise ModError('HIRC 对象头越界。')
                    kind, length = struct.unpack_from('<BI', body, pos)
                    obj = body[pos+5:pos+5+length]
                    if len(obj) != length or length < 4:
                        raise ModError('HIRC 对象越界。')
                    ident, content = u32(obj, 0), obj[4:]
                    pos += 5 + length
                    if kind == 2 and len(content) >= 9:
                        sounds[ident] = (u32(content, 5), u32(content, 0))
                    elif kind == 3 and len(content) >= 6 and struct.unpack_from('<H', content)[0] == 0x0403:
                        actions[ident] = u32(content, 2)
                    elif kind == 4:
                        count, skip = 0, 0
                        for byte in content[:5]:
                            count = (count << 7) | (byte & 127); skip += 1
                            if not byte & 128:
                                break
                        else:
                            raise ModError('事件列表长度无效。')
                        if skip + count * 4 != len(content):
                            raise ModError('事件列表结构改变。')
                        events[ident] = [u32(content, skip + i*4) for i in range(count)]
                if pos != len(body):
                    raise ModError('声音对象尾部不匹配。')
        result = defaultdict(set)
        for event, action_ids in events.items():
            for action in action_ids:
                sound = sounds.get(actions.get(action))
                if sound:
                    if sound[1] != 0x00040001:
                        raise ModError('声音源不是已验证的 Wwise Vorbis 插件。')
                    result[event].add(sound[0])
        return result


def voice_catalog(manager):
    manifest = LocalReader(manager.game_dir).read(include_audio=True)
    master = manifest['master']
    raw = manager.target(master).read_bytes()
    if len(raw) != master['size']:
        raise ModError('主数据大小不匹配，请等待游戏下载完成。')
    tables = parse_master(raw)
    resources = {r[0]: r for r in tables['CardResourceMaster']}
    texts = {r[0]: r for r in tables['CardText']}
    labels = dict(tables['MasterTextLabel'])
    packs = defaultdict(list)
    for asset in manifest['assets']:
        match = re.fullmatch(r'sound/Windows/d/([^/]+)/(dx_[0-9]+)\.pck', asset['name'])
        if match:
            packs[match[2]].append((match[1], asset))
    result = []
    for card in tables['CardMaster']:
        resource, text = resources.get(card[2]), texts.get(card[4])
        if not resource or len(resource) < 51 or not text:
            continue
        prefix = resource[38]
        if not isinstance(prefix, str):
            continue
        events = []
        for col, label in SLOTS.items():
            if not isinstance(resource[col], str):
                raise ModError('卡牌语音主数据字段变化。')
            for name in resource[col].split(','):
                name = name.strip()
                if name:
                    events.append({'name': name, 'label': label, 'event_id': event_hash(name)})
        for language, asset in packs.get(prefix, []):
            if events:
                result.append({'name': labels.get(text[1], str(card[0])), 'card_id': card[0],
                               'language': language, 'asset': asset, 'events': events, 'prefix': prefix})
    if LocalReader(manager.game_dir).read(include_audio=True) != manifest or manager.target(master).read_bytes() != raw:
        raise ModError('清单在读取时变化，请下载结束后重试。')
    return result


def decoder_path():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    for candidate in (root / 'audio-tools/vgmstream-cli.exe', root / 'tools/vgmstream/vgmstream-cli.exe'):
        if candidate.is_file():
            return candidate
    raise ModError('缺少 vgmstream 解码器，请使用完整程序包。')


def encoder_path():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    for candidate in (root / 'audio-tools/wwise-wem.exe', root / 'tools/wem-encoder/wwise-wem.exe'):
        if candidate.is_file():
            return candidate
    raise ModError('缺少 Wwise Vorbis 编码器，请使用完整程序包。')


def convert_audio_file(source, target_info):
    """Decode a common audio file, resample it, and encode a validated Wwise Vorbis WEM."""
    source = Path(source)
    if source.suffix.lower() not in IMPORT_FORMATS:
        raise ModError('支持 WAV、MP3、FLAC、OGG 和 WEM 文件。')
    if not source.is_file() or source.stat().st_size > MAX_SOURCE_AUDIO:
        raise ModError('音频文件不存在或超过 128 MB。')
    try:
        import miniaudio
        source_info = miniaudio.get_file_info(str(source))
        if source_info.duration <= 0 or source_info.duration > 120:
            raise ModError('音频长度必须大于 0 且不超过 120 秒。')
        # The encoder's installed Wwise profile requires stereo. Mono originals are
        # duplicated into left/right channels; stereo originals retain their layout.
        decoded = miniaudio.decode_file(
            str(source), output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=2, sample_rate=target_info['rate'])
    except ModError:
        raise
    except Exception as exc:
        raise ModError(f'无法解码所选音频：{exc}') from exc
    if decoded.num_frames <= 0 or decoded.num_frames / target_info['rate'] > 120:
        raise ModError('转换后的音频长度无效或超过 120 秒。')

    with tempfile.TemporaryDirectory(prefix='svwb-audio-convert-') as directory:
        wav_path = Path(directory) / 'input.wav'
        wem_path = Path(directory) / 'output.wem'
        with wave.open(str(wav_path), 'wb') as stream:
            stream.setnchannels(2)
            stream.setsampwidth(2)
            stream.setframerate(target_info['rate'])
            stream.writeframes(decoded.samples.tobytes())
        try:
            result = subprocess.run(
                [str(encoder_path()), str(wav_path), '--output', str(wem_path),
                 '--wwise-version', WEM_ENCODER_VERSION],
                capture_output=True, timeout=90,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            raise ModError('Wwise 编码超时，未采用此音频。') from exc
        if result.returncode or not wem_path.is_file():
            detail = (result.stderr or result.stdout).decode('utf-8', errors='replace').strip()
            raise ModError('Wwise 编码失败' + (f'：{detail[-500:]}' if detail else '。'))
        data = wem_path.read_bytes()
        info = wem_info(data)
        if info['channels'] != 2 or info['rate'] != target_info['rate']:
            raise ModError('编码结果与目标采样率或声道数不符。')
        if len(data) > MAX_WEM:
            raise ModError('编码后的 WEM 超过 32 MB。')
        decode_wem(data, Path(directory) / 'roundtrip.wav')
        return data, info


def decode_wem(data, destination):
    wem_info(data)
    with tempfile.TemporaryDirectory(prefix='svwb-voice-') as directory:
        source, output = Path(directory) / 'input.wem', Path(directory) / 'output.wav'
        source.write_bytes(data)
        result = subprocess.run([str(decoder_path()), '-o', str(output), str(source)],
                                capture_output=True, timeout=45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or not output.is_file():
            raise ModError('WEM 无法完整解码，未采用此音频。')
        raw = output.read_bytes()
        with wave.open(io.BytesIO(raw), 'rb') as stream:
            info = wem_info(data)
            if stream.getnchannels() != info['channels'] or stream.getframerate() != info['rate'] or stream.getnframes() != info['samples']:
                raise ModError('WEM 样本计数与解码结果不同。')
        atomic_write(destination, raw)
    return Path(destination)


class VoiceManager(ModManager):
    def __init__(self, manager):
        super().__init__(manager.game_dir, manager.base)
        # Use the same game write.lock, with a separate backup namespace.
        self.voice_root = self.data_dir / 'voice'

    def backup_dir(self, asset):
        self.target(asset)
        root = self.voice_root / 'backups'
        path = root / asset['hash']
        if (self.voice_root.is_symlink() or root.is_symlink()
                or not root.resolve().is_relative_to(self.data_dir.resolve())
                or path.is_symlink() or not path.resolve().is_relative_to(root.resolve())):
            raise ModError('语音备份路径异常。')
        for name in ('record.json', 'original.bin'):
            candidate = path / name
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(path.resolve()):
                raise ModError('语音备份文件路径异常。')
        return path

    def read_package(self, asset):
        target = self.target(asset)
        if not target.is_file() or target.stat().st_size > MAX_PACK:
            raise ModError('语音包未缓存或大小异常，请先在游戏中下载该语言语音。')
        current = target.read_bytes()
        record = self.metadata(asset)
        if record:
            if any(record['asset'].get(k) != asset.get(k) for k in ('name','hash','key','size')):
                raise ModError('语音备份与当前清单不匹配。')
            original = self.backup_bytes(asset, record)
            if sha(current) not in [record['original_sha'], *record['modded_shas']]:
                raise ModError('语音包有外部变更，未覆盖。')
        else:
            original = current
        if len(original) != asset['size'] or asset['key'] != 0:
            raise ModError('语音包大小或加密方式变化，未继续修改。')
        Package(original)
        return Package(current), Package(original), sha(current), record

    def verify_live_asset(self, asset):
        manifest = LocalReader(self.game_dir).read(include_audio=True)
        matches = [a for a in manifest['assets'] if a['name'] == asset['name']]
        if len(matches) != 1 or any(matches[0].get(k) != asset.get(k) for k in ('hash', 'key', 'size')):
            raise ModError('游戏清单已更新，旧语音包不再是当前资源；请刷新语音目录。')

    def clips(self, card):
        current, original, fingerprint, record = self.read_package(card['asset'])
        mapping = current.event_media()
        result = []
        for event in card['events']:
            for media in sorted(mapping.get(event['event_id'], [])):
                info = wem_info(current.media(media))
                related = [e['name'] for e in card['events'] if media in mapping.get(e['event_id'], [])]
                result.append(dict(event, media_id=media, seconds=info['seconds'],
                                   changed=sha(current.media(media)) != sha(original.media(media)),
                                   shared_events=list(dict.fromkeys(related))))
        if not result:
            raise ModError('该卡语音事件未映射到独立媒体；未猜测关联。')
        return result, fingerprint

    def apply_clip(self, card, media_id, replacement, expected_sha, source_name):
        asset = card['asset']
        with self.locked():
            self.verify_live_asset(asset)
            current, original, current_sha, record = self.read_package(asset)
            if current_sha != expected_sha:
                raise ModError('试听后语音包变化，请刷新后重试。')
            if media_id not in {c['media_id'] for c in self.clips(card)[0]}:
                raise ModError('此媒体不属于选中卡牌。')
            old_info, new_info = wem_info(original.media(media_id)), wem_info(replacement)
            channels_match = (old_info['channels'] == new_info['channels']
                              or old_info['channels'] == 1 and new_info['channels'] == 2)
            if old_info['codec'] != new_info['codec'] or old_info['rate'] != new_info['rate'] or not channels_match:
                raise ModError('替换 WEM 必须使用相同的 Vorbis 编码和采样率；仅允许原音单声道转为双声道。')
            with tempfile.TemporaryDirectory() as directory:
                decode_wem(replacement, Path(directory) / 'check.wav')
            modified = current.replace({media_id: replacement})
            if modified == current.data:
                raise ModError('音频与当前内容相同，无需重复替换。')
            directory = self.backup_dir(asset)
            directory.mkdir(parents=True, exist_ok=True)
            if record is None:
                backup = directory / 'original.bin'
                if backup.exists() and backup.read_bytes() != original.data:
                    raise ModError('存在不同的原始备份，未覆盖。')
                if not backup.exists():
                    with backup.open('xb') as handle:
                        handle.write(original.data); handle.flush()
                        import os
                        os.fsync(handle.fileno())
                record = {'asset': asset, 'original_sha': sha(original.data), 'modded_shas': [],
                          'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
            self.backup_bytes(asset, record)
            now = datetime.now(timezone.utc).isoformat(timespec='seconds')
            record.update(modified_at=now, context={'name': card['name'], 'language': card['language']})
            record.setdefault('history', []).append({'time': now, 'action': 'replace', 'card_id': card['card_id'],
                'card_name': card['name'], 'media_id': media_id, 'source': Path(source_name).name,
                'media_sha256': sha(replacement)})
            if sha(modified) not in record['modded_shas']:
                record['modded_shas'].append(sha(modified))
            write_json(directory / 'record.json', record)
            require_game_closed()
            if sha(self.target(asset).read_bytes()) != current_sha:
                raise ModError('写入前语音包变化，已停止。')
            atomic_write(self.target(asset), modified)
            if sha(self.target(asset).read_bytes()) != sha(modified):
                raise ModError('写入回读失败，首次备份已保留。')

    def restore_clip(self, card, media_id, expected_sha):
        asset = card['asset']
        with self.locked():
            self.verify_live_asset(asset)
            current, original, current_sha, record = self.read_package(asset)
            if current_sha != expected_sha or record is None:
                raise ModError('没有备份或语音包已变化，请刷新。')
            if media_id not in {c['media_id'] for c in self.clips(card)[0]}:
                raise ModError('此媒体不属于选中卡牌。')
            if current.media(media_id) == original.media(media_id):
                return False
            replacements = {e['id']: current.content(e) for e in current.entries
                            if e['kind'] == 'media' and e['id'] != media_id
                            and current.content(e) != original.media(e['id'])}
            modified = original.replace(replacements) if replacements else original.data
            record['modified_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            record.setdefault('history', []).append({'time': record['modified_at'], 'action': 'restore_clip',
                'card_id': card['card_id'], 'card_name': card['name'], 'media_id': media_id})
            if sha(modified) not in record['modded_shas']:
                record['modded_shas'].append(sha(modified))
            write_json(self.backup_dir(asset) / 'record.json', record)
            require_game_closed()
            if sha(self.target(asset).read_bytes()) != current_sha:
                raise ModError('恢复前语音包变化。')
            atomic_write(self.target(asset), modified)
            if sha(self.target(asset).read_bytes()) != sha(modified):
                raise ModError('恢复回读校验失败。')
            return True

    def inventory(self, cards):
        # Reuse the artwork inventory's fingerprint and stale-index protections.
        proxy = ModManager(self.game_dir, self.base)
        proxy.data_dir = self.voice_root
        rows = [{'name': c['name'] + ' · ' + c['language'], 'texture_id': c['asset']['hash'], 'asset': c['asset']} for c in cards]
        return scan_backups(proxy, rows)

    def restore_packs(self, cards, entries):
        with self.locked():
            fresh = {r['id']: r for r in self.inventory(cards)}
            count, errors = 0, []
            for expected in entries:
                try:
                    row = fresh.get(expected['id'])
                    if not row or not row['restorable'] or row['current_sha'] != expected['current_sha']:
                        raise ModError('记录或文件已变化，请刷新管理列表。')
                    self.verify_live_asset(row['asset'])
                    count += int(self._restore(row['asset'], row['current_sha']))
                    record = self.metadata(row['asset'])
                    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
                    record.update(modified_at=now)
                    record.setdefault('history', []).append({'time': now, 'action': 'restore_pack'})
                    write_json(self.backup_dir(row['asset']) / 'record.json', record)
                except Exception as exc:
                    errors.append(str(exc))
            return count, errors
