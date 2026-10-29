"""Public runtime must not depend on excluded experiment scripts."""
import subprocess
import sys


def test_order_module_imports_without_experiment():
    code = '''
import sys
sys.modules["authorized_experiment"] = None
import lavka_order_mcp
assert lavka_order_mcp.GUARD.name == "fee-experiment-20261029.sqlite"
'''
    subprocess.run([sys.executable, "-c", code], check=True)
