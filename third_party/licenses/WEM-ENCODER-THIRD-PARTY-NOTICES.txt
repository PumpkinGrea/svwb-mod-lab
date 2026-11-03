# Third-party notices

This repository derives parts of its codec behaviour from third-party sources
and ships static tables whose contents originate outside it. This file names
those sources, reproduces the licence they carry, and states which parts of the
repository that licence does not cover. It is an inventory of what is in the
tree: it records facts and resolves no legal question.

## Sources

| Source | What this repository takes from it | Licence |
|---|---|---|
| Xiph.Org OggVorbis reference encoder | Vorbis syntax and decoder order; the floor, residue, mapping and codebook semantics the container must satisfy; the analysis constants the format itself defines | Xiph BSD-style licence, reproduced below |
| aoTuV beta6.03 (Aoyumi's fork of the same encoder) | the stereo residue coupled quantization and classification of the 2ch/48 kHz configuration (`_vp_couple_quantize_normalize`) | the same Xiph BSD-style licence |
| [vgmstream](https://github.com/vgmstream/vgmstream) | publication of the Wwise Vorbis static codebook bodies held in `crates/wem-profiles/src/generated/codebooks/` | ISC-style permissive, stated in its `COPYING` |

## Xiph.Org OggVorbis reference encoder and aoTuV beta6.03

Portions of the codec behaviour in this repository derive from the OggVorbis
reference encoder, and portions from aoTuV beta6.03, Aoyumi's fork of it. The
2ch/48 kHz residue handoff follows aoTuV beta6.03's
`_vp_couple_quantize_normalize`; the end-of-stream LPC training length follows
the public `vorbis_analysis_wrote` path; and the static tables the format itself
defines — the floor dB lookup, the window halves, the transform constants — are
the reference encoder's published values. A table that was observed from the
paired build instead of derived from an upstream is listed under
[Not covered by these notices](#not-covered-by-these-notices).

Both distributions carry the same licence. The text below is quoted verbatim
from the canonical `COPYING` of Xiph's Vorbis distribution,
<https://gitlab.xiph.org/xiph/vorbis/-/raw/master/COPYING> (retrieved
2026-09-23). The clauses are identical in the release this repository checks
against, v1.3.3, whose `COPYING` carries the years `2002-2008`, and in the
current tree, whose `COPYING` carries `2002-2020`; individual source files carry
the years of their own authorship, and libvorbis source files in this lineage
open with `COPYRIGHT 1994-2009 by the Xiph.Org Foundation` — the file
`lib/modes/psych_44.h`, for example.

**Quotation — the upstream licence text, not this project's words:**

> Copyright (c) 2002-2008 Xiph.org Foundation
>
> Redistribution and use in source and binary forms, with or without
> modification, are permitted provided that the following conditions
> are met:
>
> - Redistributions of source code must retain the above copyright
> notice, this list of conditions and the following disclaimer.
>
> - Redistributions in binary form must reproduce the above copyright
> notice, this list of conditions and the following disclaimer in the
> documentation and/or other materials provided with the distribution.
>
> - Neither the name of the Xiph.org Foundation nor the names of its
> contributors may be used to endorse or promote products derived from
> this software without specific prior written permission.
>
> THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
> ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
> LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
> A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE FOUNDATION
> OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
> SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
> LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
> DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
> THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
> (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
> OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

The head of such a source file states the same grant in short form, quoted here
with the file's comment decoration removed:

> THIS FILE IS PART OF THE OggVorbis SOFTWARE CODEC SOURCE CODE.
> USE, DISTRIBUTION AND REPRODUCTION OF THIS LIBRARY SOURCE IS
> GOVERNED BY A BSD-STYLE SOURCE LICENSE INCLUDED WITH THIS SOURCE
> IN 'COPYING'. PLEASE READ THESE TERMS BEFORE DISTRIBUTING.
>
> THE OggVorbis SOURCE CODE IS (C) COPYRIGHT 1994-2009
> by the Xiph.Org Foundation https://xiph.org/

aoTuV beta6.03 is published by Aoyumi at <https://ao-yumi.github.io/aotuv_web/>,
which describes the source as BSD-style licensed and offers
`source_code/libvorbis-aotuv_b6.03.tar.bz2`; current source is at
<https://github.com/AO-Yumi/vorbis_aotuv>.

## vgmstream and the Wwise Vorbis codebook bodies

`crates/wem-profiles/src/generated/codebooks/` holds 598 static Vorbis codebook
bodies as generated Rust tables — `t97.rs`, `t219.rs`, `t282.rs`, about 880 KB
in total. The bodies correspond to the Wwise Vorbis codebooks that vgmstream
publishes in `src/coding/libs/vorbis_codebooks_wwise.h`, and this repository
credits vgmstream as the public source of those tables. vgmstream is
distributed under an ISC-style permissive licence, stated in its `COPYING`
(<https://github.com/vgmstream/vgmstream/blob/master/COPYING>), whose permission
grant reads:

> Permission to use, copy, modify, and distribute this software for any
> purpose with or without fee is hereby granted, provided that the above
> copyright notice and this permission notice appear in all copies.

Inside one table, an ID is a row: `t97` holds IDs 0–96, `t219` holds IDs 97–315
and `t282` holds IDs 316–597. The 2ch/48 kHz configuration refers to book IDs
38–49, 62–76 and **416–430**; 416–430 is exactly the range vgmstream's header
labels `vcb_list_aotuv603`, the aoTuV beta6.03 codebook set. The 6ch/44.1 kHz
configuration refers to no ID at or above 416: it uses 38–49, 62–76 and
213–224. Only the 2ch/48 kHz configuration reaches into the aoTuV range.

## Not covered by these notices

- **The psychoacoustic calibration tables.** The quality curves, the transient
  record families and the 2ch tone bank are encoder-internal values observed
  from the paired build's runtime. No upstream publishes them, they are this
  project's own recorded observations, they appear in no output file, and no
  upstream licence is claimed over them.
- **Audiokinetic's rights in the Wwise format.** This file lists upstream
  software licences only. What this repository does and does not claim about the
  Wwise format, and its relationship to Audiokinetic, is in
  [`PROVENANCE.md`](PROVENANCE.md).
- **This project's own licence.** This file is not it. The terms under which
  this repository itself is offered are stated by its own licence files at the
  repository root, `LICENSE-APACHE` and `LICENSE-MIT`.

## Build dependencies

The Rust crates' third-party dependencies are declared in `crates/Cargo.lock`,
which is committed. Each dependency is distributed by its own authors under its
own licence, and none is vendored into this repository: each is used as its own
distribution provides it.

## How to verify

**1. A setup packet carries book IDs, not codebook bodies.** Each installed
profile's setup packet is a compiled byte constant in
`crates/wem-profiles/src/generated/`: 201 bytes for `wwise2013_6ch_44100.rs`,
215 bytes for `wwise2013_2ch_48000.rs`. Parsed as Vorbis setup syntax, the 6ch
packet holds 39 book references and the 2ch packet 42, each one a 10-bit ID
resolved against tables compiled into the library — which is why a container
cannot be decoded unless its profile is installed, and why no body travels in
the file. `crates/wem-profiles/tests/profiles.rs`
(`two_channel_profile_resolves_t282_books`) parses the 2ch packet, resolves every
ID it holds against the installed tables, and asserts that ID 416 is row 100 of
`t282`:

```bash
cargo test -p wem-profiles two_channel_profile_resolves_t282_books
```

**2. The generated bodies match the publicly published tables.** Fetch
`src/coding/libs/vorbis_codebooks_wwise.h` from
<https://github.com/vgmstream/vgmstream>. Its `vcb_list_aotuv603` entry table
maps IDs 416–430 to byte arrays written bit-reflected (least-significant bit
first within each byte). Unpack each array in libvorbis's `_book_unpack` order
and compare dimension, entry count, length list, map type and quantised values
against rows 100–114 of `crates/wem-profiles/src/generated/codebooks/t282.rs` —
ID 416 is row 100 and ID 430 is row 114, the table's IDs running 316–597. The
remaining installed bodies can be compared the same way against the header's
`vcb_list_standard`.