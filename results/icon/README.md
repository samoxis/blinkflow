# A new icon with Muse Image: three candidates

Oct 28, 20:03–20:04 UTC. Three calls to `muse-image-1.0` on the Meta Model API (`POST /v1/images/generations`, `n` 1,
`size` "1024x1024"), one per variant; [`muse-image.json`](muse-image.json) keeps each prompt as sent, the reply's
`created` timestamp, `usage` and the `x-request-id` header (the reply has no id field of its own), with the image
replaced by its length.

The brief, the same for all three: a stylized white robot duck, one large round camera-lens eye, a small violet box
(#7C4DFF); flat vector, rounded shapes, thick even outlines, no text, no gradients; white, violet and an orange beak
only; dark indigo background (#1A1240); rounded square, subject large and centred with a 15% margin, readable at 48 px.

| Variant | Subject |
|---|---|
| m1 | the head, three-quarter view, looking at the box in the lower-right corner |
| m2 | the whole duck, geometric, beside the box |
| m3 | the lens eye, with the duck and the box reflected in it |

Each reply was a 1600×1600 WebP (`size` sets the aspect, not the pixels); it was saved as a 1024×1024 PNG (Lanczos),
whose SHA-256 is in `muse-image.json` beside the WebP's. The images and the 1024 / 128 / 48 px sheet are kept outside
the repo until one is chosen; `docs/icon.png` is unchanged.

## Round 2: variant (a) only

Oct 28, three more calls, same endpoint and parameters ([`muse-image-r2.json`](muse-image-r2.json): prompts, `created`,
`usage`, `x-request-id`, and the SHA-256 of both the reply and the saved PNG). Changes to the brief: the head one solid
white shape with a single outline and nothing on top (no double outline, no ear-like bumps); the lens eye large, 2–3
concentric violet rings, looking down-right; a small orange beak pointing at the box; the box larger, about a quarter
of the width. a2 also asks for a larger eye, a3 for a flat shadow under the head (a darker indigo ellipse).

The replies were again opaque 1600×1600 WebP with white outside the rounded square. That white was made transparent
here: the white regions touching the image border get alpha 0, the antialiased rim becomes indigo at partial alpha;
then the image is cropped to the rounded square and resized to 1024×1024 (Lanczos). The sheet shows each at 1024, 128,
48 and 32 px, on light and on dark.

How each kept the brief: a1 still draws a double outline around the head; a2 has one shape, two violet rings and the
pupil down-right, but its beak is a lighter orange than the others; a3 has the largest box and the shadow, but its eye
adds a second violet shade and a white highlight instead of rings.
