#!/usr/bin/env python3
"""
IPTC Metadata Reader for JPG files.

This script reads IPTC metadata from JPG files using the python-iptcinfo3 library
and returns the data as a JSON object. Includes error handling for files with no IPTC data.

Usage:
    python iptc_reader.py <path_to_jpg_file>
    
Example:
    python iptc_reader.py /path/to/photo.jpg
"""

import json
import sys
from pathlib import Path
from iptcinfo3 import IPTCInfo

def read_iptc_metadata(file_path):
    """
    Read IPTC metadata from a JPG file.
    
    Args:
        file_path (str): Path to the JPG file
        
    Returns:
        dict: IPTC metadata as JSON object, or error message if no IPTC data
    """
    file_path = Path(file_path)
    
    # Check if file exists
    if not file_path.exists():
        return {
            "error": "File not found",
            "file_path": str(file_path),
            "message": f"The file '{file_path}' does not exist."
        }
    
    # Check if file is a JPG
    if file_path.suffix.lower() not in ['.jpg', '.jpeg']:
        return {
            "error": "Invalid file type",
            "file_path": str(file_path),
            "message": f"File must be a JPG or JPEG image. Got: {file_path.suffix}"
        }
    
    # Try to read IPTC metadata
    try:
        # Create IPTCInfo object with force=True to always get an object
        iptc = IPTCInfo(str(file_path), force=True)
        
        # Check if IPTC data exists by checking error and data attributes
        if iptc.error and 'Marker scan hit start of image data' in str(iptc.error):
            return {
                "error": "No IPTC data found",
                "file_path": str(file_path),
                "message": f"The file '{file_path}' contains no IPTC metadata."
            }
        
        # Extract available IPTC fields
        iptc_data = {}
        
        # Common IPTC fields that might be present
        iptc_fields = {
            'caption': '2#120',  # Caption/Abstract
            'headline': '2#105',  # Headline
            'keywords': '2#25',   # Keywords
            'credit': '2#110',    # Credit
            'source': '2#115',    # Source
            'copyright': '2#116',  # Copyright Notice
            'contact': '2#118',   # Contact
            'date_created': '2#055',  # Date Created
            'city': '2#090',      # City
            'state': '2#095',      # State/Province
            'country': '2#101',    # Country/Primary Location Code
            'country_code': '2#100',  # Country/Primary Location Name
            'author': '2#122',    # Author/Artist
            'title': '2#005',     # Object Name
        }
        
        # Extract each field if it exists
        for field_name, field_tag in iptc_fields.items():
            try:
                value = getattr(iptc, field_tag, None)
                if value:
                    # Handle different value types
                    if isinstance(value, (list, tuple)):
                        iptc_data[field_name] = [str(v) for v in value if v]
                    elif value:
                        iptc_data[field_name] = str(value)
            except (AttributeError, Exception):
                # Skip fields that can't be accessed
                pass
        
        # If we found some IPTC data, return it
        if iptc_data:
            return {
                "success": True,
                "file_path": str(file_path),
                "iptc_metadata": iptc_data,
                "message": f"Successfully extracted {len(iptc_data)} IPTC fields from '{file_path}'"
            }
        else:
            return {
                "error": "No IPTC data found",
                "file_path": str(file_path),
                "message": f"The file '{file_path}' contains no extractable IPTC metadata."
            }
        
    except Exception as e:
        return {
            "error": "Failed to read IPTC metadata",
            "file_path": str(file_path),
            "message": f"An error occurred while reading IPTC metadata: {str(e)}"
        }

def main():
    """
    Main function to handle command line usage.
    """
    if len(sys.argv) != 2:
        print("Usage: python iptc_reader.py <path_to_jpg_file>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    result = read_iptc_metadata(file_path)
    
    # Output JSON result
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()