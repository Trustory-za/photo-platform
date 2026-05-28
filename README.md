# Photo Platform

A photo licensing platform for photographers to upload, manage, and license their images with IPTC metadata extraction capabilities.

## Features

- IPTC metadata extraction from JPG files
- JSON output for integration with other systems
- Error handling for files with no IPTC data
- Command-line interface for easy use
- Python virtual environment setup

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
   pip install -r requirements.txt
   ```

## Usage

### Command Line Interface

Extract IPTC metadata from a JPG file:

```bash
python iptc_reader.py /path/to/your/image.jpg
```

### Example Output

#### Image with IPTC data:
```json
{
  "success": true,
  "file_path": "/path/to/your/image.jpg",
  "iptc_metadata": {
    "caption": "A beautiful landscape photograph",
    "headline": "Landscape Photography",
    "keywords": ["nature", "landscape", "mountains", "outdoors"],
    "credit": "John Doe Photography",
    "source": "John Doe",
    "copyright": "© 2024 John Doe. All rights reserved.",
    "contact": "john@example.com",
    "date_created": "2024-01-15",
    "city": "Banff",
    "state": "Alberta",
    "country": "Canada",
    "country_code": "CA",
    "author": "John Doe",
    "title": "Mountain Vista"
  },
  "message": "Successfully extracted 12 IPTC fields from '/path/to/your/image.jpg'"
}
```

#### Image without IPTC data:
```json
{
  "error": "No IPTC data found",
  "file_path": "/path/to/your/image.jpg",
  "message": "The file '/path/to/your/image.jpg' contains no IPTC metadata."
}
```

#### File not found:
```json
{
  "error": "File not found",
  "file_path": "/path/to/your/image.jpg",
  "message": "The file '/path/to/your/image.jpg' does not exist."
}
```

#### Invalid file type:
```json
{
  "error": "Invalid file type",
  "file_path": "/path/to/your/image.jpg",
  "message": "File must be a JPG or JPEG image. Got: .png"
}
```

## Supported IPTC Fields

The script extracts the following IPTC fields when present:

- **caption**: Caption/Abstract (2#120)
- **headline**: Headline (2#105)
- **keywords**: Keywords (2#25)
- **credit**: Credit (2#110)
- **source**: Source (2#115)
- **copyright**: Copyright Notice (2#116)
- **contact**: Contact (2#118)
- **date_created**: Date Created (2#055)
- **city**: City (2#090)
- **state**: State/Province (2#095)
- **country**: Country/Primary Location Code (2#101)
- **country_code**: Country/Primary Location Name (2#100)
- **author**: Author/Artist (2#122)
- **title**: Object Name (2#005)

## Error Handling

The script includes comprehensive error handling for:
- Non-existent files
- Invalid file types (non-JPG/JPEG)
- Files with no IPTC data
- Corrupted or unreadable image files
- Library-related errors

## Dependencies

- `python-iptcinfo3>=2.3.0`: IPTC metadata extraction library
- Python 3.6+

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

For issues and questions, please open an issue on GitHub.