import asyncio
import pytest
import lavka_uz


@pytest.mark.asyncio
async def test_selection_changes_default_status_and_explicit_override(monkeypatch):
    seen = []
    class Regional:
        def __init__(self, country, http): self.country = country
        async def status(self):
            seen.append(self.country)
            return {'country': self.country}
    monkeypatch.setattr('regional_storefront.RegionalStorefront', Regional)
    try:
        await lavka_uz.select_region('RU')
        assert (await lavka_uz.service_status())['country'] == 'RU'
        assert (await lavka_uz.service_status('KZ'))['country'] == 'KZ'
        assert (await lavka_uz.service_status())['country'] == 'RU'
    finally:
        await lavka_uz.select_region('UZ')
    assert seen == ['RU', 'KZ', 'RU']


@pytest.mark.asyncio
async def test_all_uz_tools_refuse_selected_ru_and_kz(monkeypatch):
    names = {t.name for t in await lavka_uz.mcp.list_tools()}
    allowed = {'select_region', 'service_status', 'search_products'}
    expected = {'delivery_location', 'detect_delivery_location', 'suggest_address', 'saved_address_count', 'get_cart', 'set_cart_item', 'saved_cards', 'order_history', 'active_orders', 'checkout_preview', 'saved_addresses', 'order_preview', 'submit_order', 'reconcile_checkout', 'cancel_order', 'login_start', 'qr_login_status', 'qr_login_cancel'}
    assert names - allowed == expected
    monkeypatch.setattr(lavka_uz, 'create_http', lambda: pytest.fail('must not touch UZ'))
    try:
        for region in ('RU', 'KZ'):
            await lavka_uz.select_region(region)
            for name in expected - {'qr_login_cancel'}:
                tool = lavka_uz.mcp._tool_manager.get_tool(name)
                # Call the registered wrapper directly, avoiding argument validation.
                with pytest.raises(ValueError, match='UZ-only'):
                    await tool.fn()
    finally:
        await lavka_uz.select_region('UZ')


@pytest.mark.asyncio
async def test_region_cannot_change_during_uz_operation(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    class Client:
        async def __aenter__(self):
            entered.set()
            await release.wait()
            return self
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(lavka_uz, 'create_http', Client)
    task = asyncio.create_task(lavka_uz.saved_address_count())
    await entered.wait()
    try:
        with pytest.raises(ValueError, match='in progress'):
            await lavka_uz.select_region('RU')
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    assert (await lavka_uz.select_region('UZ'))['country'] == 'UZ'


def test_startup_region_env_is_validated_and_process_scoped():
    import os, subprocess, sys
    code = "import lavka_uz; print(lavka_uz._selected_region)"
    def run(value):
        env = os.environ.copy()
        if value is None: env.pop('YANDEX_LAVKA_REGION', None)
        else: env['YANDEX_LAVKA_REGION'] = value
        return subprocess.run([sys.executable, '-c', code], env=env, text=True, capture_output=True)
    assert run(None).stdout.strip() == 'UZ'
    assert run('KZ').stdout.strip() == 'KZ'
    assert run('RU').stdout.strip() == 'RU'
    bad = run('XX')
    assert bad.returncode != 0 and 'YANDEX_LAVKA_REGION' in bad.stderr


@pytest.mark.asyncio
async def test_search_uses_selection_and_override(monkeypatch):
    class Regional:
        def __init__(self, country, http): self.country = country
        async def search(self, query, limit, longitude, latitude):
            return {'country': self.country}
    monkeypatch.setattr('regional_storefront.RegionalStorefront', Regional)
    try:
        await lavka_uz.select_region('KZ')
        assert (await lavka_uz.search_products('milk', longitude=1, latitude=1))['country'] == 'KZ'
        assert (await lavka_uz.search_products('milk', longitude=1, latitude=1, country='RU'))['country'] == 'RU'
        assert (await lavka_uz.search_products('milk', longitude=1, latitude=1))['country'] == 'KZ'
    finally:
        await lavka_uz.select_region('UZ')
