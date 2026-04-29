def test_txt_to_pdf(client, auth_headers, sample_txt):
    with sample_txt.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.txt", f, "text/plain")},
            data={"target_format": "pdf"},
        )
    assert res.status_code == 200
    # PDF files start with %PDF
    assert res.content[:4] == b"%PDF"
