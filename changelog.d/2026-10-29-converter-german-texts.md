### Fixed — the converter's own texts are German on German pages

The converter wrote some of its own texts in English on every page. They now
come from the translation catalogue, like the rest of the page:

- the progress text ("Processing your file…") and the download button;
- the file counter under the drop field;
- the hint when a target makes the file much larger (for example JPG to PNG);
- the messages for a wrong API key and too many requests, and the fallback
  texts for a failed conversion or batch and a network error;
- the screen-reader labels of each file row.

Sizes and other numbers use the page's decimal separator ("1,5 KB" on German
pages). Messages the server writes itself, for example when a file can't be
converted, are still in English.
