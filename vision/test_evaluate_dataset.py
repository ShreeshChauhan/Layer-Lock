import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import evaluate_dataset as batch
import evaluate_videos as ev
import download_test_videos as download


class DatasetTests(unittest.TestCase):
    def test_catalog_preserves_original_filenames(self):
        all_rows = download.planned_rows(download.catalog_selection())
        self.assertEqual(len(all_rows), 30)
        by_url = {r['source_url']:r for r in all_rows}
        for row in download.planned_rows():
            self.assertEqual(by_url[row['source_url']]['output_filename'],row['output_filename'])

    def test_onset_is_not_spaghetti_ground_truth(self):
        with tempfile.TemporaryDirectory(dir=batch.ROOT) as temporary:
            root = Path(temporary)
            output = root/'results'; folder = output/'sample'/'full_frame'
            folder.mkdir(parents=True)
            (root/'test_videos').mkdir()
            (root/'test_videos'/'sample.mp4').touch()
            batch.write_csv(root/'dataset_sequences.csv',[
                dict(sequence='sample',video_url='url1',onset_frame='120'),
                dict(sequence='missing',video_url='url2',onset_frame='200')])
            rows = []
            for seconds in [18,20,22]:
                row = dict.fromkeys(ev.FIELDS,'')
                row.update(clip_timestamp_seconds=str(seconds),spaghetti_detected='True',
                           highest_spaghetti_confidence='.8',source_timestamp_seconds=str(seconds+100))
                rows.append(row)
            batch.write_csv(folder/'frames.csv',rows)
            (folder/'summary.json').write_text(json.dumps(dict(status='ok',frames_analyzed=3,
                maximum_confidence=.8,average_inference_ms=10,roi_xywh=None)))
            manifest = {'sample.mp4':dict(dataset_label='sample',source_url='url1',
                output_filename='sample.mp4',onset_in_clip_seconds='20',failure_onset_seconds='120')}
            with patch.object(batch,'ROOT',root):
                batch.consolidate(output,manifest,{})
            with (output/'consolidated_evaluation.csv').open() as handle:
                summaries = list(csv.DictReader(handle))
            self.assertEqual(summaries[0]['before_positive'],'1')
            self.assertEqual(summaries[0]['after_positive'],'2')
            self.assertEqual(summaries[-1]['status'],'unavailable')
            self.assertEqual(summaries[-1]['spaghetti_frames'],'')
            with (output/'consolidated_frames.csv').open() as handle:
                frames = list(csv.DictReader(handle))
            self.assertTrue(all(f['human_ground_truth']=='' for f in frames))
            self.assertTrue(all(f['validation_label']=='unreviewed' for f in frames))


if __name__ == '__main__':
    unittest.main()
