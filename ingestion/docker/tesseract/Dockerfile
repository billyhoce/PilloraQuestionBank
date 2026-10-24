# Tesseract OCR, for scans: it reads a scanned answer table's question cells and gives a
# scanned question paper the text layer it lacks (question_extractor/ocr.py).
#
# Debian stable is the version pin. It keeps one Tesseract release (bookworm: 5.3.0)
# for its whole life, so OCR output changes only when this tag does.
FROM debian:bookworm-slim

# tesseract-ocr brings the English (eng) and orientation (osd) models with it;
# every sample paper is in English.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 1000 --create-home ocr
USER ocr
WORKDIR /work

ENTRYPOINT ["tesseract"]
CMD ["--version"]
