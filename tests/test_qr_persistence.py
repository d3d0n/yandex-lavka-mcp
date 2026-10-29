import json
import os
import stat

import httpx
import pytest


@pytest.mark.asyncio
async def test_save_uz_session_round_trips_cookies_without_domain_widening(tmp_path, monkeypatch):
    import lavka_uz
    from qr_auth import save_session
    async with httpx.AsyncClient() as http:
        http.cookies.set('Session_id', 'sensitive', domain='.yandex.uz', path='/')
        http.cookies.set('ru_only', 'sensitive', domain='.yandex.ru', path='/')
        target = tmp_path / 'state.json'
        save_session(http, target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    monkeypatch.setattr(lavka_uz, 'STATE', str(target))
    restored = lavka_uz.create_http()
    assert 'Session_id=sensitive' in restored.build_request('GET', 'https://lavka.yandex.uz/').headers['cookie']
    assert 'ru_only' not in restored.build_request('GET', 'https://lavka.yandex.uz/').headers['cookie']
    assert 'Session_id' not in restored.build_request('GET', 'https://yandex.ru/').headers['cookie']
    await restored.aclose()
