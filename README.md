# Trustory Images — Photo Licensing Platform

A South African photo licensing platform built for photographers to upload, watermark, and license their images. Developed for Charlé Lombard.

## Overview

Trustory Images lets photographers supply high-resolution images, extracts embedded IPTC metadata (captions, keywords, credit lines) automatically, applies a tiled diagonal watermark to protect copyright, and prepares images for licensing via Stripe payment before full-resolution downloads are released.

## Features

- **IPTC Metadata Extraction** — reads embedded metadata from JPG files using `iptcinfo3`: keywords, captions, bylines, credit lines, and more
- **Automatic Watermarking** — tiles "© Trustory Images" across the full image in a diagonal grid pattern at 50 % opacity, rotated -30°, using Pillow
- **Batch-Ready** — both tools operate as CLI scripts that accept file paths and return structured JSON output
- **Error Handling** — graceful failure for missing files, non-image inputs, and files without IPTC data

## Tech Stack

- **Language:** Python 3.11
- **Image Processing:** Pillow (PIL)
- **Metadata Extraction:** iptcinfo3

## Installation

```bash
# Clone the repository
git clone https://github.com/Trustory-za/photo-platform.git
cd photo-platform

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Extract IPTC Metadata

```bash
python iptc_reader.py path/to/image.jpg
```

**Example output:**

```json
{
  "success": true,
  "file_path": "/path/to/image.jpg",
  "fields_found": ["keywords", "caption_writer", "credit_line"],
  "total_fields": 3,
  "metadata": {
    "keywords": ["nature", "landscape", "mountain"],
    "caption_writer": "John Doe",
    "credit_line": "© 2024 John Doe Photography"
  }
}
```

If the file has no IPTC data:

```json
{
  "error": "No IPTC data found",
  "file_path": "/path/to/image.jpg",
  "message": "The JPG file contains no IPTC metadata"
}
```

### Apply Watermark

```bash
python watermark.py input.jpg output.jpg
```

**Example output:**

```json
{
  "success": true,
  "input_path": "/home/user/input.jpg",
  "output_path": "/home/user/output.jpg",
  "image_size": "4000x3000",
  "watermark_text": "© Trustory Images"
}
```

The watermark tiles the text diagonally across the full image at 50 % opacity with -30° rotation — visible enough to deter unauthorised use without obscuring the photograph.

## File Structure

```
photo-platform/
├── iptc_reader.py        # IPTC metadata extraction script
├── watermark.py          # Image watermarking script
├── requirements.txt      # Python dependencies
├── README.md             # This file
├── test.jpg              # Sample image for testing
├── test.png              # Sample PNG for testing
└── test_watermarked.jpg  # Sample watermarked output
```

## Development Notes

- Both scripts return structured JSON output (exit code 0 on success, 1 on failure), making them suitable for integration into a larger pipeline
- The watermark uses a binary search to find the optimal font size relative to the image dimensions — it adapts to any resolution
- Placeholder test images (`test.jpg`, `test.png`) are included for local testing

## License

This project is part of the Trustory Images photo licensing platform. All rights reserved.