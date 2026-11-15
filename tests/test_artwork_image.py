from io import BytesIO
from unittest import TestCase
from pathlib import Path
from tempfile import TemporaryDirectory
from PIL import Image
from apple_music_obs_overlay.artwork.image import normalize_artwork, MAX_ARTWORK_SIZE
from apple_music_obs_overlay.artwork.cache import ArtworkCache, MAX_CACHED_ARTWORK


class ArtworkImageTests(TestCase):
    def test_large_cover_is_resized_with_aspect_ratio(self):
        source = BytesIO()
        Image.new('RGB', (1200, 600), 'red').save(source, 'PNG')
        with Image.open(BytesIO(normalize_artwork(source.getvalue()))) as result:
            self.assertEqual(result.format, 'JPEG')
            self.assertEqual(result.size, (MAX_ARTWORK_SIZE, MAX_ARTWORK_SIZE // 2))

    def test_animation_becomes_a_single_frame(self):
        source = BytesIO()
        Image.new('RGB', (100, 100), 'red').save(source, 'GIF', save_all=True,
            append_images=[Image.new('RGB', (100, 100), 'blue')], duration=50, loop=0)
        with Image.open(BytesIO(normalize_artwork(source.getvalue()))) as result:
            self.assertEqual(result.format, 'JPEG')
            self.assertFalse(getattr(result, 'is_animated', False))
            red, green, blue = result.getpixel((50, 50))
            self.assertGreater(red, 200)
            self.assertLess(blue, 30)

    def test_invalid_data_is_rejected(self):
        with self.assertRaises(OSError):
            normalize_artwork(b'not an image')

    def test_content_url_is_stable_after_other_covers_and_file_is_not_rewritten(self):
        with TemporaryDirectory() as tmp:
            cache = ArtworkCache(Path(tmp))
            first = cache.publish(b'first image')
            modified = (Path(tmp) / first[0]).stat().st_mtime_ns
            cache.publish(b'second image')
            self.assertEqual(cache.publish(b'first image'), first)
            self.assertEqual((Path(tmp) / first[0]).stat().st_mtime_ns, modified)

    def test_cache_bounds_files_and_preserves_diagnostic_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            diagnostic = root / 'cover_direct.jpg'
            diagnostic.write_bytes(b'raw diagnostic')
            cache = ArtworkCache(root)
            first = cache.publish(b'0')
            for i in range(1, MAX_CACHED_ARTWORK + 10):
                cache.publish(str(i).encode())
            self.assertEqual(len(list(root.glob('cover_*.jpg'))), MAX_CACHED_ARTWORK + 1)
            self.assertFalse((root / first[0]).exists())
            self.assertEqual(diagnostic.read_bytes(), b'raw diagnostic')
            self.assertEqual(cache.publish(b'0'), first)
