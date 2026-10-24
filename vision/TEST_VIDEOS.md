# LayerLock failure clips

Run from the repository root with Python 3.10 or newer:

```powershell
python -m pip install -U yt-dlp
# Install FFmpeg (including ffprobe), then reopen your terminal if PATH changed.
winget install --id Gyan.FFmpeg --exact
ffmpeg -version
ffprobe -version
python vision/download_test_videos.py
```

Use `python vision/download_test_videos.py --plan` to generate the initial CSV
without downloads (does not overwrite an existing manifest). Rerun normally to
retry failed clips; existing clips are decoded and duration-checked before reuse.
Use `--overwrite` to regenerate them. Exit codes: 0 success, 1 per-video failure,
2 missing dependencies, 130 interruption. A supported JavaScript runtime may also
be required by current yt-dlp YouTube extraction; follow yt-dlp's official setup
documentation if its diagnostics request one: https://github.com/yt-dlp/yt-dlp#installation.

Outputs are video-only H.264 MP4s in `vision/test_videos/`, with no resizing.
The tracked `vision/test_videos_manifest.csv` records source links, dataset labels,
annotations, intended/actual ranges, filenames, status, and errors. A planned row
is not evidence of a downloaded video. Temporary downloads stay inside the output
directory and are cleaned up after each attempt. Only five sources are attempted;
unavailable sources are reported rather than silently substituted.

## Provenance and interpretation

Source inspected October 23, 2026:

- URLs and display labels: https://github.com/EmptyDeck/3DPrint-Failure-Video-Dataset/blob/master/video_links.md
- Exact onset frames, fps, and lengths: https://github.com/EmptyDeck/3DPrint-Failure-Video-Dataset/blob/master/metadata/sequences.csv
- Annotation definition and license: https://github.com/EmptyDeck/3DPrint-Failure-Video-Dataset/blob/master/README.md

Attribution: EmptyDeck, *Bed-Adhesion Failure-Onset Dataset for FDM 3D Printing*.
The README specifies CC BY-NC 4.0 for annotations and externally hosted research
videos: https://creativecommons.org/licenses/by-nc/4.0/ . Retain this attribution
and the source manifest with derived clips. These derivatives are trimmed,
re-encoded, and have audio removed. Commercial use requires separate permission;
this dataset is not automatically suitable for commercial product testing.

The dataset annotates the first visible movement of the printed object, a
bed-adhesion failure. It does not provide spaghetti labels or spaghetti onset
times. No clear spaghetti failures were established from these annotations.
The five earliest onsets were selected instead; their category is the dataset's
bed-adhesion category, not an independently verified visual spaghetti label.
Metadata and display labels sometimes differ, so selection joins on YouTube ID.
At 1 fps, the zero-based onset frame equals seconds; do not subtract one.

| Display label | Metadata label | Onset (s) | Planned range (s) |
| --- | --- | ---: | --- |
| PinkNetriti | PinkNetriti_Early | 49 | 29–89 |
| YellowEarly | YellowEarly | 120 | 100–160 |
| WhiteHorseback | WhiteHorseback | 262 | 242–302 |
| BlackEarly | BlackTilt_noz | 312 | 292–352 |
| P2RedSkull | RedSkullEarly | 317 | 297–357 |

Normally the range is onset minus 20 through onset plus 40. At either video
boundary it shifts to preserve 60 seconds where possible; videos shorter than
60 seconds use their full duration. The CSV records the resulting onset position.
An out-of-range onset or hosted duration differing from annotation duration by
more than two seconds is rejected to avoid silently misaligned footage. Matching
duration does not prove visual alignment: inspect the resulting clips before
using them as a benchmark. FFprobe checks length and a full FFmpeg decode checks
that each output is readable before it receives successful status.

The script uses public, unauthenticated access only, ignores user yt-dlp config,
and supplies no cookies, credentials, DRM options, geo-bypass options, or access
workarounds. Restricted/unavailable videos fail individually. Do not work around
host download restrictions; obtain authorized original files from the owner if
public downloads are unavailable.

## Verification in this workspace

The execution environment has Python but lacks yt-dlp, FFmpeg, and FFprobe.
Shell access to GitHub failed DNS resolution. The script was therefore tested
offline; no MP4 downloads have been verified here. Run the commands above on a
machine with the dependencies and permitted network access.

Offline logic checks:

```powershell
python -m unittest discover -s vision -p test_download_test_videos.py
```
