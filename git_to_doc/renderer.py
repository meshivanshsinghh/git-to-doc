from datetime import date
from git_to_doc.model import CommitDoc

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
YELLOW = "\033[33m"
DIM    = "\033[2m"
WHITE  = "\033[97m"

def _c(text: str, *codes: str) -> str:
    return "".join(codes) + text + RESET


_SECTION = {
    "feat":     "Added",
    "fix":      "Fixed",
    "docs":     "Documentation",
    "refactor": "Changed",
    "perf":     "Performance",
    "test":     "Tests",
    "chore":    "Maintenance",
    "ci":       "CI/CD",
    "build":    "Build",
    "revert":   "Reverted",
}

_TYPE_EMOJI = {
    "feat":     "✨",
    "fix":      "🐛",
    "docs":     "📝",
    "refactor": "♻️",
    "perf":     "⚡",
    "test":     "🧪",
    "chore":    "🔧",
    "ci":       "🤖",
    "build":    "📦",
    "revert":   "⏪",
}


def render_commit_message(doc: CommitDoc) -> str:
    """Returns a Conventional Commit string, e.g. feat(scope): subject"""
    scope    = f"({doc.scope})" if doc.scope else ""
    breaking = "!" if doc.breaking else ""
    header   = f"{doc.type}{scope}{breaking}: {doc.subject}"

    parts = [header]
    if doc.body:
        parts.append(f"\n{doc.body}")
    if doc.breaking:
        parts.append(f"\nBREAKING CHANGE: {doc.body or doc.subject}")
    return "\n".join(parts)


def render_changelog(doc: CommitDoc) -> str:
    """Returns a markdown changelog snippet ready to paste into CHANGELOG.md"""
    today   = date.today().isoformat()
    section = "⚠️ Breaking Changes" if doc.breaking else _SECTION.get(doc.type, "Changed")

    lines = [
        f"## [Unreleased] — {today}",
        "",
        f"### {section}",
        "",
        doc.changelog_entry,
    ]
    if doc.body:
        lines += ["", f"  {doc.body}"]
    return "\n".join(lines)


def render_full_output(doc: CommitDoc) -> str:
    """Pretty-prints the full terminal output with colour and markdown blocks."""
    emoji = _TYPE_EMOJI.get(doc.type, "📌")
    bar   = _c("─" * 58, DIM)

    commit_msg  = render_commit_message(doc)
    changelog   = render_changelog(doc)

    output = f"""
{bar}
{_c(f"  {emoji}  CONVENTIONAL COMMIT MESSAGE", BOLD, CYAN)}
{bar}

  {_c(commit_msg, BOLD, WHITE)}

{bar}
{_c("  📋  CHANGELOG ENTRY  (paste into CHANGELOG.md)", BOLD, CYAN)}
{bar}

{changelog}

{bar}
{_c("  🗣️   PLAIN ENGLISH SUMMARY", BOLD, CYAN)}
{bar}

  {_c(doc.plain_english, YELLOW)}

{bar}
"""
    return output


def render_markdown_file(doc: CommitDoc, model: str = "gemma4",
                          source: str = "", stats: dict = None) -> str:
    """Returns a reviewer-first markdown doc: merge-safety callout, clean
    copy-paste blocks, and collapsible files/metadata sections."""
    emoji  = _TYPE_EMOJI.get(doc.type, "📌")
    today  = date.today().isoformat()
    header = doc.human_title

    # 1. Merge-safety callout — the first thing a reviewer needs
    if doc.breaking:
        callout = ("> [!WARNING]\n"
                   "> **Breaking change** — review before merging. "
                   "Existing API behavior changes.")
    else:
        callout = "> [!NOTE]\n> **Non-breaking change** — safe to merge."

    # 2. One-line at-a-glance strip
    n_files  = len(stats["files"]) if stats and stats.get("files") else 0
    diffstat = f" · +{stats.get('additions', 0)} / -{stats.get('deletions', 0)}" if stats else ""
    stat_line = (f"`{doc.type}` · scope `{doc.scope or '—'}` · "
                 f"{n_files} file(s) changed{diffstat} · via git-to-doc + `{model}`")

    # 3. CLEAN copy-paste commit block (nothing decorative inside)
    commit_block = f"{doc.type}{scope}{'!' if doc.breaking else ''}: {doc.subject}"
    if doc.body:
        commit_block += f"\n\n{doc.body}"
    if doc.breaking:
        commit_block += f"\n\nBREAKING CHANGE: {doc.body or doc.subject}"

    # 4. Changelog snippet = section bucket + bullet (paste under Unreleased)
    section = _SECTION.get(doc.type, "Changed")
    changelog_block = f"### {section}\n{doc.changelog_entry}"

    files_section = ""
    if stats and stats.get("files"):
        file_lines = []
        for f in stats["files"]:
            note = doc.file_notes.get(f)
            if note:
                file_lines.append(f"- `{f}` — {note}")
            else:
                file_lines.append(f"- `{f}`")
        files_list = "\n".join(file_lines)
        files_section = (f"<details>\n<summary>Files changed ({n_files})</summary>\n\n"
                         f"{files_list}\n\n</details>\n\n")

    review_section = ""
    if doc.review_notes:
        review_section = f"## Review Notes\n\n{doc.review_notes}\n\n"

    src_row = f"| Source | {source} |\n" if source else ""
    meta_section = (f"<details>\n<summary>Metadata</summary>\n\n"
                    f"| Field | Value |\n|-------|-------|\n"
                    f"| Type | `{doc.type}` |\n"
                    f"| Scope | `{doc.scope or '—'}` |\n"
                    f"| Breaking | {'⚠️ Yes' if doc.breaking else 'No'} |\n"
                    f"| Model | `{model}` |\n{src_row}"
                    f"| Generated | {today} |\n\n</details>\n")

    return f"""# {emoji} {header}

{callout}

{stat_line}

---

## What changed

{doc.plain_english}

## Commit message

```
{commit_block}
```

## Changelog entry — paste into `CHANGELOG.md`

```markdown
{changelog_block}
```

{review_section}{files_section}{meta_section}"""

