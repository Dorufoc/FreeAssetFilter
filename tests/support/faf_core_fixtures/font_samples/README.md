# font_samples provenance

- sample_regular.ttf: copied from Windows system font ANTQUAB.TTF
  (small enough to satisfy the <512KB rule).
- sample_regular.otf: Windows Fonts ships zero .otf files (verified 0/415);
  copied verbatim from Go x/image testdata CFFTest.otf (real CFF-OpenType,
  sfntVersion=OTTO validated with fontTools).
- sample_regular.woff / .woff2: converted from sample_regular.ttf via
  fontTools TTFont flavor conversion (real transformation, reload-verified).
- sample_corrupt.ttf: intentionally destroyed (sfnt magic zeroed +
  truncated to 128B + garbage); eager TTFont table walk raises
  TTLibError — verified at generation time.
