#!/usr/bin/env python3
"""
IPTC Metadata Reader for JPG files.

This script reads IPTC metadata from JPG files using the python-iptcinfo3 library
and returns the data as a JSON object. Includes error handling for files with no IPTC data.
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
        dict: IPTC metadata as JSON object, or error message
    """
    try:
        # Validate file path
        file_path = Path(file_path)
        if not file_path.exists():
            return {
                "error": "File not found",
                "file_path": str(file_path),
                "message": "The specified file does not exist"
            }
        
        if not file_path.is_file():
            return {
                "error": "Invalid file path",
                "file_path": str(file_path),
                "message": "The specified path is not a file"
            }
        
        # Check if file has .jpg or .jpeg extension (case insensitive)
        if file_path.suffix.lower() not in ['.jpg', '.jpeg']:
            return {
                "error": "Invalid file type",
                "file_path": str(file_path),
                "message": "File must be a JPG (.jpg or .jpeg)"
            }
        
        # Read IPTC metadata using standard iptcinfo3 API
        try:
            # Create IPTCInfo object with force=True to always get an object
            iptc = IPTCInfo(str(file_path), force=True)
            
            # Check if IPTC data exists
            if iptc.error and 'Marker scan hit start of image data' in str(iptc.error):
                return {
                    "error": "No IPTC data found",
                    "file_path": str(file_path),
                    "message": "The JPG file contains no IPTC metadata"
                }
            
            # Use standard IPTC field names directly
            standard_fields = [
                'caption/abstract', 'keywords', 'by-line', 'byline/title', 
                'creditline', 'source', 'copyright notice', 'contact',
                'headline', 'object name', 'edit status', 'urgency', 'category',
                'supplemental category', 'date created', 'time created',
                'digital date created', 'digital time created',
                'originating program', 'program version'
            ]
            
            iptc_data = {}
            fields_found = []
            
            # Extract standard IPTC fields
            for field in standard_fields:
                if field in iptc:
                    value = iptc[field]
                    if value is not None and value != '':
                        iptc_data[field] = value
                        fields_found.append(field)
            
            # If no IPTC fields found
            if not fields_found:
                return {
                    "error": "No IPTC fields found",
                    "file_path": str(file_path),
                    "message": "The JPG file has IPTC data but no standard fields were extracted",
                    "fields_found": []
                }
            
            # Clean and structure the data
            cleaned_data = {}
            
            # Process the IPTC data
            fields_found = []
            for field, value in iptc_data.items():
                # Handle different value types
                if isinstance(value, (list, tuple)):
                    cleaned_data[field] = [str(v) for v in value if v]
                elif value is None:
                    cleaned_data[field] = None
                else:
                    cleaned_data[field] = str(value)
                
                fields_found.append(field)
            
            # Add metadata about the extraction
            result = {
                "success": True,
                "file_path": str(file_path),
                "fields_found": fields_found,
                "total_fields": len(fields_found),
                "metadata": cleaned_data
            }
            
            return result
            
        except Exception as e:
            return {
                "error": "Failed to read IPTC data",
                "file_path": str(file_path),
                "message": f"Error processing IPTC metadata: {str(e)}",
                "error_type": type(e).__name__
            }
            
    except Exception as e:
        return {
            "error": "Unexpected error",
            "file_path": str(file_path),
            "message": f"An unexpected error occurred: {str(e)}",
            "error_type": type(e).__name__
        }


def main():
    """
    Main function to handle command line input and output.
    """
    if len(sys.argv) != 2:
        print(json.dumps({
            "error": "Invalid arguments",
            "message": "Usage: python iptc_reader.py <jpg_file_path>"
        }, indent=2))
        sys.exit(1)
    
    file_path = sys.argv[1]
    result = read_iptc_metadata(file_path)
    
    # Output JSON formatted result
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()