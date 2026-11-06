### Fixed — JPG and WebP results keep the photo's colour profile

Converting or compressing to JPG or WebP dropped the image's colour profile
(ICC), although the metadata strip keeps it on purpose. Viewers then read a
wide-gamut photo — an iPhone's Display P3, Adobe RGB — as sRGB, and its
colours turned dull. HEIC → JPG, the most common iPhone conversion, was hit
every time. JPEG and WebP results now carry the profile, as PNG, TIFF and
AVIF results already did; so does compression to a target size.

- A profile that no longer fits the pixels as written goes instead of being
  misapplied: a CMYK profile after the conversion to RGB, a greyscale one in
  a WebP (always colour) or on colour pixels, one too short to say which
  colours it describes.
- A profile over 4 MB goes too. RGB profiles take a few KB, print profiles
  up to about 2 MB; Pillow splits a JPEG's profile in time growing with the
  square of its size, so a crafted one could tie up the server for seconds
  per encode.
- In target-size compression a profile that alone would take more than a
  quarter of the target goes, so a large print profile can't make a
  reachable target unreachable.
- The size estimate under the compress slider counts the profile's bytes, so
  it stays exact for JPEGs that carry one.
