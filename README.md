# Photo Platform

A photo licensing platform for photographers to upload, manage, and license their images with IPTC metadata extraction capabilities.

## Features

- IPTC metadata extraction from JPG files
- JSON output of metadata fields
- Error handling for files with no IPTC data
- Virtual environment setup for dependency management

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Trustory-za/photo-platform.git
cd photo-platform
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install iptcinfo3
```

## Usage

### IPTC Metadata Reader

Extract IPTC metadata from JPG files:

```bash
python iptc_reader.py /path/to/your/image.jpg
```

#### Example Output

**For a file with IPTC metadata:**
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

**For a file with no IPTC metadata:**
```json
{
  "error": "No IPTC data found",
  "file_path": "/path/to/image.jpg",
  "message": "The JPG file contains no IPTC metadata"
}
```

**For an invalid file:**
```json
{
  "error": "File not found",
  "file_path": "/path/to/missing.jpg",
  "message": "The specified file does not exist"
}
```

## Dependencies

- `iptcinfo3` - Library for reading IPTC metadata from image files

## Development

The project is set up with proper error handling and follows Python best practices. The IPTC reader handles various edge cases including:

- Non-existent files
- Non-JPG files
- Files with no IPTC metadata
- Files with partial IPTC data

## License

This project is part of the photo licensing platform and is intended for commercial use with proper attribution.
## Current Tools
- `watermark.py` — Tiled diagonal watermarking (70% opacity, -30° rotation)
