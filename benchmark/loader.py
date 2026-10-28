"""Read and validate the question set. Stage 3.1.

`benchmark/questions/questions.csv` is hand-written in a spreadsheet, which is
the pleasant way to author fifty rows and a reliable way to introduce a typo
that nothing notices. So this module's job is less "parse" than "refuse".

── Every bad row, never the first ─────────────────────────────────────────────

`load_questions` returns problems rather than raising on them, and it collects
**all** of them. A loader that dies on the first defect turns a question set
with four mistakes into four edit-run cycles, and the fourth is found twenty
minutes after the first. The runner prints the whole list and exits.

Structural failures — a missing file, a header that is not the expected one —
*do* raise, because no row can be interpreted at all and a list of fifty
identical complaints is not useful.

── The check nothing else can make ───────────────────────────────────────────

Gold page numbers are validated against each document's **real page count**,
read with `pypdf`. "Gold page 250" in a 194-page document is a plausible typo
that every other check passes: the row is well-formed, the type is valid, the
document exists, and the question would simply never be answerable by any
retriever. It would show up as an unexplained zero in the baseline.
"""

import csv
import pathlib
from dataclasses import dataclass

from pypdf import PdfReader

COLUMNS = [
    "id",
    "document",
    "question",
    "gold_pages",
    "gold_answer",
    "type",
    "answerable",
]

ANSWERABLE_TYPES = frozenset({"lookup", "numeric", "definition", "table", "multi_page"})
UNANSWERABLE_TYPES = frozenset({"near_miss", "out_of_domain"})
QUESTION_TYPES = ANSWERABLE_TYPES | UNANSWERABLE_TYPES

PAGE_SEPARATOR = ";"
"""Gold pages are semicolon-separated, because the comma is the delimiter."""


@dataclass(frozen=True)
class EvalQuestion:
    """One validated question."""

    id: str
    document: str | None
    """None only for `out_of_domain`, where no document is relevant."""

    question: str
    gold_pages: frozenset[int]
    """Empty when unanswerable. 1-indexed, as `Chunk.page` records them."""

    gold_answer: str
    type: str
    answerable: bool


@dataclass(frozen=True)
class Problem:
    """One reason one row was rejected."""

    row: int
    """1-indexed line number in the file, counting the header — what an editor shows."""

    id: str
    message: str

    def __str__(self) -> str:
        return f"line {self.row} ({self.id or 'no id'}): {self.message}"


@dataclass(frozen=True)
class LoadResult:
    questions: list[EvalQuestion]
    problems: list[Problem]

    @property
    def ok(self) -> bool:
        return not self.problems


def page_counts(documents_dir: pathlib.Path) -> dict[str, int]:
    """How many pages each corpus document has.

    Read once per run. `PdfReader` parses the cross-reference table rather than
    every page's content, so this is cheap even for the 230-page scan.
    """
    counts: dict[str, int] = {}

    for path in sorted(documents_dir.glob("*.pdf")):
        try:
            counts[path.name] = len(PdfReader(path).pages)
        except Exception as exc:  # a corrupt corpus file is a real possibility
            raise RuntimeError(f"Could not read {path.name}: {exc}") from exc

    return counts


def load_questions(
    csv_path: pathlib.Path, *, documents_dir: pathlib.Path
) -> LoadResult:
    """Read the question set, validating every row.

    Raises:
        FileNotFoundError: the question file or documents directory is missing.
        ValueError: the header is not `COLUMNS`.
        RuntimeError: a corpus PDF could not be read.
    """
    if not csv_path.exists():
        raise FileNotFoundError(
            f"No question set at {csv_path}. See "
            f"benchmark/questions/README.md — the schema and five worked "
            f"examples are there, and questions.example.csv is the header."
        )
    if not documents_dir.is_dir():
        raise FileNotFoundError(f"No corpus directory at {documents_dir}.")

    pages = page_counts(documents_dir)

    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)

        if reader.fieldnames != COLUMNS:
            raise ValueError(
                f"Unexpected header in {csv_path.name}.\n"
                f"  expected: {','.join(COLUMNS)}\n"
                f"  found:    {','.join(reader.fieldnames or [])}"
            )

        rows = list(enumerate(reader, start=2))

    questions: list[EvalQuestion] = []
    problems: list[Problem] = []
    seen: dict[str, int] = {}

    for line, row in rows:
        row_problems, question = _validate(row, line=line, pages=pages)

        identifier = (row.get("id") or "").strip()
        if identifier and identifier in seen:
            row_problems.append(
                Problem(
                    line,
                    identifier,
                    f"duplicate id, first used on line {seen[identifier]}. Ids are "
                    f"how results are compared across runs, so two rows sharing "
                    f"one makes a baseline uncomparable rather than merely untidy.",
                )
            )
        elif identifier:
            seen[identifier] = line

        if row_problems:
            problems.extend(row_problems)
        elif question is not None:
            questions.append(question)

    return LoadResult(questions=questions, problems=problems)


def _validate(
    row: dict[str, str | None], *, line: int, pages: dict[str, int]
) -> tuple[list[Problem], EvalQuestion | None]:
    """Check one row. Returns every problem with it, and the question if clean."""
    problems: list[Problem] = []

    def complain(message: str) -> None:
        problems.append(Problem(line, identifier, message))

    identifier = (row.get("id") or "").strip()
    document = (row.get("document") or "").strip()
    question = (row.get("question") or "").strip()
    raw_pages = (row.get("gold_pages") or "").strip()
    gold_answer = (row.get("gold_answer") or "").strip()
    kind = (row.get("type") or "").strip()
    raw_answerable = (row.get("answerable") or "").strip().lower()

    if not identifier:
        complain("missing id")
    if not question:
        complain("missing question")

    # ── type and answerable, which constrain each other ───────────────────────
    if kind not in QUESTION_TYPES:
        complain(f"unknown type {kind!r}; expected one of {sorted(QUESTION_TYPES)}")

    answerable: bool | None = {"true": True, "false": False}.get(raw_answerable)
    if answerable is None:
        complain(f"answerable must be 'true' or 'false', found {raw_answerable!r}")

    if answerable is not None and kind in QUESTION_TYPES:
        expected = kind in ANSWERABLE_TYPES
        if answerable != expected:
            complain(
                f"type {kind!r} and answerable={raw_answerable} disagree; "
                f"{sorted(UNANSWERABLE_TYPES)} are the unanswerable types"
            )

    # ── the document ──────────────────────────────────────────────────────────
    if kind == "out_of_domain":
        if document:
            complain(
                "out_of_domain questions name no document, because no document "
                "is relevant to them by definition"
            )
    elif not document:
        complain("missing document (required for every type except out_of_domain)")
    elif document not in pages:
        complain(
            f"unknown document {document!r}; the corpus holds {sorted(pages)}"
        )

    # ── gold pages ────────────────────────────────────────────────────────────
    gold_pages: set[int] = set()

    # Remembered so that one defect produces one message. A page beyond the end
    # of the document leaves `gold_pages` empty, which would otherwise trip the
    # "answerable question with no gold_pages" check below and report the same
    # typo twice — turning a four-mistake file into eight complaints, half of
    # them consequences of the other half.
    problems_before_pages = len(problems)

    if raw_pages:
        for part in raw_pages.split(PAGE_SEPARATOR):
            part = part.strip()
            if not part:
                continue
            try:
                number = int(part)
            except ValueError:
                complain(f"gold page {part!r} is not a number")
                continue
            if number < 1:
                complain(f"gold page {number} is not 1-indexed")
                continue

            limit = pages.get(document)
            if limit is not None and number > limit:
                complain(
                    f"gold page {number} is beyond {document} ({limit} pages). "
                    f"A retriever can never satisfy this question, so it would "
                    f"read as an unexplained zero in the baseline."
                )
                continue

            gold_pages.add(number)

    if answerable is True:
        # Only when nothing usable was given *and* no page was individually
        # rejected. `gold_pages=";"` reaches here with no page-level complaint
        # and an empty set, so the check cannot simply test `raw_pages`.
        if not gold_pages and len(problems) == problems_before_pages:
            complain("answerable question with no gold_pages")
        if not gold_answer:
            complain(
                "answerable question with no gold_answer. The runner does not "
                "grade answer text, but writing it is what confirms the fact "
                "really is on that page"
            )
    elif answerable is False:
        if gold_pages:
            complain("unanswerable question with gold_pages")
        if gold_answer:
            complain("unanswerable question with a gold_answer")

    if problems:
        return problems, None

    assert answerable is not None  # every path above complained otherwise

    return [], EvalQuestion(
        id=identifier,
        document=document or None,
        question=question,
        gold_pages=frozenset(gold_pages),
        gold_answer=gold_answer,
        type=kind,
        answerable=answerable,
    )
