#!/usr/bin/env python3
"""
Debug script to trace where HTML corruption occurs in CodeRabbit parsing
"""
import json
import re
import subprocess
import sys
from bs4 import BeautifulSoup
import html


def debug_localStorage_parsing():
    """Debug the localStorage mock parsing step by step."""
    print("=== STEP 1: Fetch raw review data ===")
    result = subprocess.run(['gh', 'pr', 'view', 'https://github.com/obra/lace/pull/278', '--json', 'reviews'], 
                          capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    body = data['reviews'][0]['body']
    
    # Find the localStorage section
    localStorage_pos = body.find("Type the localStorage mock")
    localStorage_section = body[localStorage_pos-100:localStorage_pos+600]
    print("Raw GitHub API content around localStorage:")
    print(localStorage_section)
    print("\n" + "="*60 + "\n")
    
    print("=== STEP 2: Parse with BeautifulSoup ===")
    soup = BeautifulSoup(body, 'html.parser')
    details_elements = soup.find_all('details')
    
    print(f"Found {len(details_elements)} details elements")
    
    # Find nitpick section
    nitpick_details = None
    for details in details_elements:
        summary = details.find('summary')
        if summary and 'Nitpick comments' in summary.get_text():
            nitpick_details = details
            break
    
    if nitpick_details:
        print("Found nitpick details section")
        nitpick_blockquote = nitpick_details.find('blockquote')
        
        print("=== STEP 3: Extract blockquote HTML ===")
        blockquote_html = str(nitpick_blockquote)
        
        # Find localStorage section in blockquote
        localStorage_in_blockquote = blockquote_html.find("Type the localStorage mock")
        if localStorage_in_blockquote != -1:
            bq_section = blockquote_html[localStorage_in_blockquote-100:localStorage_in_blockquote+600]
            print("Blockquote HTML around localStorage:")
            print(bq_section)
            print("\n" + "="*60 + "\n")
        
        print("=== STEP 4: BeautifulSoup get_text() ===")
        blockquote_text = nitpick_blockquote.get_text()
        localStorage_text_pos = blockquote_text.find("Type the localStorage mock")
        if localStorage_text_pos != -1:
            text_section = blockquote_text[localStorage_text_pos-50:localStorage_text_pos+400]
            print("After get_text() around localStorage:")
            print(repr(text_section))
            print("\n" + "="*60 + "\n")
        
        print("=== STEP 5: Extract diff with regex ===")
        diff_pattern = r'```diff\n(.*?)\n```'
        all_diffs = re.findall(diff_pattern, blockquote_html, re.DOTALL)
        
        print(f"Found {len(all_diffs)} diffs in blockquote")
        if all_diffs:
            # Find the localStorage diff specifically
            for i, diff in enumerate(all_diffs):
                if 'localStorageMock' in diff:
                    print(f"Diff {i} (contains localStorageMock):")
                    print(f"Raw: {repr(diff[:200])}")
                    print(f"HTML decoded: {repr(html.unescape(diff[:200]))}")
                    break
        
        print("\n" + "="*60 + "\n")
        print("=== STEP 6: Final parsing test ===")
        
        # Test the exact logic from parse_file_level_comments
        file_details = BeautifulSoup(str(nitpick_blockquote), 'html.parser').find_all('details')
        
        for file_details_elem in file_details:
            file_summary = file_details_elem.find('summary')
            if file_summary and 'SettingsContainer.test.tsx' in file_summary.get_text():
                print("Found SettingsContainer.test.tsx file section")
                
                file_blockquote = file_details_elem.find('blockquote')
                if file_blockquote:
                    file_text = file_blockquote.get_text()
                    
                    # Look for localStorage line
                    if "27-35" in file_text:
                        print("Found 27-35 line reference")
                        
                        # Extract the diff for this specific comment
                        file_html = str(file_blockquote)
                        print(f"File HTML snippet: {file_html[file_html.find('localStorageMock'):file_html.find('localStorageMock')+200]}")
                        
                        diff_matches = re.findall(r'```diff\n(.*?)\n```', file_html, re.DOTALL)
                        if diff_matches:
                            print(f"Extracted diff: {repr(diff_matches[0][:100])}")
                            print(f"HTML decoded: {repr(html.unescape(diff_matches[0][:100]))}")
                        break
                break


if __name__ == "__main__":
    debug_localStorage_parsing()