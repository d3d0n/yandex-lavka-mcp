import subprocess
import sys


def test_qr_modules_import_in_fresh_interpreters():
    for name in ('qr_runtime', 'qr_auth', 'qr_mcp', 'lavka_uz'):
        result = subprocess.run([sys.executable, '-c', f'import {name}'], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
