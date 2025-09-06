# CodeRabbit Review Extractor

Convert CodeRabbit GitHub PR reviews into clean, LLM-friendly text for AI-assisted code improvement workflows.

## What This Does

CodeRabbit provides excellent automated code review feedback, but it's designed for human consumption in GitHub's web interface. This tool extracts that feedback and formats it specifically for AI coding agents (Claude, ChatGPT, etc.) to automatically apply suggestions.

Perfect for:
- 🤖 **AI-assisted development workflows**
- 🔄 **Automated code improvement pipelines** 
- 📝 **Converting review feedback to actionable prompts**
- 🚀 **Streamlining the code review → implementation cycle**

## Quick Start

```bash
# Basic usage - latest review only (recommended)
python3 extract-coderabbit-feedback.py obra/lace/278

# All reviews (for complex analysis)
python3 extract-coderabbit-feedback.py obra/lace/255 --all-reviews

# Get help
python3 extract-coderabbit-feedback.py --help
```

## Installation

### Requirements
- **GitHub CLI** (`gh`) installed and authenticated
- **Python 3.6+** 
- **beautifulsoup4** package

### Install Dependencies
```bash
pip install beautifulsoup4
```

### Setup GitHub CLI
```bash
# Install gh CLI
brew install gh  # macOS
# or follow: https://cli.github.com/

# Authenticate (works with private repos)
gh auth login
```

## Features

### 🎯 Smart Review Handling
- **Latest review by default** - Avoids overwhelming output from PRs with 20+ reviews
- **File-organized output** - Groups all feedback by file for easy navigation
- **Priority sorting** - AI-actionable items (🤖) appear first within each file

### 🤖 LLM-Optimized Format
- **AI prompts prioritized** - Detailed implementation instructions when available
- **Clean diffs** - Fallback for simple mechanical changes
- **No redundancy** - Never shows both prompt AND diff for the same suggestion
- **HTML-free output** - Stripped of GitHub web interface artifacts

### 📊 Example Output
```
# CodeRabbit Review Feedback
========================================

**Total files with feedback:** 11
**Total comments:** 46

## packages/core/src/config/user-settings.ts
**6 suggestion(s)**

### 1. Lines 13: 🤖 Replace all `any` with a safe JSON type (violates "no-explicit-any").

**Proposed prompt:**
```
In packages/core/src/config/user-settings.ts around lines 13, 26, 52 and 68,
replace the use of `any` with a concrete JSON-safe type: add a JsonValue
(recursive union: string | number | boolean | null | JsonValue[] | { [key:
string]: JsonValue }) and a UserSettings = Record<string, JsonValue> (or a more
specific shape if known), then change private static cachedSettings, method
parameters and return types to use UserSettings/JsonValue instead of any...
```

### 2. Lines 42: Consolidate ABOUTME comments

```diff
-// ABOUTME: Simple user settings manager for arbitrary JSON preferences
-// ABOUTME: Stores settings in ~/.lace/user-settings.json with no validation
+// ABOUTME: Simple user settings manager for arbitrary JSON preferences stored in ~/.lace/user-settings.json (no validation)
```
```

## Options

### Review Selection
- **Default**: Latest review only (avoids overwhelming multi-review PRs)
- **`--all-reviews`**: Extract all CodeRabbit reviews
- **`--since-commit SHA`**: Reviews after specific commit (coming soon)

### Debug Mode
- **`--debug`**: Show processing annotations to understand decisions

### Input Formats
- **Full URL**: `https://github.com/owner/repo/pull/123`
- **Short format**: `owner/repo/123`

## Advanced Usage

### Pathological Multi-Review PRs
Some PRs accumulate dozens of reviews as code evolves:
```bash
# Problem: 20 reviews = 300 comments across 36 files (overwhelming)
python3 extract-coderabbit-feedback.py obra/lace/255 --all-reviews

# Solution: Latest review only = 58 comments across 22 files (manageable) 
python3 extract-coderabbit-feedback.py obra/lace/255
```

### Integration with AI Assistants
```bash
# Pipe directly to AI coding assistants
python3 extract-coderabbit-feedback.py owner/repo/123 | claude-api "Apply these suggestions"

# Save for batch processing
python3 extract-coderabbit-feedback.py owner/repo/123 > feedback.txt
```

## Output Format

The tool extracts and organizes three types of CodeRabbit feedback:

### 1. 🤖 AI-Actionable Items (Prioritized)
- **Refactor suggestions** with detailed implementation prompts
- **Cross-file changes** with scope guidance
- **Security fixes** with context and alternatives
- **Complex architectural changes** with step-by-step instructions

### 2. Nitpick Comments
- **Style improvements** with simple diffs
- **Best practice suggestions** with explanations
- **Minor optimizations** with code examples

### 3. Outside Diff Range Comments  
- **Issues outside the changed lines** with context
- **Broader pattern suggestions** affecting multiple files
- **Architectural recommendations** for consideration

## Why This Format Works

### Problem-Focused vs Solution-Prescriptive
- **Traditional diffs**: "Change A to B" (prescriptive)
- **AI prompts**: "Problem X causes Y, consider approaches Z" (explanatory)

### Token Efficiency
- **Eliminates redundancy** between descriptions, diffs, and prompts
- **20% more concise** output while preserving critical information
- **Priority-sorted** so AI focuses on most important items first

### Implementation Flexibility
- **AI prompts** let agents find the best solution approach
- **Simple diffs** provide precise guidance for mechanical changes
- **Context preservation** for cross-file and multi-step changes

## Development

### Debug Mode
Use `--debug` to see processing decisions:
```bash
python3 extract-coderabbit-feedback.py obra/lace/278 --debug
```
Shows annotations like:
```
<!-- DEBUG: has_prompt=True, has_diff=False, source=inline -->
<!-- DEBUG: Showing prompt only, skipping description and diff -->
```

### Contributing
This tool evolved through systematic agent feedback and iterative improvement:
1. Initial extraction with HTML corruption issues
2. Agent review identified formatting problems
3. Step-by-step commits fixing each issue class
4. Focus group validation of prompt-vs-diff prioritization

## License

MIT License - Feel free to use, modify, and distribute.

---

*Built to bridge the gap between excellent automated code review (CodeRabbit) and excellent automated code improvement (AI coding agents).*