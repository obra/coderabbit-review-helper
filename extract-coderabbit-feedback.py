#!/usr/bin/env python3
"""
ABOUTME: Extract CodeRabbit review feedback from GitHub PRs for LLM consumption
ABOUTME: Uses gh CLI to fetch PR comments and formats them as plain text
"""
import json
import re
import subprocess
import sys
from urllib.parse import urlparse
from typing import List, Dict, Any, Tuple
from bs4 import BeautifulSoup
import html


def parse_pr_input(input_str: str) -> str:
    """Parse PR URL or owner/repo/number format into a full GitHub PR URL."""
    input_str = input_str.strip()
    
    # If it's already a full URL, return as-is
    if input_str.startswith('https://github.com/'):
        return input_str
    
    # Parse owner/repo/number format (e.g., "obra/lace/278")
    parts = input_str.split('/')
    if len(parts) == 3:
        owner, repo, pr_num = parts
        return f"https://github.com/{owner}/{repo}/pull/{pr_num}"
    
    raise ValueError(f"Invalid PR format: {input_str}. Use 'owner/repo/number' or full URL")


def fetch_pr_reviews(pr_url: str) -> List[Dict[str, Any]]:
    """Fetch PR reviews using gh CLI."""
    try:
        result = subprocess.run(
            ['gh', 'pr', 'view', pr_url, '--json', 'reviews'],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
        return data.get('reviews', [])
    except subprocess.CalledProcessError as e:
        print(f"Error fetching PR: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON response: {e}", file=sys.stderr)
        sys.exit(1)


def fetch_pr_inline_comments(pr_url: str) -> List[Dict[str, Any]]:
    """Fetch PR inline review comments using GitHub API via gh CLI."""
    try:
        # Extract owner/repo/number from URL
        if 'github.com' in pr_url:
            parts = pr_url.replace('https://github.com/', '').split('/')
            if len(parts) >= 4 and parts[2] == 'pull':
                owner, repo, _, pr_number = parts[:4]
                api_path = f"repos/{owner}/{repo}/pulls/{pr_number}/comments"
            else:
                raise ValueError("Invalid GitHub PR URL format")
        else:
            raise ValueError("URL must be a GitHub PR URL")
        
        result = subprocess.run(
            ['gh', 'api', api_path],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
        return data if isinstance(data, list) else []
    except subprocess.CalledProcessError as e:
        print(f"Error fetching inline comments: {e.stderr}", file=sys.stderr)
        return []
    except json.JSONDecodeError as e:
        print(f"Error parsing inline comments JSON: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Error processing PR URL for inline comments: {e}", file=sys.stderr)
        return []


def extract_coderabbit_reviews(reviews: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter reviews to only CodeRabbit ones."""
    return [
        review for review in reviews
        if review.get('author', {}).get('login') == 'coderabbitai'
    ]


def extract_coderabbit_inline_comments(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter inline comments to only CodeRabbit ones."""
    return [
        comment for comment in comments
        if comment.get('user', {}).get('login') == 'coderabbitai[bot]'
    ]


def parse_review_type(body: str) -> str:
    """Determine the type of CodeRabbit review."""
    if 'Actionable comments posted:' in body:
        return 'ACTIONABLE_REVIEW'
    elif 'walkthrough_start' in body and 'walkthrough_end' in body:
        return 'WALKTHROUGH'
    elif '<!-- This is an auto-generated comment: summarize by coderabbit.ai -->' in body:
        return 'SUMMARY'
    else:
        return 'OTHER'


def extract_prompt_for_ai_agents(body: str) -> List[str]:
    """Extract 'Prompt for AI Agents' sections from review body."""
    prompts = []
    
    # Pattern to find 🤖 Prompt for AI Agents sections
    # These appear to be in <summary> tags followed by clipboard content
    pattern = r'<summary>🤖 Prompt for AI Agents</summary>\s*<div[^>]*data-snippet-clipboard-copy-content="([^"]*)"'
    matches = re.findall(pattern, body, re.DOTALL)
    
    for match in matches:
        # Decode HTML entities
        clean_text = (match
                     .replace('&lt;', '<')
                     .replace('&gt;', '>')
                     .replace('&amp;', '&')
                     .replace('&quot;', '"')
                     .replace('\\n', '\n')
                     .strip())
        if clean_text:
            prompts.append(clean_text)
    
    return prompts


# Removed unused functions - now using parse_review_sections instead


def parse_review_sections(body: str) -> Dict[str, Any]:
    """Parse different sections from CodeRabbit review body using HTML parsing."""
    sections = {}
    
    # Extract actionable comments count from text
    actionable_match = re.search(r'Actionable comments posted:\s*(\d+)', body)
    if actionable_match:
        sections['actionable_count'] = int(actionable_match.group(1))
    
    # Parse HTML structure - but be careful not to mangle code content
    # Only use BeautifulSoup for extracting the <details> sections, then work with raw content
    soup = BeautifulSoup(body, 'html.parser')
    
    # Find sections by looking for <details> elements with specific summary text
    details_elements = soup.find_all('details')
    
    for details in details_elements:
        summary = details.find('summary')
        if not summary:
            continue
            
        summary_text = summary.get_text(strip=True)
        
        # Check for outside diff range comments (avoid emoji dependency)
        if 'Outside diff range comments' in summary_text:
            # Extract count from summary text
            count_match = re.search(r'\((\d+)\)', summary_text)
            if count_match:
                count = int(count_match.group(1))
                blockquote = details.find('blockquote')
                if blockquote:
                    # Get all content inside the blockquote
                    content = str(blockquote)
                    sections['outside_diff_comments'] = {'count': count, 'content': content}
        
        # Check for nitpick comments
        elif 'Nitpick comments' in summary_text:
            count_match = re.search(r'\((\d+)\)', summary_text)
            if count_match:
                count = int(count_match.group(1))
                # Instead of using BeautifulSoup's blockquote content (which mangles code),
                # extract the raw content from the original body text
                
                # Find the position of this details section in the original body
                details_start = body.find('Nitpick comments')
                if details_start != -1:
                    # Find where this section ends (next major section or end)
                    section_markers = ['📜 Review details', '🔇 Additional comments', '</details>\n\n</details>']
                    section_end = len(body)
                    
                    for marker in section_markers:
                        marker_pos = body.find(marker, details_start)
                        if marker_pos != -1:
                            section_end = min(section_end, marker_pos)
                    
                    # Extract the raw text content
                    raw_content = body[details_start:section_end]
                    sections['nitpick_comments'] = {'count': count, 'content': raw_content}
        
        # Check for review details (usually at the end)
        elif 'Review details' in summary_text:
            # This section contains metadata, we might want it for context
            blockquote = details.find('blockquote')
            if blockquote:
                content = str(blockquote)
                sections['review_details'] = {'content': content}
    
    # Extract AI prompts (look for specific patterns)
    sections['ai_prompts'] = extract_prompt_for_ai_agents(body)
    
    return sections


def parse_file_level_comments(content: str) -> List[Dict[str, Any]]:
    """Parse individual file-level comments from section content, avoiding HTML corruption."""
    comments = []
    
    # Use regex to find file sections instead of BeautifulSoup to avoid HTML corruption
    # Pattern: <summary>filename (count)</summary><blockquote>content</blockquote></details>
    file_pattern = r'<summary>([^<]+?)\s*\((\d+)\)</summary><blockquote>(.*?)</blockquote></details>'
    file_matches = re.finditer(file_pattern, content, re.DOTALL)
    
    for file_match in file_matches:
        file_path = file_match.group(1).strip()
        comment_count = int(file_match.group(2))
        file_content = file_match.group(3)  # Raw blockquote content, not parsed by BeautifulSoup
        
        # Now parse line comments within this file content
        # Find line comment patterns: `16-24`: **Title**
        line_pattern = r'`([^`]+)`:\s*\*\*(.*?)\*\*\s*\n\n(.*?)(?=\n\n`[^`]+`:\s*\*\*|\n\n---|\n\n</blockquote>|$)'
        line_matches = re.finditer(line_pattern, file_content, re.DOTALL)
        
        for line_match in line_matches:
            line_range = line_match.group(1).strip()
            title = line_match.group(2).strip() 
            content_block = line_match.group(3).strip()
            
            # Check if this looks like a line reference
            if re.match(r'^[\d\-,\s]+$', line_range):
                # Extract description (everything before first code block)
                description = content_block
                code_diff = ""
                
                code_start = content_block.find('```')
                if code_start != -1:
                    description = content_block[:code_start].strip()
                    
                    # Extract code diff from raw content (no BeautifulSoup mangling)
                    diff_match = re.search(r'```diff\n(.*?)\n```', content_block, re.DOTALL)
                    if diff_match:
                        code_diff = diff_match.group(1).strip()
                        # HTML decode only entities, don't let BeautifulSoup interpret as HTML
                        code_diff = html.unescape(code_diff)
                
                # Clean up description
                description_lines = []
                for line in description.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('Also applies to:') and line != '---':
                        description_lines.append(line)
                description = ' '.join(description_lines)
                
                comments.append({
                    'file': file_path,
                    'lines': line_range,
                    'title': title,
                    'description': description,
                    'code_diff': code_diff
                })
    
    return comments


def format_for_llm(coderabbit_reviews: List[Dict[str, Any]], inline_comments: List[Dict[str, Any]] = None) -> str:
    """Format CodeRabbit review feedback as plain text for LLM consumption."""
    output = []
    output.append("# CodeRabbit Review Feedback")
    output.append("=" * 40)
    output.append("")
    
    for i, review in enumerate(coderabbit_reviews, 1):
        review_type = parse_review_type(review['body'])
        
        # Skip walkthrough reviews as requested
        if review_type == 'WALKTHROUGH':
            continue
            
        output.append(f"## Review {i} - {review_type}")
        output.append("")
        
        body = review['body']
        sections = parse_review_sections(body)
        
        # Add summary info
        if 'actionable_count' in sections:
            output.append(f"**Actionable comments posted: {sections['actionable_count']}**")
            output.append("")
        
        # Process outside diff range comments
        if 'outside_diff_comments' in sections:
            outside_comments = parse_file_level_comments(sections['outside_diff_comments']['content'])
            if outside_comments:
                output.append("### Outside Diff Range Comments")
                output.append("")
                
                for comment in outside_comments:
                    output.append(f"**{comment['file']} (lines {comment['lines']}): {comment['title']}**")
                    output.append("")
                    
                    # Clean up description (remove extra markdown formatting)
                    desc = re.sub(r'\n+', ' ', comment['description']).strip()
                    output.append(desc)
                    output.append("")
                    
                    if comment['code_diff']:
                        output.append("```diff")
                        output.append(comment['code_diff'])
                        output.append("```")
                        output.append("")
        
        # Process nitpick comments  
        if 'nitpick_comments' in sections:
            nitpick_comments = parse_file_level_comments(sections['nitpick_comments']['content'])
            if nitpick_comments:
                output.append("### Nitpick Comments")
                output.append("")
                
                for comment in nitpick_comments:
                    output.append(f"**{comment['file']} (lines {comment['lines']}): {comment['title']}**")
                    output.append("")
                    
                    # Clean up description
                    desc = re.sub(r'\n+', ' ', comment['description']).strip()
                    output.append(desc)
                    output.append("")
                    
                    if comment['code_diff']:
                        output.append("```diff")
                        output.append(comment['code_diff'])
                        output.append("```")
                        output.append("")
        
        # Add AI prompts from review body
        if sections.get('ai_prompts'):
            output.append("### AI Implementation Instructions (from review body)")
            output.append("")
            
            for j, prompt in enumerate(sections['ai_prompts'], 1):
                output.append(f"**Prompt {j}:**")
                output.append("```")
                output.append(prompt)
                output.append("```")
                output.append("")
        
        output.append("-" * 40)
        output.append("")
    
    # Add inline review comments (these contain the main refactor suggestions and AI prompts)
    if inline_comments:
        output.append("## Inline Review Comments")
        output.append("")
        
        for i, comment in enumerate(inline_comments, 1):
            # Extract file and line info
            file_path = comment.get('path', 'unknown')
            original_line = comment.get('original_line', 'unknown')
            
            output.append(f"### Inline Comment {i}")
            output.append(f"**File:** {file_path} (line {original_line})")
            output.append("")
            
            # Parse the comment body
            body = comment.get('body', '')
            
            # Extract refactor suggestion type
            if '🛠️ Refactor suggestion' in body:
                output.append("**Type:** 🛠️ Refactor Suggestion")
            else:
                output.append("**Type:** Comment")
            output.append("")
            
            # Extract and format the main content (everything before AI prompt)
            if '<details>' in body and 'Prompt for AI Agents' in body:
                main_content = body.split('<details>')[0].strip()
            else:
                main_content = body
            
            # Clean up markdown formatting for LLM consumption
            main_content = main_content.replace('_🛠️ Refactor suggestion_', '').strip()
            main_content = re.sub(r'\n\n+', '\n\n', main_content)  # Normalize line breaks
            
            output.append("**Suggestion:**")
            output.append(main_content)
            output.append("")
            
            # Extract AI prompt if present
            ai_prompt_match = re.search(r'<summary>🤖 Prompt for AI Agents</summary>\s*\n\n```\n(.*?)\n```', body, re.DOTALL)
            if ai_prompt_match:
                ai_prompt = ai_prompt_match.group(1).strip()
                output.append("**🤖 AI Implementation Instructions:**")
                output.append("```")
                output.append(ai_prompt)
                output.append("```")
                output.append("")
            
            output.append("-" * 40)
            output.append("")
    
    return "\n".join(output)


def main():
    """Main entry point."""
    if len(sys.argv) != 2:
        print("Usage: python extract-coderabbit-feedback.py <PR_URL_OR_OWNER/REPO/NUMBER>")
        print("Examples:")
        print("  python extract-coderabbit-feedback.py https://github.com/owner/repo/pull/123")
        print("  python extract-coderabbit-feedback.py owner/repo/123")
        sys.exit(1)
    
    try:
        pr_url = parse_pr_input(sys.argv[1])
        
        # Fetch both reviews and inline comments
        reviews = fetch_pr_reviews(pr_url)
        inline_comments = fetch_pr_inline_comments(pr_url)
        
        coderabbit_reviews = extract_coderabbit_reviews(reviews)
        coderabbit_inline_comments = extract_coderabbit_inline_comments(inline_comments)
        
        if not coderabbit_reviews and not coderabbit_inline_comments:
            print("No CodeRabbit reviews or comments found in this PR.", file=sys.stderr)
            sys.exit(1)
        
        formatted_output = format_for_llm(coderabbit_reviews, coderabbit_inline_comments)
        print(formatted_output)
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()