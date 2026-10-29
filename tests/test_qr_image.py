import stat


def test_qr_image_written_as_private_png(tmp_path):
    from qr_auth import write_qr_image
    target = tmp_path / 'login.png'
    write_qr_image('https://passport.yandex.uz/qr?example=1', target)
    assert target.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
