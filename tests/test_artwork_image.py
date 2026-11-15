from io import BytesIO
from unittest import TestCase
from pathlib import Path
from tempfile import TemporaryDirectory
from PIL import Image, ImageCms, PngImagePlugin
from apple_music_obs_overlay.artwork.image import normalize_artwork, MAX_ARTWORK_SIZE
from apple_music_obs_overlay.artwork.cache import ArtworkCache, MAX_CACHED_ARTWORK


def cover(index=0):
    out = BytesIO()
    Image.new('RGB', (4, 4), (index, 64, 32)).save(out, 'PNG')
    return out.getvalue()


class ArtworkImageTests(TestCase):
    def test_large_cover_is_resized_with_aspect_ratio(self):
        source = BytesIO()
        Image.new('RGB', (1200, 600), 'red').save(source, 'PNG')
        with Image.open(BytesIO(normalize_artwork(source.getvalue()))) as result:
            self.assertEqual(result.format, 'PNG')
            self.assertEqual(result.size, (MAX_ARTWORK_SIZE, MAX_ARTWORK_SIZE // 2))

    def test_animation_is_preserved_byte_for_byte(self):
        source = BytesIO()
        Image.new('RGB', (100, 100), 'red').save(source, 'GIF', save_all=True,
            append_images=[Image.new('RGB', (100, 100), 'blue')], duration=50, loop=0)
        normalized = normalize_artwork(source.getvalue())
        self.assertEqual(normalized, source.getvalue())
        with Image.open(BytesIO(normalized)) as result:
            self.assertTrue(result.is_animated)
            self.assertEqual(result.n_frames, 2)

    def test_color_profile_and_decoded_pixels_are_preserved(self):
        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        source = BytesIO()
        Image.new('RGB', (64, 64), (128, 64, 32)).save(source, 'PNG', icc_profile=icc)
        with Image.open(BytesIO(source.getvalue())) as original:
            expected = original.convert('RGBA').tobytes()
        with Image.open(BytesIO(normalize_artwork(source.getvalue()))) as result:
            self.assertEqual(result.info['icc_profile'], icc)
            self.assertEqual(result.tobytes(), expected)

    def test_small_jpeg_keeps_original_encoding(self):
        source = BytesIO()
        Image.new('RGB', (600, 600), (128, 64, 32)).save(source, 'JPEG', quality=91)
        self.assertEqual(normalize_artwork(source.getvalue()), source.getvalue())

    def test_transparency_is_not_flattened(self):
        image = Image.new('RGBA', (3, 1))
        image.putdata([(32, 64, 96, 0), (64, 96, 128, 127), (96, 128, 160, 255)])
        source = BytesIO()
        image.save(source, 'PNG')
        with Image.open(BytesIO(normalize_artwork(source.getvalue()))) as result:
            self.assertEqual(result.tobytes(), image.tobytes())

    def test_nonvisual_metadata_does_not_change_normalized_content(self):
        results = []
        for value in ['old', 'new']:
            source = BytesIO()
            meta = PngImagePlugin.PngInfo()
            meta.add_text('Comment', value)
            Image.new('RGB', (4, 4), 'red').save(source, 'PNG', pnginfo=meta)
            results.append(normalize_artwork(source.getvalue()))
        self.assertEqual(*results)

    def test_lab_profile_is_converted_before_saving_png(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('LAB'))
        target = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
        original = Image.new('LAB', (4, 4), (128, 128, 128))
        expected = ImageCms.profileToProfile(original, profile, target, outputMode='RGB')
        source = BytesIO()
        original.save(source, 'TIFF', icc_profile=profile.tobytes())
        with Image.open(BytesIO(normalize_artwork(source.getvalue()))) as result:
            self.assertEqual(result.convert('RGB').tobytes(), expected.tobytes())
            self.assertEqual(result.info['icc_profile'], target.tobytes())

    def test_exif_orientation_is_applied_once(self):
        source = BytesIO()
        exif = Image.Exif()
        exif[274] = 6
        Image.new('RGB', (1200, 600), 'red').save(source, 'JPEG', exif=exif)
        with Image.open(BytesIO(normalize_artwork(source.getvalue()))) as result:
            self.assertEqual(result.size, (MAX_ARTWORK_SIZE // 2, MAX_ARTWORK_SIZE))
            self.assertNotIn(274, result.getexif())

    def test_invalid_data_is_rejected(self):
        with self.assertRaises(OSError):
            normalize_artwork(b'not an image')

    def test_16_bit_grayscale_is_not_clipped_to_white(self):
        source = BytesIO()
        Image.new('I;16', (32, 32), 32768).save(source, 'PNG')
        self.assertEqual(normalize_artwork(source.getvalue()), source.getvalue())

    def test_palette_transparency_is_resampled_with_alpha(self):
        image = Image.new('P', (1200, 600))
        image.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
        image.paste(1, (600, 0, 1200, 600))
        source = BytesIO()
        image.save(source, 'PNG', transparency=0)
        with Image.open(BytesIO(normalize_artwork(source.getvalue()))) as result:
            alphas = set(result.getchannel('A').getdata())
            self.assertTrue(any(0 < value < 255 for value in alphas))

    def test_invalid_cmyk_profile_does_not_discard_a_valid_cover(self):
        source = BytesIO()
        Image.new('CMYK', (1200, 600), (0, 128, 255, 0)).save(source, 'JPEG', icc_profile=b'broken')
        with Image.open(BytesIO(normalize_artwork(source.getvalue()))) as result:
            self.assertEqual(result.format, 'PNG')
            self.assertNotIn('icc_profile', result.info)
            self.assertEqual(result.size, (MAX_ARTWORK_SIZE, MAX_ARTWORK_SIZE // 2))

    def test_content_url_is_stable_after_other_covers_and_file_is_not_rewritten(self):
        with TemporaryDirectory() as tmp:
            cache = ArtworkCache(Path(tmp))
            first = cache.publish(cover(1))
            modified = (Path(tmp) / first[0]).stat().st_mtime_ns
            cache.publish(cover(2))
            self.assertEqual(cache.publish(cover(1)), first)
            self.assertEqual((Path(tmp) / first[0]).stat().st_mtime_ns, modified)

    def test_cache_bounds_files_and_preserves_diagnostic_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            diagnostic = root / 'cover_direct.jpg'
            diagnostic.write_bytes(b'raw diagnostic')
            legacy = root / ('cover_' + '0' * 64 + '.jpg')
            legacy.write_bytes(b'legacy cover')
            cache = ArtworkCache(root)
            first = cache.publish(cover())
            for i in range(1, MAX_CACHED_ARTWORK + 10):
                cache.publish(cover(i))
            self.assertEqual(len(list(root.glob('cover_*.*'))), MAX_CACHED_ARTWORK + 1)
            self.assertFalse((root / first[0]).exists())
            self.assertFalse(legacy.exists())
            self.assertEqual(diagnostic.read_bytes(), b'raw diagnostic')
            self.assertEqual(cache.publish(cover()), first)
            gif = BytesIO()
            Image.new('RGB', (4, 4), 'red').save(gif, 'GIF')
            published, _ = cache.publish(gif.getvalue())
            self.assertTrue(published.endswith('.gif'))
            self.assertEqual((root / published).read_bytes(), gif.getvalue())
