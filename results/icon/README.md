# The icon: provenance

`docs/icon.png` was made with `muse-image-1.0` on the Meta Model API, Oct 28, 20:20:47 UTC: one call to
`POST /v1/images/edits` (multipart, `n` 1, `size` "1024x1024"), reply `created` 1793218876, `x-request-id`
`e5cd076f-5629-4086-9de2-b878cb2e127e`. The input image was an earlier reference image supplied by the author; its
hash is in [`muse-image.json`](muse-image.json), beside the prompt as sent, the reply's `usage` and the SHA-256 of the
reply and of `docs/icon.png`.

The prompt asked for the reference redrawn cleanly, not copied: the head and neck of a white robot duck, a large
violet eye with two highlights, an orange beak pointing at a violet cube in the lower right, a dark indigo rounded
square, a flat style with thick even outlines, white, violet and orange only, no shading, no text.

The reply was an opaque 1600×1600 WebP with white outside the rounded square. That white was made transparent (the
white regions touching the border get alpha 0, the antialiased rim becomes indigo at partial alpha) and the image
resized to 1024×1024 (Lanczos). `docs/icon-512.png`, `docs/icon-180.png` and `docs/favicon-32.png` are that PNG
resized.

Earlier candidates (two rounds of text-to-image, two other edits) are in this folder's git history.
