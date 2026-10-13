"""Export a verified committed submission, without credentials or publication."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(output, ffprobe):
    if git('status', '--porcelain'):
        raise SystemExit('Commit verified changes first; the Git checkout must be clean.')
    output = output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise SystemExit('Use an output directory outside the source repository.')
    output.mkdir(parents=True, exist_ok=True)
    commit = git('rev-parse', 'HEAD')
    copies = {
        'SovereignTradeCopilot_Report.pdf': ROOT/'track_2b/SovereignTradeCopilot_Report.pdf',
        'demo.mp4': ROOT/'track_2b/demo.mp4',
        'technical_report.md': ROOT/'track_2b/technical_report.md',
        'START_HERE.md': ROOT/'track_2b/docs/SUBMISSION.md',
        'PREVIEW.png': ROOT/'track_2b/docs/demo-video-source/assets/submission-preview.png',
    }
    pages = len(PdfReader(copies['SovereignTradeCopilot_Report.pdf']).pages)
    if not 1 <= pages <= 6:
        raise SystemExit(f'PDF page limit failed: {pages}')
    probe = json.loads(subprocess.check_output([
        ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json',
        str(copies['demo.mp4'])], text=True))
    video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    duration = float(probe['format']['duration'])
    if not 0 < duration <= 120:
        raise SystemExit(f'Video duration limit failed: {duration}')
    source_zip = output/'SOURCE.zip'
    subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=zip',
                    '--prefix=sovereign-trade-copilot/', '-o', str(source_zip),
                    commit], check=True)
    with zipfile.ZipFile(source_zip) as archive:
        if archive.testzip():
            raise SystemExit('Source archive CRC verification failed.')
        # Export committed bytes, including Markdown, rather than a checkout's
        # platform-specific LF/CRLF representation.
        for name, source in copies.items():
            entry = 'sovereign-trade-copilot/' + source.relative_to(ROOT).as_posix()
            (output/name).write_bytes(archive.read(entry))
        names = archive.namelist()
        for name in names:
            parts = Path(name).parts
            if any(p.lower() in {'.git', '_private', '.hyperframes', 'node_modules', '__pycache__'} for p in parts):
                raise SystemExit(f'Excluded storage entered archive: {name}')
            if Path(name).name.startswith('.env') and Path(name).name != '.env.example':
                raise SystemExit(f'Environment file entered archive: {name}')
        required = ['Makefile','LICENSE','README.md','track_2b/README.md',
                    'track_2b/Dockerfile','track_2b/Makefile',
                    'track_2b/SovereignTradeCopilot_Report.pdf','track_2b/demo.mp4']
        for name in required:
            if 'sovereign-trade-copilot/'+name not in names:
                raise SystemExit(f'Missing required source artifact: {name}')
        data_size = sum(i.file_size for i in archive.infolist()
                        if i.filename.startswith('sovereign-trade-copilot/track_2b/data/'))
        if data_size > 100_000_000:
            raise SystemExit('Track data exceeds 100 MB.')
    manifest = {
        'project': 'Sovereign Trade Copilot', 'track': '2B - Own Project',
        'prepared_on': '2026-10-13', 'source_commit': commit,
        'model': 'swiss-ai/Apertus-v1.5-70B', 'pipeline': 'light-harness-1.3',
        'report_pages': pages, 'video_seconds': duration,
        'video_codec': video['codec_name'], 'video_width': video['width'],
        'video_height': video['height'], 'video_frame_rate': video['avg_frame_rate'],
        'data_bytes': data_size, 'private_storage_excluded': True,
        'code_license': 'Apache-2.0', 'report_and_new_data_license': 'CC-BY-4.0',
        'video_disclosure': 'Recorded synthetic Apertus first drafts; scripted edit and approval; no sending.',
        'business_acceptance': 'Original B/E/E and later calibration failures remain; runtime PASS is not business PASS.',
        'publication': {'pushed': False, 'submitted': False, 'video_url': None,
                        'repository_url': 'https://github.com/quaner1234-cmd/sovereign-trade-copilot'},
        'files': {name: {'bytes': (output/name).stat().st_size, 'sha256': sha256(output/name)}
                  for name in [*copies, 'SOURCE.zip']},
    }
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    file_names = [*copies, 'SOURCE.zip', 'manifest.json']
    (output/'SHA256SUMS.txt').write_text(''.join(f'{sha256(output/name)}  {name}\n'
                                              for name in file_names), encoding='utf-8')
    bundle = output.parent/'SovereignTradeCopilot_Submission_20261013.zip'
    with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in [*file_names, 'SHA256SUMS.txt']:
            archive.write(output/name, arcname=output.name+'/'+name)
    with zipfile.ZipFile(bundle) as archive:
        if archive.testzip():
            raise SystemExit('Delivery archive CRC verification failed.')
    print(json.dumps({'archive': str(bundle), 'source_commit': commit,
                      'report_pages': pages, 'video_seconds': duration,
                      'data_bytes': data_size, 'pushed': False, 'submitted': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ffprobe', default='ffprobe')
    args = parser.parse_args()
    build(args.output, args.ffprobe)
