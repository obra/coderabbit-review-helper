#!/usr/bin/env python3
"""
ABOUTME: Extract CodeRabbit review feedback from GitHub PRs for LLM consumption
ABOUTME: Uses gh CLI to fetch PR comments and formats them as plain text
"""
import argparse
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


def clean_html_artifacts(text: str) -> str:
    """Remove HTML comments and artifacts from text."""
    # Remove HTML comments
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    
    # Remove CodeRabbit warning blocks
    text = re.sub(r'>\s*‼️\s*\*\*IMPORTANT\*\*.*?(?=\n\n|\n$)', '', text, flags=re.DOTALL)
    
    # Remove other quote block artifacts  
    text = re.sub(r'>\s*Carefully review.*?(?=\n\n|\n$)', '', text, flags=re.DOTALL)
    
    # Remove empty lines that result from artifact removal
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    
    return text.strip()


def clean_diff_artifacts(diff: str) -> str:
    """Clean up diff artifacts and markers."""
    if not diff:
        return diff
        
    # Remove @@ hunk markers - handle both @@ ... @@ and lone @@ lines
    diff = re.sub(r'^@@.*?@@.*?\n', '', diff, flags=re.MULTILINE)  # Full hunk headers
    diff = re.sub(r'^\s*@@\s*\n', '', diff, flags=re.MULTILINE)    # Lone @@ lines
    
    # Remove empty lines at start/end
    diff = diff.strip()
    
    return diff


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
                        code_diff = clean_html_artifacts(code_diff)  # Remove any HTML comments in diffs
                        code_diff = clean_diff_artifacts(code_diff)  # Clean up @@ markers and artifacts
                
                # Clean up description
                description = clean_html_artifacts(description)  # Remove HTML comments first
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


def group_comments_by_file(coderabbit_reviews: List[Dict[str, Any]], inline_comments: List[Dict[str, Any]] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Group all comments by file for better organization."""
    file_groups = {}
    
    # Process review body comments
    for review in coderabbit_reviews:
        sections = parse_review_sections(review['body'])
        
        # Add outside diff comments
        if 'outside_diff_comments' in sections:
            outside_comments = parse_file_level_comments(sections['outside_diff_comments']['content'])
            for comment in outside_comments:
                file_path = comment['file']
                if file_path not in file_groups:
                    file_groups[file_path] = []
                comment['source'] = 'outside_diff'
                file_groups[file_path].append(comment)
        
        # Add nitpick comments
        if 'nitpick_comments' in sections:
            nitpick_comments = parse_file_level_comments(sections['nitpick_comments']['content'])
            for comment in nitpick_comments:
                file_path = comment['file']
                if file_path not in file_groups:
                    file_groups[file_path] = []
                comment['source'] = 'nitpick'
                file_groups[file_path].append(comment)
    
    # Process inline comments
    if inline_comments:
        for comment in inline_comments:
            file_path = comment.get('path', 'unknown')
            line_num = comment.get('original_line', 'unknown')
            
            if file_path not in file_groups:
                file_groups[file_path] = []
                
            # Convert inline comment to standard format
            body = comment.get('body', '')
            comment_type = '🛠️ Refactor Suggestion' if '🛠️ Refactor suggestion' in body else 'Comment'
            
            # Extract title from body
            title_match = re.search(r'\*\*(.*?)\*\*', body)
            title = title_match.group(1).strip() if title_match else "Suggestion"
            
            # Extract description and diff
            if '<details>' in body and 'Prompt for AI Agents' in body:
                main_content = body.split('<details>')[0].strip()
            else:
                main_content = body
                
            main_content = main_content.replace('_🛠️ Refactor suggestion_', '').strip()
            main_content = clean_html_artifacts(main_content)
            
            # Extract AI prompt
            ai_prompt = ""
            ai_prompt_match = re.search(r'<summary>🤖 Prompt for AI Agents</summary>\s*\n\n```\n(.*?)\n```', body, re.DOTALL)
            if ai_prompt_match:
                ai_prompt = ai_prompt_match.group(1).strip()
            
            file_groups[file_path].append({
                'lines': str(line_num),
                'title': title,
                'description': main_content,
                'code_diff': '',  # Inline comments don't have separate diffs
                'ai_prompt': ai_prompt,
                'source': 'inline',
                'comment_type': comment_type
            })
    
    return file_groups


def format_for_llm(coderabbit_reviews: List[Dict[str, Any]], inline_comments: List[Dict[str, Any]] = None) -> str:
    """Format CodeRabbit review feedback organized by file for LLM consumption."""
    output = []
    output.append("# CodeRabbit Review Feedback")
    output.append("=" * 40)
    output.append("")
    
    # Group all comments by file
    file_groups = group_comments_by_file(coderabbit_reviews, inline_comments)
    
    if not file_groups:
        output.append("No actionable comments found.")
        return "\n".join(output)
    
    # Add summary
    total_comments = sum(len(comments) for comments in file_groups.values())
    output.append(f"**Total files with feedback:** {len(file_groups)}")
    output.append(f"**Total comments:** {total_comments}")
    output.append("")
    
    # Process each file
    for file_path in sorted(file_groups.keys()):
        comments = file_groups[file_path]
        
        output.append(f"## {file_path}")
        output.append(f"**{len(comments)} suggestion(s)**")
        output.append("")
        
        # Sort comments by priority: AI prompts first, then by line number
        def get_sort_key(comment):
            # Priority 1: Comments with AI prompts (highest priority)
            has_ai_prompt = bool(comment.get('ai_prompt'))
            
            # Priority 2: Line number (for logical code flow)
            line_num = 999
            if comment['lines'].replace('-', '').isdigit():
                line_num = int(comment['lines'].split('-')[0])
                
            # Return tuple: (ai_prompt_priority, line_number)
            # Lower numbers = higher priority, so AI prompts get 0, others get 1
            return (0 if has_ai_prompt else 1, line_num)
        
        comments_sorted = sorted(comments, key=get_sort_key)
        
        for i, comment in enumerate(comments_sorted, 1):
            # Add AI prompt indicator to title for high-priority items
            title = comment['title']
            if comment.get('ai_prompt'):
                title = f"🤖 {title}"
                
            output.append(f"### {i}. Lines {comment['lines']}: {title}")
            output.append(f"**Source:** {comment['source']}")
            if comment.get('comment_type'):
                output.append(f"**Type:** {comment['comment_type']}")
            output.append("")
            
            # Description
            if comment['description']:
                output.append("**Issue:**")
                output.append(comment['description'])
                output.append("")
            
            # Code diff
            if comment['code_diff']:
                output.append("**Suggested change:**")
                output.append("```diff")
                output.append(comment['code_diff'])
                output.append("```")
                output.append("")
            
            # AI implementation instructions
            if comment.get('ai_prompt'):
                output.append("**🤖 AI Implementation Instructions:**")
                output.append("```")
                output.append(comment['ai_prompt'])
                output.append("```")
                output.append("")
            
            if i < len(comments_sorted):
                output.append("-" * 30)
                output.append("")
        
        output.append("=" * 60)
        output.append("")
    
    return "\n".join(output)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="""
CodeRabbit Review Extractor - Convert GitHub PR reviews to LLM-friendly text

This tool extracts CodeRabbit automated code review feedback from GitHub pull 
requests and formats it as clean, organized text suitable for AI coding agents.

Perfect for feeding CodeRabbit suggestions to Claude, ChatGPT, or other LLMs
to automatically apply code improvements, refactoring suggestions, and fixes.
        """.strip(),
        epilog="""
EXAMPLES:
  %(prog)s https://github.com/owner/repo/pull/123
  %(prog)s owner/repo/123  
  %(prog)s obra/lace/278 --all-reviews

WHAT IT EXTRACTS:
  • Refactor suggestions with specific code diffs
  • AI implementation instructions (🤖 prompts) with detailed steps  
  • Nitpick comments and code quality improvements
  • File-organized feedback sorted by priority
  • Clean format without HTML artifacts or noise

HOW IT WORKS:
  1. Uses 'gh' CLI to fetch PR reviews (works with private repos)
  2. Extracts both main review summaries and inline code comments
  3. Organizes feedback by file with line-number targeting
  4. Prioritizes actionable items with AI implementation guides
  5. Outputs clean text ready for LLM consumption

DEFAULT BEHAVIOR:
  Processes only the LATEST CodeRabbit review to avoid overwhelming output.
  Use --all-reviews for PRs with multiple review iterations if needed.

REQUIREMENTS:
  • GitHub CLI (gh) installed and authenticated
  • Python 3.6+ with beautifulsoup4 package
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('pr_input', 
                       help='GitHub PR URL or owner/repo/number format (e.g., "owner/repo/123")')
    parser.add_argument('--all-reviews', 
                       action='store_true',
                       help='Extract all CodeRabbit reviews (default: latest only)')
    parser.add_argument('--since-commit',
                       metavar='SHA', 
                       help='Extract reviews submitted after this commit SHA')
    
    # Custom handling for no arguments to show helpful info
    if len(sys.argv) == 1:
        print("🤖 CodeRabbit Review Extractor")
        print("=" * 40)
        print()
        print("WHAT THIS DOES:")
        print("  Converts CodeRabbit GitHub PR reviews into clean text for AI coding agents")
        print("  (Claude, ChatGPT, etc.) to automatically apply code suggestions.")
        print()
        print("QUICK START:")
        print("  python3 extract-coderabbit-feedback.py https://github.com/owner/repo/pull/123")
        print("  python3 extract-coderabbit-feedback.py owner/repo/123")
        print()
        print("For full help and options, run:")
        print("  python3 extract-coderabbit-feedback.py --help")
        sys.exit(1)
    
    args = parser.parse_args()
    
    try:
        pr_url = parse_pr_input(args.pr_input)
        
        # Fetch both reviews and inline comments
        reviews = fetch_pr_reviews(pr_url)
        inline_comments = fetch_pr_inline_comments(pr_url)
        
        coderabbit_reviews = extract_coderabbit_reviews(reviews)
        
        # Filter reviews based on options
        if not args.all_reviews and not args.since_commit:
            # Default: latest review only
            if coderabbit_reviews:
                coderabbit_reviews = [coderabbit_reviews[-1]]  # Take the last (most recent) review
        elif args.since_commit:
            # Filter reviews submitted after the specified commit
            # This would require additional logic to compare timestamps with commit dates
            print("--since-commit option not yet implemented", file=sys.stderr)
            sys.exit(1)
        
        coderabbit_inline_comments = extract_coderabbit_inline_comments(inline_comments)
        
        if not coderabbit_reviews and not coderabbit_inline_comments:
            print("No CodeRabbit reviews or comments found in this PR.", file=sys.stderr)
            sys.exit(1)
        
        # Show processing info
        if len(coderabbit_reviews) > 1:
            print(f"Processing {len(coderabbit_reviews)} CodeRabbit reviews...", file=sys.stderr)
        elif len(coderabbit_reviews) == 1:
            print(f"Processing latest CodeRabbit review...", file=sys.stderr)
            
        if coderabbit_inline_comments:
            print(f"Found {len(coderabbit_inline_comments)} inline comments", file=sys.stderr)
        
        formatted_output = format_for_llm(coderabbit_reviews, coderabbit_inline_comments)
        print(formatted_output)
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()