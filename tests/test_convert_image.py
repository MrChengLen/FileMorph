# SPDX-License-Identifier: AGPL-3.0-or-later


def test_png_to_jpg(client, auth_headers, sample_png):
    with sample_png.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.png", f, "image/png")},
            data={"target_format": "jpg"},
        )
    assert res.status_code == 200
