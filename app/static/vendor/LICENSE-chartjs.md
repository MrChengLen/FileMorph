# Chart.js — MIT License

FileMorph vendors `chart.umd.min.js` from Chart.js **v4.4.0**
(https://github.com/chartjs/Chart.js), distributed under the MIT License.
The bundle is used read-only by `app/templates/cockpit.html` for rendering
admin dashboard charts. No modifications were made to the upstream file.

- Upstream source: https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js
- SHA-256 (this copy): `0e2326c6868072bec1592760c6729043caeea2960a2b46cee6a2192aac6abff0`

## Upstream license text

```
The MIT License (MIT)

Copyright (c) 2014-2022 Chart.js Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## Updating

To update to a newer Chart.js release:

```bash
curl -sSL -o app/static/vendor/chart.umd.min.js \
  https://cdn.jsdelivr.net/npm/chart.js@<NEW_VERSION>/dist/chart.umd.min.js
python -c "import hashlib, pathlib; \
  print(hashlib.sha256(pathlib.Path('app/static/vendor/chart.umd.min.js').read_bytes()).hexdigest())"
```

Update both the version number and the SHA-256 above.
