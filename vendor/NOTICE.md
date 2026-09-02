# Vendored third-party code

This directory contains a vendored (committed-in-full) copy of upstream
source code, so that cloning this repository is enough to build the
low-latency transmitter with **no separate download from any other
repository**. This is a deliberate choice - see `docs/DECISIONS.md` ADR-009
for the reasoning and the license implications summarized below.

## vendor/librpitx

- **Upstream:** https://github.com/F5OEO/librpitx
- **Vendored commit:** `f01bdb64bcdb6207f448379193bc0a8accb9aa22`
- **License:** GNU General Public License v3.0 (see `vendor/librpitx/LICENSE`,
  the exact text distributed with upstream).
- **Modifications from upstream: none.** This is an unmodified copy of
  `librpitx/src/`. `native/webtx_iq.cpp` links against it using only its
  existing public API (`iqdmasync`, `clkgpio::enableclk`/`disableclk`,
  `bufferdma::GetBufferAvailable`) - see `native/README.md` for exactly how.
- Original copyright: Evariste Courjaud (F5OEO) and contributors.

## vendor/rpitx-src

- **Upstream:** https://github.com/F5OEO/rpitx
- **Vendored commit:** `ee7ff57b77962536fda4daa523749c04af6beec7`
- **License:** GNU General Public License v3.0 (see
  `vendor/rpitx-src/LICENSE`, copied verbatim from the upstream repository's
  top-level `LICENCE` file).
- **What is vendored:** upstream's `src/` directory, EXCLUDING the nested
  `src/librpitx` subdirectory - that is already vendored separately at
  `vendor/librpitx` above and is not duplicated here.
- **Modifications from upstream: `sendiq.cpp` only.**
  `vendor/rpitx-src/sendiq.cpp` has the same low-latency change as
  `patches/sendiq-lowlatency.patch` applied directly to it (adds `-b`/`-F`
  flags for read-burst size and DMA FIFO size; upstream-identical defaults
  when neither flag is passed - see that file's own top-of-file notice
  comment and `patches/README.md` for exactly what it does and why). Every
  other file under `vendor/rpitx-src/` is an unmodified copy of upstream.
- `native/webtx-sendiq` (see `native/Makefile` and `native/README.md`)
  builds this patched `sendiq.cpp` against the same `vendor/librpitx` (or
  system librpitx) that `native/webtx_iq` uses, producing a stock-`sendiq`-
  compatible fallback sink that also needs zero external download.
- Original copyright: Evariste Courjaud (F5OEO) and contributors.

## License implications for this project

- `vendor/librpitx/**` and `vendor/rpitx-src/**` remain licensed under
  GPL-3.0, exactly as upstream published them. Nothing here changes that
  license or its terms - this applies equally to the one modified file,
  `vendor/rpitx-src/sendiq.cpp` (see that section above); a GPL-3.0
  modification stays GPL-3.0.
- `native/webtx_iq` and `native/webtx-sendiq` (the compiled binaries) each
  **link against** the GPL-3.0 `vendor/librpitx` library, in exactly the
  same way (see `native/Makefile`: both build against the same resolved
  `$(LIBRPITX_LIB)`/`$(INCLUDE_DIR)`). Under GPL-3.0, that makes each
  resulting binary a work that must itself be distributable under
  GPL-3.0-compatible terms. This project already publishes the complete
  corresponding source (this whole repository, including the modified
  `vendor/rpitx-src/sendiq.cpp`), which satisfies that requirement.
- All other code in this repository - the Python server (`webtx/`), the
  browser frontend (`webtx/static/`, `webtx/templates/`), install scripts,
  and documentation - is original work by this project and is licensed
  under the MIT license in the repository root `LICENSE` file. It does not
  link against `vendor/librpitx` or `vendor/rpitx-src` (it talks to
  `native/webtx_iq`/`native/webtx-sendiq` over a subprocess pipe, not a
  library link), so it is not itself GPL-encumbered.
- If you redistribute a build of `native/webtx_iq` or `native/webtx-sendiq`,
  you must do so under GPL-3.0 terms (including making source available,
  which this repository already does).

## Keeping this up to date

If upstream librpitx fixes a bug relevant to this project, update
`vendor/librpitx/` from https://github.com/F5OEO/librpitx, note the new
commit hash above, and record what changed (and why, if anything here was
patched) in this file and in `docs/CHANGELOG.md`.

The same applies to `vendor/rpitx-src/`: if it is ever refreshed from
https://github.com/F5OEO/rpitx, note the new commit hash above, re-apply
the `sendiq.cpp` modification (or confirm `patches/sendiq-lowlatency.patch`
still applies cleanly), and record the update here and in
`docs/CHANGELOG.md`.
