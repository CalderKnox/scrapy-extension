#!/usr/bin/env bash
set -euo pipefail

docs_root=${1:-docs}
failures=0

if [[ ! -d "$docs_root" ]]; then
  echo "docs-check: missing directory: $docs_root" >&2
  exit 1
fi

while IFS= read -r directory; do
  if [[ ! -f "$directory/README.md" ]]; then
    echo "docs-check: missing $directory/README.md" >&2
    failures=1
  fi
  if [[ ! -f "$directory/_template.md" ]]; then
    echo "docs-check: missing $directory/_template.md" >&2
    failures=1
  fi
done < <(find "$docs_root" -type d -not -path '*/.*' -print | sort)

while IFS='|' read -r file link; do
  if ! rg -Fq "$link" "$file"; then
    echo "docs-check: $file must contain link $link" >&2
    failures=1
  fi
done <<'REQUIRED_LINKS'
docs/01-adrs/README.md|../02-design/01-decisions/_template.md
docs/02-design/README.md|../01-adrs/
docs/02-design/01-decisions/README.md|../../01-adrs/
REQUIRED_LINKS

if (( failures )); then
  exit 1
fi

echo "docs-check: all visible directories have README.md and _template.md"
