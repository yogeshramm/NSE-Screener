# Frontend Version Archive

Old working snapshots of index_v2.html saved before each major batch of changes.

Format: `index_v2_YYYYMMDD_HHMMSS.html`

To restore a version:
  cp frontend/versions/index_v2_YYYYMMDD_HHMMSS.html frontend/index_v2.html
  cp frontend/index_v2.html frontend/index.html
  git add frontend/ && git commit -m "Restore to YYYYMMDD version"
