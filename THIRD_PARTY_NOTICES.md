# Third-party notices

The parsing, decryption and mapping implementations in this project reference
[Hypnos-PD/wbunpacker](https://github.com/Hypnos-PD/wbunpacker), distributed under
the MIT License. Its copyright and permission notice are reproduced below.
Source-module links and other tool references are provided in README.md.

This notice does not grant rights to game assets. Game files, extracted database parameters and third-party unpacker
executables are not included in this repository. Release binaries include
the resource-format base parameter required for artwork decoding.
Separately installed dependencies remain subject to their own licenses.

## wbunpacker — MIT License

Copyright (c) 2025 HypnosPD

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## ProjectPrefs format reference

The disk ProjectPrefs decoder references the technical explanation at
https://linux.do/t/topic/1737538 . The asset traversal, bounded parser and
validation code are implemented in this project. This citation does not
attribute an MIT license to that article.

## Bundled runtime libraries

Release packages keep PySide6/Qt DLLs separate in `_internal/`; compatible
replacement libraries may be used. Reverse engineering to debug modifications
to LGPL-covered components is permitted. LGPLv3 and GPLv3 license texts are
included in `third_party/licenses/` and in the release dependency notices.
The package includes Python's runtime license and installed dependency notices.

Corresponding unmodified upstream sources for the pinned Qt/PySide6 version:
https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/
https://download.qt.io/official_releases/qt/6.12/6.12.0/single/
https://code.qt.io/cgit/pyside/pyside-setup.git/
https://code.qt.io/cgit/qt/qtbase.git/


## vgmstream audio decoder

Voice preview uses the unmodified vgmstream command-line decoder from https://github.com/vgmstream/vgmstream . The decoder and its companion DLLs are distributed together under `_internal/audio-tools/`. Their upstream `COPYING` file is included in that directory. Review that file for component-specific licenses when redistributing.

## Wwise Vorbis encoder

Common audio import uses the standalone encoder from https://github.com/rabbit-smith/wem at commit `c757fe4d2354cbd4d66960179c7715d79b13bae0`, built with `cargo build --release --manifest-path crates/Cargo.toml -p wem-core --features parallel`. The unmodified `wwise-wem.exe` is packaged under `_internal/audio-tools/`. Its MIT and Apache-2.0 license texts and upstream third-party notices are included in `third_party/licenses/` and release dependency notices. The executable is not stored in this source repository. The stereo 48 kHz Wwise 2013.2 profile is used for common audio import; other sample rates may be rejected by this encoder. No Audiokinetic authoring software is required.
