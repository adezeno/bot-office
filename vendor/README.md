# vendor

The office's own copy of three.js, so the 3D office loads from this site alone, with no CDN.

- `three.module.js` is `build/three.module.js` from the npm package `three@0.160.0`, unchanged. The import map in `index.html` points `three` at it.
- sha256 `76dea8151bc9352aef3528b4262e249b2604f62543828328db978d060d61a495`. The npm package (checked against the registry's published sha512), unpkg, jsDelivr and the `r160` tag on GitHub all serve these same bytes.
- three.js is MIT licensed. Its licence is in `three-LICENSE.txt`, copied from the same package.

To upgrade, add the new release's file under a new name (for example `three-0.161.0.module.js`) with its licence, point the import map at it, delete the old files, update this note, and test the office. GitHub Pages lets browsers keep a file for 10 minutes, so reusing the old name could briefly pair the new page with the old library.
