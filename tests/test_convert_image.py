# SPDX-License-Identifier: AGPL-3.0-or-later
def test_jpg_to_png(client, auth_headers, sample_jpg):
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/octet-stream"
    assert len(res.content) > 0


def test_jpg_to_webp(client, auth_headers, sample_jpg):
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "webp", "quality": "80"},
        )
    assert res.status_code == 200


def test_png_to_jpg(client, auth_headers, sample_png):
    with sample_png.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.png", f, "image/png")},
            data={"target_format": "jpg"},
        )
    assert res.status_code == 200


def test_unsupported_conversion(client, auth_headers, sample_jpg):
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "docx"},  # not supported
        )
    assert res.status_code == 422


def test_compress_image(client, auth_headers, sample_jpg):
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/compress",
            headers=auth_headers,
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"quality": "60"},
        )
    assert res.status_code == 200
    assert len(res.content) > 0
