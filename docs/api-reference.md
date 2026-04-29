# API Reference

FileMorph provides a REST API for programmatic file conversion and compression.
All responses are either a file download (`application/octet-stream`) or JSON.

**Base URL**: `http://localhost:8000/api/v1`

---

## Authentication

All endpoints except `/health` and `/formats` require an API key in the request header:

```
X-API-Key: your-api-key-here
```

Generate a key with:
```bash
python scripts/generate_api_key.py
# or via Docker:
docker compose exec filemorph python scripts/generate_api_key.py
```

Keys are stored as SHA-256 hashes in `data/api_keys.json`. The plaintext key is shown exactly once at generation time.

---

## Endpoints

### POST `/api/v1/convert`

Convert a file from one format to another.

**Authentication**: Required (`X-API-Key` header)

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | The file to convert |
| `target_format` | string | Yes | Target format extension, e.g. `jpg`, `pdf`, `mp3` |
| `quality` | integer | No | Quality 1–100 (default: 85). Applies to lossy formats (JPEG, WebP, video) |

**Response**: `200 OK` — the converted file as a download

**Example — HEIC to JPG**
```bash
curl -X POST http://localhost:8000/api/v1/convert \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@photo.heic" \
  -F "target_format=jpg" \
  -F "quality=90" \
  --output photo.jpg
```

**Example — DOCX to PDF**
```bash
curl -X POST http://localhost:8000/api/v1/convert \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@document.docx" \
  -F "target_format=pdf" \
  --output document.pdf
```

**Example — Python (requests)**
```python
import requests

key = "YOUR_KEY"
with open("photo.heic", "rb") as f:
    response = requests.post(
        "http://localhost:8000/api/v1/convert",
        headers={"X-API-Key": key},
        files={"file": ("photo.heic", f, "image/heic")},
        data={"target_format": "jpg", "quality": 85},
    )

with open("photo.jpg", "wb") as out:
    out.write(response.content)
```

**Example — JavaScript (fetch)**
```javascript
const formData = new FormData();
formData.append("file", fileInput.files[0]);
formData.append("target_format", "jpg");
formData.append("quality", "85");

const response = await fetch("http://localhost:8000/api/v1/convert", {
  method: "POST",
  headers: { "X-API-Key": "YOUR_KEY" },
  body: formData,
});

const blob = await response.blob();
const url = URL.createObjectURL(blob);
// use url for download link
```

---

### POST `/api/v1/compress`

Reduce a file's size by re-encoding at a lower quality, keeping the same format.

**Authentication**: Required (`X-API-Key` header)

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | The file to compress |
| `quality` | integer | No | Quality 1 (smallest) – 100 (best). Defaults to 85. Mutually exclusive with `target_size_kb` |
| `target_size_kb` | integer | No | Target output size in KB. Activates binary-search-on-quality (JPEG/WebP only). Mutually exclusive with `quality` |

**Supported formats**: JPG, JPEG, PNG, WebP, TIFF · MP4, MOV, AVI, MKV, WebM

`target_size_kb` is JPEG/WebP only — PNG/TIFF are lossless and quality does not control size meaningfully. Sending `target_size_kb` with a PNG returns `415`.

**Response**: `200 OK` — the compressed file as a download (same format, `_compressed` suffix in filename).

When `target_size_kb` is set, the response also carries:

| Header | Description |
|---|---|
| `X-FileMorph-Achieved-Bytes` | Actual output size in bytes |
| `X-FileMorph-Final-Quality` | Quality value the search settled on (1–100) |

Tolerance is ±3 % of the requested target. If even quality `1` exceeds the target, the smallest possible output is returned anyway and the headers reveal the actual size.

**Example — Compress a JPG to 70% quality**
```bash
curl -X POST http://localhost:8000/api/v1/compress \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@large_photo.jpg" \
  -F "quality=70" \
  --output smaller_photo.jpg
```

**Example — Compress a JPG to a 500 KB target**
```bash
curl -X POST http://localhost:8000/api/v1/compress \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@large_photo.jpg" \
  -F "target_size_kb=500" \
  -D headers.txt \
  --output capped_photo.jpg

# headers.txt now contains X-FileMorph-Achieved-Bytes / X-FileMorph-Final-Quality
```

**Example — Compress a video**
```bash
curl -X POST http://localhost:8000/api/v1/compress \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@recording.mp4" \
  -F "quality=60" \
  --output recording_compressed.mp4
```

**Quality guide for images**

| Quality | Typical size reduction | Visual difference |
|---|---|---|
| 90 | ~20% | Nearly invisible |
| 80 | ~40% | Very subtle |
| 70 | ~55% | Slightly noticeable on close inspection |
| 60 | ~65% | Noticeable, acceptable for web thumbnails |
| 50 | ~70% | Clearly visible, good for previews |

---

### GET `/api/v1/formats`

Returns all supported conversion and compression formats.

**Authentication**: Not required

**Response**: `200 OK` — JSON

```json
{
  "conversions": {
    "jpg": ["png", "webp", "bmp", "tiff", "gif"],
    "heic": ["jpg", "png", "webp"],
    "docx": ["pdf", "txt"],
    "txt": ["pdf"],
    "csv": ["xlsx", "json"],
    "mp4": ["avi", "mov", "mkv", "webm"],
    "mp3": ["wav", "flac", "ogg", "m4a"]
  },
  "compression": {
    "image": ["jpg", "jpeg", "png", "webp", "tiff"],
    "video": ["mp4", "avi", "mov", "mkv", "webm"]
  }
}
```

Use this endpoint to populate format selection dropdowns in your application.

---

### GET `/api/v1/health`

Health check for monitoring and load balancer probes.

**Authentication**: Not required

**Response**: `200 OK` — JSON

```json
{
  "status": "ok",
  "version": "1.0.0",
  "ffmpeg_available": true
}
```

`ffmpeg_available: false` means video and audio operations will fail — check your system setup.

---

## Error Responses

All errors return JSON with a `detail` field:

```json
{
  "detail": "Conversion from 'jpg' to 'docx' is not supported."
}
```

| HTTP Status | Meaning |
|---|---|
| `400 Bad Request` | Missing or malformed request data (e.g. filename without extension) |
| `401 Unauthorized` | Missing or invalid `X-API-Key` |
| `413 Request Entity Too Large` | File exceeds `MAX_UPLOAD_SIZE_MB` (default: 100 MB) |
| `422 Unprocessable Entity` | Unsupported format combination, or missing form field |
| `429 Too Many Requests` | Rate limit exceeded (see Rate Limiting section below) |
| `500 Internal Server Error` | Conversion failed (e.g. corrupt file, missing binary) |

---

## Rate Limiting

Per-route limits (per IP address):

| Endpoint | Limit |
|---|---|
| `POST /api/v1/convert` | 10 / minute |
| `POST /api/v1/convert/batch` | 3 / minute |
| `POST /api/v1/compress` | 10 / minute |
| `POST /api/v1/compress/batch` | 3 / minute |
| `GET /api/v1/health` | 30 / minute |
| `GET /api/v1/formats` | 120 / minute |
| Auth endpoints (`/api/v1/auth/*`) | 3–5 / minute |
| Default (other routes) | 60 / minute |

When exceeded, the response is `429 Too Many Requests`. For higher
limits, self-host your own instance and adjust the decorators in
`app/api/routes/*.py` (slowapi `@limiter.limit("…/minute")`).

---

## Swagger / OpenAPI

FileMorph auto-generates interactive API documentation:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

The Swagger UI lets you test all endpoints directly in the browser.

---

## Integration Examples

### PHP

```php
$ch = curl_init('http://localhost:8000/api/v1/convert');
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => ['X-API-Key: YOUR_KEY'],
    CURLOPT_POSTFIELDS => [
        'file' => new CURLFile('/path/to/photo.heic', 'image/heic', 'photo.heic'),
        'target_format' => 'jpg',
        'quality' => '85',
    ],
]);
$result = curl_exec($ch);
file_put_contents('/path/to/photo.jpg', $result);
```

### Node.js

```javascript
const FormData = require('form-data');
const fs = require('fs');
const axios = require('axios');

const form = new FormData();
form.append('file', fs.createReadStream('document.docx'));
form.append('target_format', 'pdf');

const response = await axios.post(
  'http://localhost:8000/api/v1/convert',
  form,
  {
    headers: { ...form.getHeaders(), 'X-API-Key': 'YOUR_KEY' },
    responseType: 'arraybuffer',
  }
);
fs.writeFileSync('document.pdf', response.data);
```

### C# / .NET

```csharp
using var client = new HttpClient();
client.DefaultRequestHeaders.Add("X-API-Key", "YOUR_KEY");

using var form = new MultipartFormDataContent();
form.Add(new StreamContent(File.OpenRead("photo.heic")), "file", "photo.heic");
form.Add(new StringContent("jpg"), "target_format");

var response = await client.PostAsync(
    "http://localhost:8000/api/v1/convert", form);
await File.WriteAllBytesAsync("photo.jpg", await response.Content.ReadAsByteArrayAsync());
```
