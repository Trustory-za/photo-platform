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
        
        # Try to read IPTC metadata
        try:
            # Create IPTCInfo object with force=True to always get an object
            iptc = IPTCInfo(str(file_path), force=True)
            
            # Check if IPTC data exists by checking error and data attributes
            if iptc.error and 'Marker scan hit start of image data' in str(iptc.error):
                return {
                    "error": "No IPTC data found",
                    "file_path": str(file_path),
                    "message": "The JPG file contains no IPTC metadata"
                }
            
            # Try to get IPTC data using the correct API
            # Check if we have the data attribute
            if hasattr(iptc, 'data'):
                iptc_data = iptc.data
            else:
                # Try to get data through other methods
                iptc_data = None
                
                # Try to access data through the object if it exists
                if hasattr(iptc, '__dict__'):
                    iptc_data = {k: v for k, v in iptc.__dict__.items() if not k.startswith('_') and k not in ['error', 'inp_charset', 'out_charset', 'c_marker_err']}
                
                # If no data found, check if we can get it through scanning
                if not iptc_data:
                    try:
                        # Try to access any available attributes that might contain IPTC data
                        for attr in dir(iptc):
                            if not attr.startswith('_') and attr not in ['error', 'inp_charset', 'out_charset', 'c_marker_err', 'blindScan', 'collectIIMInfo', 'jpegScan', 'packedIIMData', 'photoshopIIMBlock', 'save', 'save_as', 'scanToFirstIMMTag']:
                                value = getattr(iptc, attr)
                                if value is not None:
                                    if iptc_data is None:
                                        iptc_data = {}
                                    iptc_data[attr] = value
                    except:
                        pass
            
            # If no IPTC fields found
            if not iptc_data:
                return {
                    "error": "No IPTC fields found",
                    "file_path": str(file_path),
                    "message": "The JPG file has IPTC data but no fields were extracted",
                    "fields_found": []
                }
            
            # Clean and structure the data
            cleaned_data = {}
            
            # Common IPTC fields mapping
            iptc_mapping = {
                '2#005': 'object_name',
                '2#010': 'edit_status',
                '2#015': 'editorial_update',
                '2#020': 'urgency',
                '2#025': 'subject_reference',
                '2#030': 'category',
                '2#035': 'supplemental_category',
                '2#040': 'fixture_identifier',
                '2#045': 'keywords',
                '2#047': 'content_location_code',
                '2#050': 'content_location_name',
                '2#055': 'release_date',
                '2#060': 'release_time',
                '2#062': 'expiration_date',
                '2#065': 'expiration_time',
                '2#070': 'special_instructions',
                '2#075': 'action_advised',
                '2#080': 'reference_service',
                '2#085': 'reference_date',
                '2#090': 'reference_number',
                '2#095': 'date_created',
                '2#100': 'time_created',
                '2#101': 'digital_date_created',
                '2#102': 'digital_time_created',
                '2#103': 'originating_program',
                '2#105': 'program_version',
                '2#110': 'object_cycle',
                '2#115': 'byline',
                '2#116': 'byline_title',
                '2#118': 'credit_line',
                '2#120': 'source',
                '2#122': 'copyright_notice',
                '2#125': 'contact',
                '2#130': 'caption_writer',
                '2#135': 'rasterized_caption',
                '2#150': 'image_type',
                '2#200': 'custom_field_200',
                '2#201': 'custom_field_201',
                '2#202': 'custom_field_202',
                '2#203': 'custom_field_203',
                '2#204': 'custom_field_204',
                '2#205': 'custom_field_205',
                '2#206': 'custom_field_206',
                '2#207': 'custom_field_207',
                '2#208': 'custom_field_208',
                '2#209': 'custom_field_209',
                '2#210': 'custom_field_210',
                '2#211': 'custom_field_211',
                '2#212': 'custom_field_212',
                '2#213': 'custom_field_213',
                '2#214': 'custom_field_214',
                '2#215': 'custom_field_215',
                '2#216': 'custom_field_216',
                '2#217': 'custom_field_217',
                '2#218': 'custom_field_218',
                '2#219': 'custom_field_219',
                '2#220': 'custom_field_220',
                '2#221': 'custom_field_221',
                '2#222': 'custom_field_222',
                '2#223': 'custom_field_223',
                '2#224': 'custom_field_224',
                '2#225': 'custom_field_225',
                '2#226': 'custom_field_226',
                '2#227': 'custom_field_227',
                '2#228': 'custom_field_228',
                '2#229': 'custom_field_229',
                '2#230': 'custom_field_230',
                '2#231': 'custom_field_231',
                '2#232': 'custom_field_232',
                '2#233': 'custom_field_233',
                '2#234': 'custom_field_234',
                '2#235': 'custom_field_235',
                '2#236': 'custom_field_236',
                '2#237': 'custom_field_237',
                '2#238': 'custom_field_238',
                '2#239': 'custom_field_239',
                '2#240': 'custom_field_240',
                '2#241': 'custom_field_241',
                '2#242': 'custom_field_242',
                '2#243': 'custom_field_243',
                '2#244': 'custom_field_244',
                '2#245': 'custom_field_245',
                '2#246': 'custom_field_246',
                '2#247': 'custom_field_247',
                '2#248': 'custom_field_248',
                '2#249': 'custom_field_249',
                '2#250': 'custom_field_250',
                '2#251': 'custom_field_251',
                '2#252': 'custom_field_252',
                '2#253': 'custom_field_253',
                '2#254': 'custom_field_254',
                '2#255': 'custom_field_255'
            }
            
            # Process the IPTC data
            fields_found = []
            for tag, value in iptc_data.items():
                # Convert tag to human-readable name
                field_name = iptc_mapping.get(tag, f'unknown_field_{tag}')
                
                # Handle different value types
                if isinstance(value, (list, tuple)):
                    cleaned_data[field_name] = [str(v) for v in value if v]
                elif value is None:
                    cleaned_data[field_name] = None
                else:
                    cleaned_data[field_name] = str(value)
                
                fields_found.append(field_name)
            
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