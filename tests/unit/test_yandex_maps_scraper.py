from pipeline.geocoding.providers.yandex_maps import YandexMapsScraper


def test_extract_first_business_address_from_maps_html() -> None:
    html = (
        '<script>{"items":[{"type":"business","title":"Crocus City Hall",'
        '"address":"Krasnogorsk, Mezhdunarodnaya Street, 20"}]}</script>'
    )
    assert (
        YandexMapsScraper.extract_first_business_address(html)
        == "Krasnogorsk, Mezhdunarodnaya Street, 20"
    )


def test_extract_first_business_address_decodes_escaped_chars() -> None:
    html = '<script>{"items":[{"type":"business","address":"Line 1, \\"Building A\\""}]}</script>'
    assert YandexMapsScraper.extract_first_business_address(html) == 'Line 1, "Building A"'


def test_extract_business_addresses_returns_deduplicated_list() -> None:
    html = (
        '<script>{"items":['
        '{"type":"business","address":"Addr 1"},'
        '{"type":"business","address":"Addr 2"},'
        '{"type":"business","address":"Addr 1"}'
        "]}</script>"
    )
    assert YandexMapsScraper.extract_business_addresses(html, limit=5) == ["Addr 1", "Addr 2"]


def test_extract_first_business_address_returns_none_when_missing() -> None:
    html = '<script>{"items":[{"type":"category","address":"Somewhere"}]}</script>'
    assert YandexMapsScraper.extract_first_business_address(html) is None


def test_is_captcha_page_detects_yandex_captcha_markup() -> None:
    html = "<html><title>Are you not a robot?</title><form action='/checkcaptcha'></form></html>"
    assert YandexMapsScraper._is_captcha_page(html) is True
