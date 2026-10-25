"""Offline checks for annotation conversion, boundaries, and failure isolation."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision.src import download_test_videos as downloader


class DownloadTests(unittest.TestCase):
    def test_ranges(self):
        self.assertEqual(downloader.clip_range(100, 500), (80, 140))
        self.assertEqual(downloader.clip_range(5, 500), (0, 60))
        self.assertEqual(downloader.clip_range(490, 500), (440, 500))
        self.assertEqual(downloader.clip_range(15, 30), (0, 30))
        for onset, duration in [(-1, 30), (30, 30), (0, 0), (float('nan'), 60)]:
            with self.assertRaises(ValueError):
                downloader.clip_range(onset, duration)

    def test_manifest(self):
        rows = downloader.planned_rows()
        self.assertEqual(len(rows), 5)
        self.assertEqual(len({r['output_filename'] for r in rows}), 5)
        self.assertEqual(rows[0]['failure_onset_seconds'], 49)
        for row in rows:
            self.assertEqual(row['clip_end_seconds'] - row['clip_start_seconds'], 60)
            self.assertEqual(row['onset_in_clip_seconds'], 20)
            self.assertEqual(row['status'], 'planned')

    def test_failure_does_not_stop_remaining_sources(self):
        with tempfile.TemporaryDirectory(dir=downloader.ROOT) as folder:
            with patch.object(downloader, 'OUTPUT', Path(folder)), \
                 patch.object(downloader, 'MANIFEST', Path(folder) / 'manifest.csv'), \
                 patch.object(downloader.shutil, 'which', return_value='found'), \
                 patch.object(downloader.importlib.util, 'find_spec', return_value=True), \
                 patch.object(downloader, 'process', side_effect=RuntimeError('Unavailable')) as process, \
                 patch.object(downloader, 'write_manifest') as manifest, \
                 patch('sys.argv', ['download_test_videos.py']), \
                 contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(downloader.main(), 1)
                self.assertEqual(process.call_count, 5)
                self.assertEqual(manifest.call_count, 5)
                self.assertTrue(all(r['status'] == 'failed' for r in manifest.call_args.args[0]))


if __name__ == '__main__':
    unittest.main()
