"""Documentation entry-point link tests."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]

DOCS_TO_CHECK = (
    ROOT / "README.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "design" / "section-design-index.md",
)

LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class DocsLinkTest(unittest.TestCase):
    def test_entry_point_local_links_exist(self) -> None:
        missing: list[str] = []
        for path in DOCS_TO_CHECK:
            for target in _local_links(path):
                target_path = (path.parent / target).resolve()
                if not target_path.exists():
                    missing.append(f"{path.relative_to(ROOT)} -> {target}")

        self.assertEqual(missing, [])


def _local_links(path: Path) -> list[str]:
    links: list[str] = []
    for match in LINK_PATTERN.finditer(path.read_text(encoding="utf-8")):
        target = match.group(1).split("#", 1)[0]
        if not target or "://" in target or target.startswith("#"):
            continue
        links.append(target)
    return links


if __name__ == "__main__":
    unittest.main()
