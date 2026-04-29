def test_health_no_auth(client):
    """Health endpoint is public (no auth required)."""
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_formats_no_auth(client):
    """Formats endpoint is public."""
    res = client.get("/api/v1/formats")
    assert res.status_code == 200
    data = res.json()
    assert "conversions" in data
    assert "compression" in data


def test_convert_no_key_allowed(client, sample_jpg):
    """Convert endpoint allows public access without an API key (rate-limited)."""
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    assert res.status_code == 200


def test_convert_wrong_key_rejected(client, sample_jpg):
    """Convert endpoint must reject requests with an invalid API key."""
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers={"X-API-Key": "wrong-key"},
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    assert res.status_code == 401
