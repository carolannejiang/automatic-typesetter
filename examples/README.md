# Examples

## field-notes

Three short Markdown essays that exercise headings, blockquotes, tables,
lists, and scene breaks. Build them into a book:

```bash
python3 -m bookformatter examples/field-notes \
    -t "Field Notes on Book Making" \
    -a "Your Name" \
    --description "Three short essays on typography" \
    -f epub,pdf,html
```

Outputs appear in `./build/`.
