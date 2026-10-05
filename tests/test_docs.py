"""The documentation must not drift from the repository it describes."""

import re
from pathlib import Path

import pytest

from countersign.eval import compare
from countersign.llm.prompts import DEFAULT_PROMPT

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
EVALUATION = ROOT / "docs" / "evaluation.md"
PAGES = [README, *sorted((ROOT / "docs").glob("*.md"))]
REPORTS = ROOT / "evals" / "reports"
# The reports of the two live runs as they were written. They are a record: the code
# that produced them has changed since (see evals/history/README.md).
HISTORY = ROOT / "evals" / "history"

_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_TABLE = re.compile(r"<!-- table:([a-z]+):([a-z-]+) -->\n(.*?)\n<!-- /table -->", re.DOTALL)
_IMAGE = re.compile(r"(?:src|srcset)=\"([^\"]+)\"")


@pytest.mark.parametrize("page", PAGES, ids=lambda page: page.name)
def test_relative_links_point_at_files_that_exist(page: Path) -> None:
    text = page.read_text(encoding="utf-8")
    for target in [*_LINK.findall(text), *_IMAGE.findall(text)]:
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path = (page.parent / target.split("#")[0]).resolve()
        assert path.exists(), f"{page.name} links to {target}, which does not exist"


def _tables(page: Path) -> dict[tuple[str, str], str]:
    return {
        (kind, source): content
        for kind, source, content in _TABLE.findall(page.read_text(encoding="utf-8"))
    }


@pytest.mark.parametrize("page", [README, EVALUATION], ids=lambda page: page.name)
def test_every_table_of_a_page_is_what_the_reports_give(page: Path) -> None:
    if not (REPORTS / "confirm-cascade.json").exists():
        pytest.skip("the evaluation has not been run")
    tables = _tables(page)
    assert tables
    for (kind, source), content in tables.items():
        assert content == compare.table(kind, source, REPORTS, HISTORY), f"{kind} of {source}"


def test_the_pages_carry_the_tables_they_announce() -> None:
    measured = ("confirm-run", "test-run")
    recomputed = ("confirm", "test", "dev")
    assert set(_tables(README)) == {("configurations", "confirm-run")}
    assert set(_tables(EVALUATION)) == {
        *(("configurations", source) for source in (*measured, *recomputed)),
        ("prompts", "dev"),
        ("groups", "confirm-run"),
        ("scenarios", "confirm-run"),
        ("tiers", "confirm-run"),
    }


def test_the_documentation_names_the_prompt_in_use() -> None:
    version = DEFAULT_PROMPT.removeprefix("extract_")
    assert f"{version}:" in compare.PROMPTS[-1][1]
    assert (ROOT / "src" / "countersign" / "llm" / "prompts" / f"{DEFAULT_PROMPT}.txt").exists()


def test_every_setting_is_documented() -> None:
    from countersign.config import Settings

    operations = (ROOT / "docs" / "operations.md").read_text(encoding="utf-8")
    undocumented = [
        name
        for name in Settings.model_fields
        if f"`{name.upper()}`" not in operations and name.upper() not in operations
    ]
    assert undocumented == []


def test_every_command_is_documented() -> None:
    from countersign import cli

    operations = (ROOT / "docs" / "operations.md").read_text(encoding="utf-8")
    commands = re.findall(r"^countersign (\w+)", cli.__doc__ or "", flags=re.MULTILINE)
    assert len(commands) >= 6
    assert [name for name in commands if f"`countersign {name}" not in operations] == []
