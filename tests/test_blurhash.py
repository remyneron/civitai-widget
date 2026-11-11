from civitai_widget import blurhash


def test_decode_size_and_range():
    data = blurhash.decode("LEHV6nWB2yk8pyo0adR*.7kCMdnj", 16, 12)
    assert data is not None
    assert len(data) == 16 * 12 * 3


def test_decode_solid_colour_is_uniform():
    # A 1x1-component hash carries only the average colour.
    data = blurhash.decode("00OZZy", 4, 4)
    assert data is not None
    pixels = {data[i : i + 3] for i in range(0, len(data), 3)}
    assert len(pixels) == 1


def test_decode_rejects_garbage():
    assert blurhash.decode("") is None
    assert blurhash.decode("abc") is None
    assert blurhash.decode("LEHV6nWB2yk8pyo0adR*.7kCMdn") is None  # wrong length
    assert blurhash.decode("L!HV6nWB2yk8pyo0adR*.7kCMdnj") is None  # invalid character
