"""Opt-in isolated local ComfyUI server. Never used by pytest; no downloads/API nodes."""
import argparse
import os
from pathlib import Path
import runpy
import sys

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--comfy-root', required=True)
    parser.add_argument('--port', default='8190')
    parser.add_argument('--release', choices=('v030','v031','v040'), default='v030')
    options = parser.parse_args()
    comfy = Path(options.comfy_root).resolve()
    repo = Path(__file__).resolve().parents[1]
    scratch = repo / ('.local-smoke-' + options.release)
    for name in ('user', 'output', 'temp'):
        (scratch / name).mkdir(parents=True, exist_ok=True)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
    sys.path.insert(0, str(comfy))
    sys.argv = [str(comfy / 'main.py'), '--port', options.port, '--listen', '127.0.0.1',
                '--disable-api-nodes', '--disable-all-custom-nodes', '--whitelist-custom-nodes', repo.name,
                '--user-directory', str(scratch / 'user'), '--output-directory', str(scratch / 'output'),
                '--temp-directory', str(scratch / 'temp'), '--database-url', 'sqlite:///:memory:', '--disable-auto-launch']
    if options.release=='v040':
        (scratch/'input').mkdir(exist_ok=True)
        sys.argv += ['--input-directory',str(scratch/'input')]
    import comfy.options
    comfy.options.enable_args_parsing()
    import folder_paths
    folder_paths.folder_names_and_paths['custom_nodes'] = ([str(repo.parent)], set())
    runpy.run_path(sys.argv[0], run_name='__main__')
