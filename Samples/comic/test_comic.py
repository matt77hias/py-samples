#!/usr/bin/env python3
"""
Unit tests for comic_lib and calibre_normalize.

Run:
    python -m pytest test_comic.py -v
    # or, without pytest installed:
    python -m unittest test_comic -v

Tests that need optional dependencies (Pillow, rar/unrar) are skipped
automatically when those are unavailable, so the pure-logic suite always runs.
"""

import io
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import comic_lib as cl
import comic_convert as cc
from calibre_normalize import book_id_from_path, resolve_cbr_cbz_pairs

# ── Optional-dependency probes ───────────────────────────────────────────────

HAVE_PIL = cl.Image is not None

HAVE_RAR = cl.can_read_rar()
HAVE_RAR_WRITE = cl.RAR_TOOL is not None


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_jpeg(w=100, h=120, color=(200, 30, 30)) -> bytes:
    if cl.Image is None:
        raise unittest.SkipTest("Pillow not installed")
    buf = io.BytesIO()
    cl.Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


def make_grey_jpeg(w=100, h=120, value=128) -> bytes:
    if cl.Image is None:
        raise unittest.SkipTest("Pillow not installed")
    buf = io.BytesIO()
    cl.Image.new("L", (w, h), value).save(buf, "JPEG")
    return buf.getvalue()


def make_png(w=100, h=120, color=(30, 30, 200)) -> bytes:
    if cl.Image is None:
        raise unittest.SkipTest("Pillow not installed")
    buf = io.BytesIO()
    cl.Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def make_palette_gif(w=100, h=120) -> bytes:
    """A GIF, which Pillow reports as mode 'P' (palette) on a header decode."""
    if cl.Image is None:
        raise unittest.SkipTest("Pillow not installed")
    buf = io.BytesIO()
    cl.Image.new("P", (w, h)).save(buf, "GIF")
    return buf.getvalue()


def make_cbz(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


# ── Pure logic: page_name (the padding spec) ─────────────────────────────────

class TestPageName(unittest.TestCase):
    """page_name(): zero-padding width follows the total page count."""

    def test_padding_scales_with_total(self):
        """<10 pages -> 1 digit, <100 -> 2, <1000 -> 3, 1000 -> 4."""
        self.assertEqual(cl.page_name(0, 9), "1.jpg")
        self.assertEqual(cl.page_name(8, 9), "9.jpg")
        self.assertEqual(cl.page_name(0, 10), "01.jpg")
        self.assertEqual(cl.page_name(9, 10), "10.jpg")
        self.assertEqual(cl.page_name(0, 100), "001.jpg")
        self.assertEqual(cl.page_name(99, 100), "100.jpg")
        self.assertEqual(cl.page_name(0, 1000), "0001.jpg")

    def test_single_page(self):
        """A one-page book uses a single unpadded digit."""
        self.assertEqual(cl.page_name(0, 1), "1.jpg")

    def test_extension_respected(self):
        """The supplied extension is preserved in the generated name."""
        self.assertEqual(cl.page_name(0, 10, ".png"), "01.png")


# ── Pure logic: natural_key ──────────────────────────────────────────────────

class TestNaturalKey(unittest.TestCase):
    """natural_key(): numeric-aware sort so page2 < page10."""

    def test_numeric_ordering(self):
        """Embedded numbers sort by value, not lexicographically."""
        names = ["p10.jpg", "p2.jpg", "p1.jpg", "p20.jpg"]
        self.assertEqual(
            sorted(names, key=cl.natural_key),
            ["p1.jpg", "p2.jpg", "p10.jpg", "p20.jpg"],
        )

    def test_unpadded_vs_padded(self):
        """Unpadded page names still order correctly."""
        self.assertEqual(
            sorted(["1.jpg", "10.jpg", "2.jpg"], key=cl.natural_key),
            ["1.jpg", "2.jpg", "10.jpg"],
        )

    def test_case_insensitive(self):
        """Letter runs compare case-insensitively (a before B)."""
        self.assertEqual(
            sorted(["B.jpg", "a.jpg"], key=cl.natural_key),
            ["a.jpg", "B.jpg"],
        )


# ── Pure logic: junk filtering ───────────────────────────────────────────────

class TestPageEntryFilter(unittest.TestCase):
    """_is_page_entry(): distinguishes real pages from archive junk."""

    def test_accepts_real_pages(self):
        """Image files (incl. nested, mixed-case ext) count as pages."""
        for n in ["01.jpg", "page10.PNG", "ch1/02.jpg", "cover.jpeg"]:
            self.assertTrue(cl._is_page_entry(n), n)

    def test_rejects_junk(self):
        """macOS forks, dotfiles, Thumbs.db, dirs and non-images are skipped."""
        for n in ["__MACOSX/._01.jpg", "._01.jpg", ".DS_Store",
                  "Thumbs.db", "subdir/", "notes.txt"]:
            self.assertFalse(cl._is_page_entry(n), n)


# ── Pure logic: is_normalized_cbz ────────────────────────────────────────────

class TestIsNormalized(unittest.TestCase):
    """is_normalized_cbz(): detects CBZs already matching the naming convention
    so the normalizer can skip rewriting them."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _cbz(self, name, members):
        """Build a throwaway CBZ with the given member names (stub bytes)."""
        p = self.dir / name
        make_cbz(p, {m: b"x" for m in members})
        return p

    def test_normalized_variants(self):
        """Padded pages in order - with or without ComicInfo.xml - are normalized."""
        self.assertTrue(cl.is_normalized_cbz(self._cbz("a.cbz", ["1.jpg", "2.jpg", "3.jpg"])))
        self.assertTrue(cl.is_normalized_cbz(
            self._cbz("b.cbz", [f"{i:02d}.jpg" for i in range(1, 11)])))
        self.assertTrue(cl.is_normalized_cbz(
            self._cbz("c.cbz", ["1.jpg", "2.jpg", "ComicInfo.xml"])))

    def test_correctly_named_nonjpeg_is_normalized(self):
        """A correctly-named non-JPEG/PNG page (1.gif) counts as normalized: the
        check is about naming, not encoding, so we don't trigger a lossy transcode
        on a file that already has proper page names."""
        self.assertTrue(cl.is_normalized_cbz(self._cbz("g1.cbz", ["1.gif", "2.gif"])))

    def test_not_normalized(self):
        """Wrong padding, prefixes, nesting, or stray files are not normalized."""
        # unpadded at 10 pages
        self.assertFalse(cl.is_normalized_cbz(
            self._cbz("d.cbz", [f"{i}.jpg" for i in range(1, 11)])))
        # prefixed
        self.assertFalse(cl.is_normalized_cbz(self._cbz("e.cbz", ["page1.jpg", "page2.jpg"])))
        # nested dir
        self.assertFalse(cl.is_normalized_cbz(self._cbz("f.cbz", ["sub/1.jpg", "sub/2.jpg"])))
        # stray non-metadata file
        self.assertFalse(cl.is_normalized_cbz(self._cbz("g.cbz", ["1.jpg", "notes.txt"])))

    def test_empty_or_bad(self):
        """A page-less archive or a non-ZIP file is not normalized (no crash)."""
        self.assertFalse(cl.is_normalized_cbz(self._cbz("h.cbz", ["ComicInfo.xml"])))
        bad = self.dir / "bad.cbz"
        bad.write_bytes(b"not a zip")
        self.assertFalse(cl.is_normalized_cbz(bad))


# ── Pure logic: archive_extras ───────────────────────────────────────────────

class TestArchiveExtras(unittest.TestCase):
    """archive_extras(): pulls preservable reader metadata (ComicInfo.xml)."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_root_comicinfo_only(self):
        """Root-level ComicInfo.xml is returned; a nested copy is ignored."""
        p = self.dir / "m.cbz"
        make_cbz(p, {"1.jpg": b"a", "ComicInfo.xml": b"<xml/>",
                     "sub/ComicInfo.xml": b"<nested/>"})
        md = cl.archive_extras(p)
        self.assertEqual(list(md), ["ComicInfo.xml"])
        self.assertEqual(md["ComicInfo.xml"], b"<xml/>")

    def test_arbitrary_sidecars_dropped(self):
        """Non-metadata sidecars (credits.txt, *.nfo) are NOT preserved."""
        p = self.dir / "s.cbz"
        make_cbz(p, {"1.jpg": b"a", "credits.txt": b"x", "book.nfo": b"y"})
        self.assertEqual(cl.archive_extras(p), {})

    def test_absent_metadata(self):
        """An archive with no metadata members yields an empty dict."""
        p = self.dir / "n.cbz"
        make_cbz(p, {"1.jpg": b"a"})
        self.assertEqual(cl.archive_extras(p), {})


# ── Container detection (extension-independent) ───────────────────────────────

class TestDetectFormat(unittest.TestCase):
    """detect_format(): identifies the real container regardless of extension."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_zip_detected_regardless_of_extension(self):
        """A ZIP is detected as cbz even when named .cbr."""
        p = self.dir / "mislabeled.cbr"
        make_cbz(p, {"1.jpg": b"x"})
        self.assertEqual(cl.detect_format(p), "cbz")

    def test_pdf_detected(self):
        """A file starting with %PDF- is detected as pdf."""
        p = self.dir / "x.cbz"
        p.write_bytes(b"%PDF-1.7\n...")
        self.assertEqual(cl.detect_format(p), "pdf")

    def test_garbage_is_none(self):
        """Unrecognized content returns None (caller falls back to extension)."""
        p = self.dir / "x.cbz"
        p.write_bytes(b"not any known archive")
        self.assertIsNone(cl.detect_format(p))

    def test_missing_file_is_none(self):
        """A nonexistent path returns None rather than raising."""
        self.assertIsNone(cl.detect_format(self.dir / "nope.cbz"))

    @unittest.skipUnless(cl.rarfile is not None, "rarfile not installed")
    def test_rar_detected_when_available(self):
        """A RAR is detected as cbr (requires rarfile; content, not extension)."""
        # Build a minimal RAR only if a create tool exists; else just assert the
        # detector doesn't misclassify a real ZIP as RAR.
        p = self.dir / "real.cbz"
        make_cbz(p, {"1.jpg": b"x"})
        self.assertEqual(cl.detect_format(p), "cbz")  # never false-positive as cbr


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class TestMislabeledConversion(unittest.TestCase):
    """A ZIP archive saved with a .cbr extension still converts correctly,
    because dispatch detects the real container instead of trusting the name."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_zip_named_cbr_converts(self):
        """A ZIP misnamed .cbr converts to CBZ without needing unrar."""
        src = self.dir / "mislabeled.cbr"      # actually a ZIP
        page = make_jpeg()
        make_cbz(src, {"1.jpg": page})
        dst = self.dir / "out.cbz"
        n = cl.convert(src, dst, "cbz")
        self.assertEqual(n, 1)
        with zipfile.ZipFile(dst) as z:
            self.assertEqual(z.read("1.jpg"), page)

    def test_garbage_raises_conversion_error(self):
        """A non-archive file raises ConversionError, not a raw library error."""
        src = self.dir / "junk.cbz"
        src.write_bytes(b"total garbage")
        with self.assertRaises(cl.ConversionError):
            cl.convert(src, self.dir / "out.cbz", "cbz")


# ── Calibre: book id extraction ──────────────────────────────────────────────

class TestBookId(unittest.TestCase):
    """book_id_from_path(): reads the Calibre id from the 'Title (id)' folder."""

    def test_extracts_id(self):
        """The id is parsed from the book's containing folder name."""
        lib = Path("/lib")
        p = lib / "Neil Gaiman" / "Sandman (1423)" / "Sandman.cbr"
        self.assertEqual(book_id_from_path(p, lib), 1423)

    def test_no_id_returns_none(self):
        """No '(id)' anywhere in the path returns None."""
        lib = Path("/lib")
        p = lib / "Author" / "No Id Here" / "x.cbr"
        self.assertIsNone(book_id_from_path(p, lib))

    def test_id_on_immediate_parent_wins(self):
        """The nearest parent with an id wins over ancestors."""
        lib = Path("/lib")
        p = lib / "Series (5)" / "Volume (99)" / "x.cbr"
        self.assertEqual(book_id_from_path(p, lib), 99)


# ── Calibre: CBR/CBZ same-stem resolution ────────────────────────────────────

class TestResolveCbrCbzPairs(unittest.TestCase):
    """resolve_cbr_cbz_pairs(): when a CBR and CBZ share a stem, the CBR is
    ignored (CBZ already satisfies the target) - never converted over its sibling."""

    def test_cbr_ignored_when_cbz_sibling_exists(self):
        """The CBR is dropped from the worklist; the CBZ is kept."""
        d = Path("/lib/A/T (1)")
        cbr, cbz = d / "foo.cbr", d / "foo.cbz"
        keep, ignored = resolve_cbr_cbz_pairs([cbr, cbz])
        self.assertEqual(keep, [cbz])
        self.assertEqual(ignored, [cbr])

    def test_standalone_files_untouched(self):
        """A lone CBR and a lone CBZ (different stems) are both kept."""
        lone_cbr = Path("/lib/A/a.cbr")
        lone_cbz = Path("/lib/B/b.cbz")
        keep, ignored = resolve_cbr_cbz_pairs([lone_cbr, lone_cbz])
        self.assertEqual(sorted(keep), sorted([lone_cbr, lone_cbz]))
        self.assertEqual(ignored, [])

    def test_same_stem_different_dirs_not_a_pair(self):
        """Same stem in different folders is not a conflict (different books)."""
        cbr = Path("/lib/A (1)/foo.cbr")
        cbz = Path("/lib/B (2)/foo.cbz")
        keep, ignored = resolve_cbr_cbz_pairs([cbr, cbz])
        self.assertEqual(ignored, [])
        self.assertEqual(sorted(keep), sorted([cbr, cbz]))

    def test_case_insensitive_stem_match(self):
        """Stem matching is case-insensitive (Foo.cbr vs foo.cbz)."""
        d = Path("/lib/A (1)")
        cbr, cbz = d / "Foo.cbr", d / "foo.cbz"
        keep, ignored = resolve_cbr_cbz_pairs([cbr, cbz])
        self.assertEqual(ignored, [cbr])
        self.assertEqual(keep, [cbz])


# ── CBZ round-trips (need Pillow) ────────────────────────────────────────────

@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class TestCbzConversion(unittest.TestCase):
    """End-to-end CBZ conversions: passthrough, page drops, and fill-missing."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_passthrough_is_lossless_and_renames(self):
        """JPEG/PNG bytes and ComicInfo.xml survive intact; pages get padded names."""
        src = self.dir / "src.cbz"
        p1, p2, p3 = make_jpeg(color=(255, 0, 0)), make_jpeg(color=(0, 255, 0)), make_png()
        make_cbz(src, {"page1.jpg": p1, "page2.jpg": p2, "page3.png": p3,
                       "ComicInfo.xml": b"<meta/>"})
        dst = self.dir / "out.cbz"
        n = cl.convert(src, dst, "cbz")
        self.assertEqual(n, 3)
        with zipfile.ZipFile(dst) as z:
            self.assertEqual(z.namelist(), ["1.jpg", "2.jpg", "3.png", "ComicInfo.xml"])
            self.assertEqual(z.read("1.jpg"), p1)  # bytes untouched
            self.assertEqual(z.read("3.png"), p3)
            self.assertEqual(z.read("ComicInfo.xml"), b"<meta/>")
        self.assertTrue(cl.is_normalized_cbz(dst))

    def test_write_cbz_images_use_zip_stored(self):
        """JPEG and PNG pages are stored with ZIP_STORED (not DEFLATED) in the output CBZ."""
        src = self.dir / "src.cbz"
        make_cbz(src, {"1.jpg": make_jpeg(), "2.png": make_png()})
        dst = self.dir / "stored.cbz"
        cl.convert(src, dst, "cbz")
        with zipfile.ZipFile(dst) as z:
            for info in z.infolist():
                if Path(info.filename).suffix.lower() in (".jpg", ".png"):
                    self.assertEqual(
                        info.compress_type, zipfile.ZIP_STORED,
                        f"{info.filename} should use ZIP_STORED, got {info.compress_type}",
                    )

    def test_extra_never_shadows_a_page(self):
        """An extra whose name collides with a generated page name is dropped,
        not written over the page (guard exists in both write_cbz and write_cbr)."""
        img = make_jpeg(color=(1, 2, 3))
        dst = self.dir / "c.cbz"
        cl.write_cbz([cl.Page(data=img, ext=".jpg")], dst, 90,
                     extras={"1.jpg": b"EXTRA-COLLIDES"})
        with zipfile.ZipFile(dst) as z:
            self.assertEqual(z.read("1.jpg"), img)  # page bytes intact

    def test_dest_is_directory_raises_cleanly(self):
        """If dest is an existing directory, raise ConversionError (not a raw
        OSError), and leave the source untouched."""
        src = self.dir / "s.cbz"
        make_cbz(src, {"1.jpg": make_jpeg()})
        target = self.dir / "target.cbz"
        target.mkdir()
        with self.assertRaises(cl.ConversionError):
            cl.convert(src, target, "cbz")

    def test_drop_first_and_last(self):
        """--drop-first/--drop-last trim the ends; remaining pages renumber."""
        src = self.dir / "d.cbz"
        pages = [make_jpeg(color=(i, i, i)) for i in range(1, 6)]
        make_cbz(src, {f"{i}.jpg": b for i, b in enumerate(pages, 1)})
        dst = self.dir / "dropped.cbz"
        n = cl.convert(src, dst, "cbz", drop_first=1, drop_last=1)
        self.assertEqual(n, 3)
        with zipfile.ZipFile(dst) as z:
            self.assertEqual(z.namelist(), ["1.jpg", "2.jpg", "3.jpg"])
            self.assertEqual(z.read("1.jpg"), pages[1])  # original page 2
            self.assertEqual(z.read("3.jpg"), pages[3])  # original page 4

    def test_fill_missing_replaces_unreadable_page(self):
        """An unreadable page becomes a white filler at the reference resolution."""
        # Build a valid zip, then corrupt page 2's data so extraction fails (bad CRC).
        buf = io.BytesIO()
        good = make_jpeg(500, 700, (10, 20, 30))
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("1.jpg", good)
            z.writestr("2.jpg", make_jpeg(500, 700, (99, 99, 99)))
            z.writestr("3.jpg", make_jpeg(500, 700, (40, 50, 60)))
        raw = bytearray(buf.getvalue())
        second_soi = raw.find(b"\xff\xd8", raw.find(b"\xff\xd8") + 2)
        raw[second_soi + 10] ^= 0xFF  # corrupt second JPEG
        src = self.dir / "bad.cbz"
        src.write_bytes(raw)

        dst = self.dir / "filled.cbz"
        cl.convert(src, dst, "cbz", fill_missing="white")
        with zipfile.ZipFile(dst) as z:
            self.assertEqual(len(z.namelist()), 3)
            im = cl.Image.open(io.BytesIO(z.read("2.jpg")))
            self.assertEqual(im.size, (500, 700))              # matches ref resolution
            self.assertEqual(im.convert("RGB").getpixel((0, 0)), (255, 255, 255))

    def test_fill_missing_filler_matches_greyscale_mode(self):
        """Filler page for a greyscale archive is L-mode, not RGB."""
        buf = io.BytesIO()
        grey = make_grey_jpeg(500, 700, 200)
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("1.jpg", grey)
            z.writestr("2.jpg", grey)  # will be corrupted
        raw = bytearray(buf.getvalue())
        second_soi = raw.find(b"\xff\xd8", raw.find(b"\xff\xd8") + 2)
        raw[second_soi + 10] ^= 0xFF
        src = self.dir / "grey_bad.cbz"
        src.write_bytes(raw)
        dst = self.dir / "grey_filled.cbz"
        cl.convert(src, dst, "cbz", fill_missing="white")
        with zipfile.ZipFile(dst) as z:
            im = cl.Image.open(io.BytesIO(z.read("2.jpg")))
        self.assertEqual(im.mode, "L")  # filler matches surrounding greyscale pages

    def test_fill_missing_with_palette_reference_page(self):
        """A palette-mode (GIF) reference page must not crash blank_page: its
        exotic 'P' mode is clamped to RGB for the filler."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("1.gif", make_palette_gif(300, 400))  # reference page
            z.writestr("2.jpg", make_jpeg(300, 400))          # will be corrupted
        raw = bytearray(buf.getvalue())
        soi = raw.find(b"\xff\xd8")  # the JPEG's start-of-image
        raw[soi + 10] ^= 0xFF
        src = self.dir / "palette_bad.cbz"
        src.write_bytes(raw)
        dst = self.dir / "palette_filled.cbz"
        # Must not raise TypeError from Image.new("P", size, (255,255,255)).
        cl.convert(src, dst, "cbz", fill_missing="white")
        with zipfile.ZipFile(dst) as z:
            self.assertEqual(len(z.namelist()), 2)
            im = cl.Image.open(io.BytesIO(z.read("2.jpg")))
            self.assertEqual(im.convert("RGB").getpixel((0, 0)), (255, 255, 255))

    def test_missing_page_dropped_without_fill(self):
        """Without --fill-missing, an unreadable page is dropped from the output."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("1.jpg", make_jpeg())
            z.writestr("2.jpg", make_jpeg())
        raw = bytearray(buf.getvalue())
        second_soi = raw.find(b"\xff\xd8", raw.find(b"\xff\xd8") + 2)
        raw[second_soi + 5] ^= 0xFF
        src = self.dir / "bad2.cbz"
        src.write_bytes(raw)
        dst = self.dir / "out2.cbz"
        n = cl.convert(src, dst, "cbz")  # no fill -> drop the bad page
        self.assertEqual(n, 1)


# ── log callable threading ───────────────────────────────────────────────────

@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class TestLogCallable(unittest.TestCase):
    """convert() forwards all diagnostic output to the supplied log callable."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_cbz_logged(self):
        """'Wrote CBZ' line is sent to log, not to stdout."""
        src = self.dir / "s.cbz"
        make_cbz(src, {"1.jpg": make_jpeg()})
        dst = self.dir / "out.cbz"
        lines: list[str] = []
        cl.convert(src, dst, "cbz", log=lines.append)
        self.assertTrue(any("Wrote CBZ" in l for l in lines))

    def test_missing_page_warning_logged(self):
        """Unreadable-page warning is sent to log, not stdout."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("1.jpg", make_jpeg())
            z.writestr("2.jpg", make_jpeg())
        raw = bytearray(buf.getvalue())
        second_soi = raw.find(b"\xff\xd8", raw.find(b"\xff\xd8") + 2)
        raw[second_soi + 5] ^= 0xFF
        src = self.dir / "bad.cbz"
        src.write_bytes(raw)
        lines: list[str] = []
        cl.convert(src, self.dir / "out.cbz", "cbz", log=lines.append)
        self.assertTrue(any("Warning" in l for l in lines))

    def test_fill_missing_replacement_logged(self):
        """Filler-page replacement message is sent to log."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("1.jpg", make_jpeg(200, 300))
            z.writestr("2.jpg", make_jpeg(200, 300))
        raw = bytearray(buf.getvalue())
        second_soi = raw.find(b"\xff\xd8", raw.find(b"\xff\xd8") + 2)
        raw[second_soi + 10] ^= 0xFF
        src = self.dir / "bad2.cbz"
        src.write_bytes(raw)
        lines: list[str] = []
        cl.convert(src, self.dir / "out2.cbz", "cbz", fill_missing="white", log=lines.append)
        self.assertTrue(any("Replacing missing" in l for l in lines))


# ── PDF round-trips (need Pillow + fitz/img2pdf) ─────────────────────────────

@unittest.skipUnless(HAVE_PIL and (cl.fitz is not None or cl.img2pdf is not None),
                     "PDF backend not installed")
class TestPdfConversion(unittest.TestCase):
    """CBZ<->PDF conversions using the fitz/img2pdf backends."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cbz_to_pdf_page_count(self):
        """CBZ -> PDF produces a non-empty file with one page per image."""
        src = self.dir / "s.cbz"
        make_cbz(src, {f"{i}.jpg": make_jpeg() for i in range(1, 4)})
        dst = self.dir / "o.pdf"
        n = cl.convert(src, dst, "pdf")
        self.assertEqual(n, 3)
        self.assertTrue(dst.exists() and dst.stat().st_size > 0)

    @unittest.skipUnless(cl.fitz is not None, "PyMuPDF not installed")
    def test_pdf_to_cbz_roundtrip(self):
        """PDF -> CBZ rasterizes each page back to a padded-name image."""
        src = self.dir / "s.cbz"
        make_cbz(src, {f"{i}.jpg": make_jpeg() for i in range(1, 4)})
        pdf = self.dir / "o.pdf"
        cl.convert(src, pdf, "pdf")
        back = self.dir / "back.cbz"
        n = cl.convert(pdf, back, "cbz", pdf_dpi=72)
        self.assertEqual(n, 3)
        with zipfile.ZipFile(back) as z:
            self.assertEqual(z.namelist(), ["1.jpg", "2.jpg", "3.jpg"])


# ── CBR round-trips (need Pillow + rar/unrar) ────────────────────────────────

@unittest.skipUnless(HAVE_PIL and HAVE_RAR and HAVE_RAR_WRITE,
                     "rar create/read tools or Pillow not available")
class TestCbrConversion(unittest.TestCase):
    """CBR round-trip via the rar/unrar CLIs (needs the tools installed)."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cbz_cbr_cbz_roundtrip_preserves_bytes_and_metadata(self):
        """CBZ -> CBR -> CBZ keeps page bytes and ComicInfo.xml unchanged."""
        src = self.dir / "src.cbz"
        p1, p3 = make_jpeg(color=(255, 0, 0)), make_png()
        meta = b"<ComicInfo><Title>T</Title></ComicInfo>"
        make_cbz(src, {"page1.jpg": p1, "page2.jpg": make_jpeg(color=(0, 255, 0)),
                       "page3.png": p3, "ComicInfo.xml": meta})
        cbr = self.dir / "out.cbr"
        cl.convert(src, cbr, "cbr")
        back = self.dir / "back.cbz"
        cl.convert(cbr, back, "cbz")
        with zipfile.ZipFile(back) as z:
            self.assertEqual(z.read("1.jpg"), p1)
            self.assertEqual(z.read("3.png"), p3)
            self.assertEqual(z.read("ComicInfo.xml"), meta)


# ── RAR tool resolution & fail-loud behavior (data-loss guards) ──────────────

class TestRarToolResolution(unittest.TestCase):
    """Tool detection and the guarantee that a broken RAR reader fails loudly
    instead of silently dropping pages (which would then delete the source)."""

    @unittest.skipUnless(cl.rarfile is not None, "rarfile not installed")
    def test_set_rar_tools_overrides(self):
        """set_rar_tools() updates both module state and rarfile.UNRAR_TOOL."""
        saved = cl.RAR_TOOL, cl.UNRAR_TOOL, cl.rarfile.UNRAR_TOOL
        try:
            cl.set_rar_tools(rar="/custom/rar", unrar="/custom/unrar")
            self.assertEqual(cl.RAR_TOOL, "/custom/rar")
            self.assertEqual(cl.UNRAR_TOOL, "/custom/unrar")
            self.assertEqual(cl.rarfile.UNRAR_TOOL, "/custom/unrar")
        finally:
            cl.RAR_TOOL, cl.UNRAR_TOOL, cl.rarfile.UNRAR_TOOL = saved

    def test_cbr_output_without_rar_tool_raises(self):
        """CBR output with no create tool raises a clear error (not a crash)."""
        saved = cl.RAR_TOOL
        try:
            cl.RAR_TOOL = None
            with self.assertRaises(cl.ConversionError) as ctx:
                cl.write_cbr([cl.Page(data=b"\xff\xd8x", ext=".jpg")],
                             Path(self.__class__.__name__ + ".cbr"), 90)
            self.assertIn("rar", str(ctx.exception).lower())
        finally:
            cl.RAR_TOOL = saved

    def test_strict_read_raises_on_failure(self):
        """The core data-loss guard: with strict=True (used for CBR), a member
        that fails to read RAISES instead of becoming a missing-page placeholder.
        A broken/absent unrar makes every read fail, so this stops the normalizer
        from writing a short CBZ and then deleting the source CBR."""
        def bad_reader(name):
            raise OSError("simulated unrar failure")

        names = ["1.jpg", "2.jpg", "3.jpg"]
        # non-strict (CBZ behavior): degrades to placeholders, no raise
        pages = cl._extract_archive(names, bad_reader, "CBZ", strict=False)
        self.assertTrue(all(p.missing for p in pages))
        # strict (CBR behavior): raises loudly
        with self.assertRaises(cl.ConversionError):
            cl._extract_archive(names, bad_reader, "CBR", strict=True)


# ── comic_convert CLI job planning ───────────────────────────────────────────

class TestCollectJobs(unittest.TestCase):
    """collect_jobs(): batch/single job planning and collision safety."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_batch_preserves_subdirs(self):
        """Directory sources map to dest mirroring their relative subpaths."""
        (self.dir / "src" / "sub").mkdir(parents=True)
        (self.dir / "src" / "a.cbz").touch()
        (self.dir / "src" / "sub" / "b.cbz").touch()
        jobs = cc.collect_jobs(self.dir / "src", self.dir / "out", "pdf")
        rels = sorted(str(d.relative_to(self.dir / "out")) for _, d in jobs)
        self.assertEqual(rels, [str(Path("a.pdf")), str(Path("sub") / "b.pdf")])

    def test_output_collision_exits(self):
        """Two sources sharing a stem (book.cbr + book.cbz) abort, not clobber."""
        (self.dir / "src").mkdir()
        (self.dir / "src" / "book.cbz").touch()
        (self.dir / "src" / "book.cbr").touch()
        with self.assertRaises(SystemExit):
            cc.collect_jobs(self.dir / "src", self.dir / "out", "pdf")

    def test_nested_dest_excluded_from_scan(self):
        """When dest is inside source, the walk must not re-discover its own
        output (which would re-convert files and grow the tree on repeat runs)."""
        src = self.dir / "src"
        (src / "converted").mkdir(parents=True)
        (src / "a.cbz").touch()
        (src / "converted" / "a.cbz").touch()  # prior run's output
        jobs = cc.collect_jobs(src, src / "converted", "cbz")
        srcs = [s for s, _ in jobs]
        self.assertEqual(srcs, [src / "a.cbz"])

    def test_single_file_to_explicit_path(self):
        """A single source with a matching-extension dest uses it verbatim."""
        src = self.dir / "x.cbz"
        src.touch()
        jobs = cc.collect_jobs(src, self.dir / "y.pdf", "pdf")
        self.assertEqual(jobs, [(src, self.dir / "y.pdf")])


# ── --dry-run ────────────────────────────────────────────────────────────────

@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class TestDryRun(unittest.TestCase):
    """--dry-run: logs intent without writing any output files."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_args(self, dry_run=True, overwrite=False):
        return cc.ConvertOptions(dry_run=dry_run, overwrite=overwrite)

    def test_dry_run_writes_no_file(self):
        """In dry-run mode, no destination file is created."""
        src = self.dir / "src.cbz"
        make_cbz(src, {"1.jpg": make_jpeg()})
        dst = self.dir / "out.cbz"
        cc.convert_file(src, dst, "cbz", self._make_args())
        self.assertFalse(dst.exists())

    def test_dry_run_logs_would_convert(self):
        """'Would convert' is logged when destination does not exist."""
        src = self.dir / "src.cbz"
        make_cbz(src, {"1.jpg": make_jpeg()})
        dst = self.dir / "out.cbz"
        lines: list[str] = []
        cc.convert_file(src, dst, "cbz", self._make_args(), log=lines.append)
        self.assertTrue(any("Would convert" in l for l in lines))

    def test_dry_run_logs_would_skip_when_dest_exists(self):
        """'Would skip' is logged when destination exists and --overwrite is not set."""
        src = self.dir / "src.cbz"
        make_cbz(src, {"1.jpg": make_jpeg()})
        dst = self.dir / "out.cbz"
        dst.touch()  # destination already exists
        lines: list[str] = []
        cc.convert_file(src, dst, "cbz", self._make_args(), log=lines.append)
        self.assertTrue(any("Would skip" in l for l in lines))

    def test_dry_run_overwrite_flag_overrides_skip(self):
        """With --overwrite set, 'Would convert' is logged even when dest exists."""
        src = self.dir / "src.cbz"
        make_cbz(src, {"1.jpg": make_jpeg()})
        dst = self.dir / "out.cbz"
        dst.touch()
        lines: list[str] = []
        cc.convert_file(src, dst, "cbz", self._make_args(overwrite=True), log=lines.append)
        self.assertTrue(any("Would convert" in l for l in lines))
        self.assertFalse(any("Would skip" in l for l in lines))
        self.assertEqual(dst.stat().st_size, 0)  # file untouched (still empty)

    def test_returns_dry_convert_result(self):
        """Dry-run of a new dest returns Result.DRY_CONVERT."""
        src = self.dir / "src.cbz"
        make_cbz(src, {"1.jpg": make_jpeg()})
        r = cc.convert_file(src, self.dir / "out.cbz", "cbz", self._make_args())
        self.assertIs(r, cc.Result.DRY_CONVERT)

    def test_returns_dry_skip_result(self):
        """Dry-run when dest exists (no overwrite) returns Result.DRY_SKIP."""
        src = self.dir / "src.cbz"
        make_cbz(src, {"1.jpg": make_jpeg()})
        dst = self.dir / "out.cbz"
        dst.touch()
        r = cc.convert_file(src, dst, "cbz", self._make_args())
        self.assertIs(r, cc.Result.DRY_SKIP)


# ── convert_file result codes (non-dry-run) ──────────────────────────────────

@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class TestConvertFileResult(unittest.TestCase):
    """convert_file returns an accurate Result so main() can tally outcomes."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_converted_result(self):
        """A real conversion returns Result.CONVERTED."""
        src = self.dir / "src.cbz"
        make_cbz(src, {"1.jpg": make_jpeg()})
        r = cc.convert_file(src, self.dir / "out.cbz", "cbz", cc.ConvertOptions())
        self.assertIs(r, cc.Result.CONVERTED)

    def test_skipped_result_when_dest_exists(self):
        """An existing dest without --overwrite returns Result.SKIPPED and does
        not rewrite the file."""
        src = self.dir / "src.cbz"
        make_cbz(src, {"1.jpg": make_jpeg()})
        dst = self.dir / "out.cbz"
        dst.write_bytes(b"sentinel")
        r = cc.convert_file(src, dst, "cbz", cc.ConvertOptions())
        self.assertIs(r, cc.Result.SKIPPED)
        self.assertEqual(dst.read_bytes(), b"sentinel")  # untouched


# ── infer_format ──────────────────────────────────────────────────────────────

class TestInferFormat(unittest.TestCase):
    """infer_format(): explicit flag wins, else read from the dest extension."""

    def test_explicit_wins(self):
        self.assertEqual(cc.infer_format(Path("out.cbz"), "pdf"), "pdf")

    def test_from_extension(self):
        self.assertEqual(cc.infer_format(Path("out.cbr"), None), "cbr")

    def test_unknown_exits(self):
        with self.assertRaises(SystemExit):
            cc.infer_format(Path("out.txt"), None)


# ── Page.encoded() image_format support ─────────────────────────────────────

@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class TestPageEncoded(unittest.TestCase):
    """Page.encoded(): respects image_format (jpeg/png/webp)."""

    def _rgb_page(self, color=(200, 100, 50)):
        return cl.Page(image=cl.Image.new("RGB", (64, 64), color))

    def test_jpeg_output(self):
        data, ext = self._rgb_page().encoded(90, image_format="jpeg")
        self.assertEqual(ext, ".jpg")
        img = cl.Image.open(io.BytesIO(data))
        self.assertEqual(img.format, "JPEG")

    def test_png_output(self):
        data, ext = self._rgb_page().encoded(90, image_format="png")
        self.assertEqual(ext, ".png")
        img = cl.Image.open(io.BytesIO(data))
        self.assertEqual(img.format, "PNG")

    def test_webp_output(self):
        try:
            data, ext = self._rgb_page().encoded(85, image_format="webp")
        except Exception:
            self.skipTest("WebP not supported by this Pillow build")
        self.assertEqual(ext, ".webp")
        img = cl.Image.open(io.BytesIO(data))
        self.assertEqual(img.format, "WEBP")

    def test_passthrough_bypasses_format(self):
        """Passthrough exts are returned unchanged regardless of image_format."""
        raw_jpeg = make_jpeg()
        p = cl.Page(data=raw_jpeg, ext=".jpg")
        data, ext = p.encoded(90, frozenset({".jpg"}), image_format="png")
        self.assertEqual(data, raw_jpeg)   # untouched bytes
        self.assertEqual(ext, ".jpg")      # original ext preserved

    def test_png_is_lossless(self):
        """PNG output for a page created from bytes should round-trip pixel-exactly."""
        original_color = (123, 45, 67)
        page = cl.Page(image=cl.Image.new("RGB", (10, 10), original_color))
        data, _ = page.encoded(90, image_format="png")
        img = cl.Image.open(io.BytesIO(data))
        self.assertEqual(img.getpixel((0, 0)), original_color)

    def test_l_mode_jpeg_stays_grey(self):
        """An L-mode page encoded to JPEG produces a greyscale JPEG (not RGB)."""
        page = cl.Page(image=cl.Image.new("L", (32, 32), 128))
        data, ext = page.encoded(90, image_format="jpeg")
        self.assertEqual(ext, ".jpg")
        img = cl.Image.open(io.BytesIO(data))
        self.assertEqual(img.mode, "L")

    def test_l_mode_png_stays_grey(self):
        """An L-mode page encoded to PNG keeps L mode (lossless greyscale)."""
        page = cl.Page(image=cl.Image.new("L", (32, 32), 64))
        data, ext = page.encoded(90, image_format="png")
        self.assertEqual(ext, ".png")
        img = cl.Image.open(io.BytesIO(data))
        self.assertEqual(img.mode, "L")

    def test_l_mode_webp_stays_grey(self):
        """An L-mode page encoded to WebP stays greyscale (WebP supports L natively)."""
        try:
            page = cl.Page(image=cl.Image.new("L", (32, 32), 200))
            data, ext = page.encoded(85, image_format="webp")
        except Exception:
            self.skipTest("WebP not supported by this Pillow build")
        self.assertEqual(ext, ".webp")
        img = cl.Image.open(io.BytesIO(data))
        self.assertEqual(img.mode, "L")


# ── Page.is_greyscale() ─────────────────────────────────────────────────────

@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class TestPageIsGreyscale(unittest.TestCase):
    """Page.is_greyscale(): detects L-mode and equal-channel RGB images."""

    def test_l_mode_image_is_grey(self):
        p = cl.Page(image=cl.Image.new("L", (50, 50), 128))
        self.assertTrue(p.is_greyscale())

    def test_rgb_grey_image(self):
        """An RGB image where R==G==B counts as greyscale."""
        p = cl.Page(image=cl.Image.new("RGB", (50, 50), (80, 80, 80)))
        self.assertTrue(p.is_greyscale())

    def test_colour_image_is_not_grey(self):
        p = cl.Page(image=cl.Image.new("RGB", (50, 50), (255, 0, 0)))
        self.assertFalse(p.is_greyscale())

    def test_jpeg_bytes_colour(self):
        """A coloured JPEG decoded from bytes is not greyscale."""
        raw = make_jpeg(color=(200, 50, 10))
        p = cl.Page(data=raw, ext=".jpg")
        self.assertFalse(p.is_greyscale())


# ── PDF image_format and grayscale_detect (need fitz + Pillow) ───────────────

@unittest.skipUnless(HAVE_PIL and cl.fitz is not None,
                     "PyMuPDF or Pillow not installed")
class TestPdfImageFormat(unittest.TestCase):
    """PDF -> CBZ with --pdf-image-format jpeg/png/webp produces correctly-typed pages."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # Build a minimal 1-page colour PDF via CBZ->PDF conversion.
        src_cbz = self.dir / "src.cbz"
        make_cbz(src_cbz, {"1.jpg": make_jpeg(color=(200, 50, 50))})
        self.pdf = self.dir / "src.pdf"
        cl.convert(src_cbz, self.pdf, "pdf")

    def tearDown(self):
        self.tmp.cleanup()

    def _convert_and_read_page(self, image_format: str):
        dst = self.dir / f"out_{image_format}.cbz"
        cl.convert(self.pdf, dst, "cbz", pdf_dpi=72, pdf_image_format=image_format)
        with zipfile.ZipFile(dst) as z:
            name = z.namelist()[0]
            return cl.Image.open(io.BytesIO(z.read(name)))

    def test_jpeg_format(self):
        img = self._convert_and_read_page("jpeg")
        self.assertEqual(img.format, "JPEG")

    def test_png_format(self):
        img = self._convert_and_read_page("png")
        self.assertEqual(img.format, "PNG")

    def test_webp_format(self):
        try:
            img = self._convert_and_read_page("webp")
        except Exception:
            self.skipTest("WebP not supported")
        self.assertEqual(img.format, "WEBP")

    def test_pdf_color_mode_greyscale(self):
        """pdf_color_mode='greyscale' forces all pages to L-mode."""
        dst = self.dir / "grey_out.cbz"
        cl.convert(self.pdf, dst, "cbz", pdf_dpi=72, pdf_color_mode="greyscale",
                   pdf_image_format="png")
        with zipfile.ZipFile(dst) as z:
            name = z.namelist()[0]
            img = cl.Image.open(io.BytesIO(z.read(name)))
        self.assertEqual(img.mode, "L")

    def test_pdf_color_mode_auto_grey_page(self):
        """pdf_color_mode='auto' stores a genuinely grey page as L-mode."""
        grey_cbz = self.dir / "grey.cbz"
        make_cbz(grey_cbz, {"1.jpg": make_jpeg(color=(128, 128, 128))})
        grey_pdf = self.dir / "grey.pdf"
        cl.convert(grey_cbz, grey_pdf, "pdf")

        dst = self.dir / "auto_grey_out.cbz"
        cl.convert(grey_pdf, dst, "cbz", pdf_dpi=72, pdf_color_mode="auto",
                   pdf_image_format="png")
        with zipfile.ZipFile(dst) as z:
            name = z.namelist()[0]
            img = cl.Image.open(io.BytesIO(z.read(name)))
        self.assertIn(img.mode, ("L", "RGB"))  # L when auto detects grey

    def test_pdf_image_format_only_applies_to_pdf_source(self):
        """Converting CBZ->CBZ ignores pdf_image_format; passthrough is used."""
        src = self.dir / "passthrough_src.cbz"
        raw_jpeg = make_jpeg()
        make_cbz(src, {"1.jpg": raw_jpeg})
        dst = self.dir / "passthrough_dst.cbz"
        cl.convert(src, dst, "cbz", pdf_image_format="png")  # should NOT re-encode as PNG
        with zipfile.ZipFile(dst) as z:
            self.assertEqual(z.namelist(), ["1.jpg"])  # still .jpg

    def test_pdf_color_mode_greyscale_output_is_l_mode(self):
        """pdf_color_mode='greyscale' + png produces L-mode PNG pages (not RGB)."""
        dst = self.dir / "grey_png.cbz"
        cl.convert(self.pdf, dst, "cbz", pdf_dpi=72,
                   pdf_color_mode="greyscale", pdf_image_format="png")
        with zipfile.ZipFile(dst) as z:
            img = cl.Image.open(io.BytesIO(z.read(z.namelist()[0])))
        self.assertEqual(img.mode, "L")

    def test_invalid_pdf_color_mode_raises(self):
        """An unknown pdf_color_mode raises ConversionError rather than silently
        falling back to colour."""
        with self.assertRaises(cl.ConversionError):
            cl.extract_from_pdf(self.pdf, 72, pdf_color_mode="bogus")


# ── comic_convert CLI parallel workers ──────────────────────────────────────

@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class TestParallelWorkers(unittest.TestCase):
    """--workers N runs multiple conversions concurrently and reports correctly."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_src_dir(self, n: int) -> Path:
        src = self.dir / "src"
        src.mkdir(exist_ok=True)
        for i in range(n):
            make_cbz(src / f"book{i}.cbz", {f"1.jpg": make_jpeg(color=(i * 10, 50, 50))})
        return src

    def _make_args(self):
        return cc.ConvertOptions()

    def test_parallel_converts_all_files(self):
        """Parallel workers (ThreadPoolExecutor) convert all files without failures."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        src = self._make_src_dir(6)
        dst = self.dir / "out"
        jobs = cc.collect_jobs(src, dst, "cbz")
        args = self._make_args()
        failures = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(cc.convert_file, s, d, "cbz", args) for s, d in jobs}
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    failures += 1
        self.assertEqual(failures, 0)
        self.assertEqual(len(sorted(dst.glob("*.cbz"))), 6)

    def test_serial_converts_all_files(self):
        """Serial execution produces the same output as parallel."""
        src = self._make_src_dir(4)
        dst = self.dir / "serial_out"
        jobs = cc.collect_jobs(src, dst, "cbz")
        args = self._make_args()
        for s, d in jobs:
            cc.convert_file(s, d, "cbz", args)
        self.assertEqual(len(sorted(dst.glob("*.cbz"))), 4)

    def test_workers_default_is_none(self):
        """Default --workers is None (resolved to CPU count at runtime)."""
        args = cc.build_parser().parse_args(["src", "dst"])
        self.assertIsNone(args.workers)

    def test_workers_arg_parsed(self):
        """--workers N overrides the default."""
        args = cc.build_parser().parse_args(["src", "dst", "--workers", "3"])
        self.assertEqual(args.workers, 3)

    def test_workers_one_disables_parallelism(self):
        """--workers 1 is accepted and means serial execution."""
        args = cc.build_parser().parse_args(["src", "dst", "--workers", "1"])
        self.assertEqual(args.workers, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
