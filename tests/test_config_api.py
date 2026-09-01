"""/api/config's derived fields — orientation labels and the limits the frontend reads
instead of hardcoding its own copies (Product.md, user request: say whether a size is
portrait or landscape)."""


def test_orientation_is_correct_for_every_known_preset(client):
    sizes = {row["key"]: row for row in client.get("/api/config").json()["sizes"]}

    assert sizes["4:5"]["orientation"] == "portrait"
    assert sizes["3:4"]["orientation"] == "portrait"
    assert sizes["2:3"]["orientation"] == "portrait"
    assert sizes["16:9"]["orientation"] == "landscape"
    assert sizes["1:1"]["orientation"] == "square"


def test_orientation_agrees_with_the_real_width_and_height(client):
    for row in client.get("/api/config").json()["sizes"]:
        if row["width"] == row["height"]:
            assert row["orientation"] == "square"
        elif row["width"] < row["height"]:
            assert row["orientation"] == "portrait"
        else:
            assert row["orientation"] == "landscape"


def test_config_exposes_the_real_decoration_limit(client):
    from backend import config

    assert client.get("/api/config").json()["max_elements"] == config.MAX_ELEMENTS


def test_config_exposes_density_presets(client):
    from backend import config

    body = client.get("/api/config").json()
    assert body["default_density"] == config.DEFAULT_DENSITY
    keys = {row["key"] for row in body["densities"]}
    assert keys == set(config.DENSITY_PRESETS)
