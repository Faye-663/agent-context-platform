from pathlib import Path


def test_playground_renders_untrusted_payloads_without_inner_html() -> None:
    app_js = (Path(__file__).parents[1] / "playground" / "app.js").read_text(
        encoding="utf-8"
    )

    assert "innerHTML" not in app_js
    assert "wire: { request: requestBody, response: responseBody }" in app_js
