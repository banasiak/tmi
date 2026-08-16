"""The layering rules, enforced rather than described.

This page is assembled from whatever sources happen to be present, so the
arrangement below is load-bearing rather than tidy:

    analysis  ->  sections  ->  report

`analysis` measures the house and knows nothing about HTML. Each section reads
only from `analysis` — never from another section — so a missing export can drop
one section without silently corrupting a later one. These used to be
conventions kept by hand, and the hand slipped: a value computed in the solar
section was read by the provenance section, and a value computed inside the
hourly-water section was read at module level by prose that ran whether or not
that section had.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from src import sections

ROOT = Path(__file__).resolve().parent.parent
SECTION_DIR = ROOT / "src" / "sections"
SECTION_FILES = sorted(p for p in SECTION_DIR.glob("*.py")
                       if p.name != "__init__.py")


def imported_modules(path: Path) -> set[str]:
    """Every `src.*` module a file imports, however it spells the import."""
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("src"):
                found.add(node.module)
                for alias in node.names:
                    found.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src"):
                    found.add(alias.name)
    return found


class SectionsAreIndependent(unittest.TestCase):
    def test_every_section_module_is_registered(self):
        registered = {m.__name__.rsplit(".", 1)[-1] for m in sections.MODULES}
        on_disk = {p.stem for p in SECTION_FILES}
        self.assertEqual(registered, on_disk,
                         "a section module exists that the page never builds")

    def test_every_section_exposes_build(self):
        for module in sections.MODULES:
            with self.subTest(module.__name__):
                self.assertTrue(callable(getattr(module, "build", None)))

    def test_no_section_imports_another_section(self):
        """The invariant that lets the page survive a missing source."""
        names = {p.stem for p in SECTION_FILES}
        for path in SECTION_FILES:
            with self.subTest(path.name):
                siblings = {
                    mod for mod in imported_modules(path)
                    if mod.startswith("src.sections")
                    and mod.rsplit(".", 1)[-1] in names - {path.stem}
                }
                self.assertEqual(siblings, set(),
                                 f"{path.name} depends on another section")

    def test_no_section_imports_the_build_script(self):
        for path in SECTION_FILES:
            with self.subTest(path.name):
                self.assertNotIn("build", {m.split(".")[0]
                                           for m in imported_modules(path)})


class AnalysisKnowsNothingAboutHtml(unittest.TestCase):
    def test_analysis_does_not_import_the_presentation_layer(self):
        forbidden = {"src.report", "src.charts", "src.palette", "src.sections"}
        imported = imported_modules(ROOT / "src" / "analysis.py")
        self.assertEqual(imported & forbidden, set())

    def test_analysis_emits_no_markup(self):
        """A stray tag here would be a figure no section could be held to."""
        source = (ROOT / "src" / "analysis.py").read_text()
        self.assertNotIn("<div", source)
        self.assertNotIn("<p>", source)
        self.assertNotIn("<td>", source)


class TheAnalysisContractIsExact(unittest.TestCase):
    """Every field is read by somebody, and everything read is a field."""

    @staticmethod
    def declared_fields() -> set[str]:
        source = (ROOT / "src" / "analysis.py").read_text()
        body = source.split("class Analysis", 1)[1].split("\ndef ", 1)[0]
        return set(re.findall(r"^    (\w+): ", body, re.M))

    @staticmethod
    def consumer_source() -> str:
        return "".join(p.read_text() for p in SECTION_FILES) + \
            (ROOT / "build.py").read_text()

    def test_no_field_goes_unread(self):
        """A field nobody reads is a measurement the page stopped making."""
        consumers = self.consumer_source()
        unread = sorted(f for f in self.declared_fields()
                        if f"data.{f}" not in consumers)
        self.assertEqual(unread, [], "unread Analysis fields")

    def test_nothing_is_read_that_was_never_declared(self):
        declared = self.declared_fields()
        used = set(re.findall(r"\bdata\.(\w+)", self.consumer_source()))
        self.assertEqual(sorted(used - declared), [])


class HouseConstantsAreCentral(unittest.TestCase):
    """Hand-supplied numbers live in one file, so they can be audited in one."""

    def test_no_section_hardcodes_the_pool_volume(self):
        for path in SECTION_FILES + [ROOT / "src" / "analysis.py"]:
            with self.subTest(path.name):
                self.assertNotIn("5000.0", path.read_text())

    def test_house_module_holds_no_logic(self):
        tree = ast.parse((ROOT / "src" / "house.py").read_text())
        self.assertEqual(
            [n for n in tree.body if isinstance(n, (ast.FunctionDef,
                                                    ast.ClassDef))], [])

    def test_equipment_declares_itself_a_record(self):
        """Unreferenced constants in `equipment` are kept on purpose.

        A dead-code sweep will flag the refrigerant charge, the locked-rotor
        amps and the garage dimensions every time, because nothing computes with
        them. They stay: a label reading costs a ladder and a flashlight to
        reacquire, and the machine may not be there next time. This test exists
        so the reasoning is discoverable from the tests as well as the docstring.
        """
        doc = ast.get_docstring(ast.parse(
            (ROOT / "src" / "equipment.py").read_text()))
        self.assertIn("a record, not a library", doc)
        self.assertIn("Do not treat an unreferenced constant", doc)


if __name__ == "__main__":
    unittest.main()
