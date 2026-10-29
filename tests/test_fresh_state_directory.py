import os
import subprocess
import sys
import textwrap
import pytest


@pytest.mark.parametrize('first', ['guard', 'preview', 'cancel'])
def test_custom_session_fresh_home_initializes_all_order_state(tmp_path, first):
    home = tmp_path / 'home'
    home.mkdir()
    custom = tmp_path / 'custom' / 'session.json'
    script = textwrap.dedent('''
        import asyncio
        import os
        import stat
        from pathlib import Path
        import httpx
        import lavka_order_mcp as orders
        import lavka_uz

        async def bootstrap(self):
            self.props = {'pageData': {'passportInfo': {'status': 'VALID'}}}
            return self.props
        lavka_uz.Lavka.bootstrap = bootstrap
        async def history():
            return {'orders': [{'order_id': 'test', 'status': 'canceled'}]}
        async def run():
            actions = [os.environ['FIRST_STATE']] + [x for x in ('guard', 'preview', 'cancel') if x != os.environ['FIRST_STATE']]
            for action in actions:
                if action == 'guard':
                    with orders._guard_db() as db:
                        pass
                elif action == 'preview':
                    with orders._db() as db:
                        pass
                else:
                    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))) as http:
                        result = await orders.cancel(http, 'test', True, history)
                        assert result['outcome'] == 'canceled'
        asyncio.run(run())
        state = Path.home() / '.local/share/yandex-lavka-mcp'
        assert stat.S_IMODE(state.stat().st_mode) == 0o700
        for path in (orders.GUARD, orders.STATE, orders.CANCEL_STATE):
            assert path.is_file()
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
    ''')
    env = os.environ.copy()
    env.update(HOME=str(home), YANDEX_SESSION_FILE=str(custom), FIRST_STATE=first)
    subprocess.run([sys.executable, '-c', script], env=env, check=True)


@pytest.mark.parametrize('kind', ['symlink', 'public', 'file'])
def test_unsafe_existing_state_directory_is_rejected_without_modification(tmp_path, kind):
    home = tmp_path / 'home'
    directory = home / '.local/share/yandex-lavka-mcp'
    directory.parent.mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.mkdir(mode=0o700)
    if kind == 'symlink':
        directory.symlink_to(outside, target_is_directory=True)
    elif kind == 'file':
        directory.write_text('keep')
    else:
        directory.mkdir(mode=0o755)
        directory.chmod(0o755)
    env = os.environ.copy()
    env.update(HOME=str(home), YANDEX_SESSION_FILE=str(tmp_path / 'custom/session.json'))
    script = """\
import lavka_order_mcp as orders
try:
    orders._guard_db()
except (ValueError, OSError):
    pass
else:
    raise AssertionError('unsafe directory accepted')
"""
    subprocess.run([sys.executable, '-c', script], env=env, check=True)
    assert not list(outside.iterdir())
    if kind == 'public':
        assert directory.stat().st_mode & 0o777 == 0o755
    elif kind == 'file':
        assert directory.read_text() == 'keep'
    else:
        assert directory.is_symlink()
