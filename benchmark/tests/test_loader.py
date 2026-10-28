"""Reading and refusing the question set. Stage 3.1.

The question set is hand-written in a spreadsheet, so these tests are mostly
about typos — and about the loader reporting *all* of them rather than the
first, which is the difference between one editing pass and four.
"""

import pathlib

import pytest

from benchmark.loader import load_questions
from benchmark.tests.conftest import LONG, LONG_PAGES, SHORT, SHORT_PAGES


def test_a_clean_file_loads(corpus: pathlib.Path, write_questions) -> None:
    path = write_questions(
        f"q1,{SHORT},What is on page two?,2,Page two,lookup,true",
        f"q2,{LONG},Which pages cover it?,3;4,Pages three and four,multi_page,true",
        f"q3,{LONG},What rate limit does it define?,,,near_miss,false",
        "q4,,What is the depth of the Trieste?,,,out_of_domain,false",
    )

    result = load_questions(path, documents_dir=corpus)

    assert result.ok, [str(p) for p in result.problems]
    assert [q.id for q in result.questions] == ["q1", "q2", "q3", "q4"]
    assert result.questions[1].gold_pages == frozenset({3, 4})
    assert result.questions[2].gold_pages == frozenset()
    assert result.questions[3].document is None


def test_every_invalid_row_is_reported_not_just_the_first(
    corpus: pathlib.Path, write_questions
) -> None:
    """**The behaviour this module exists for.**

    Four rows, four distinct defects. A loader that returned at the first one
    would turn a single editing pass into four, and the fourth defect would be
    found twenty minutes after the first.
    """
    path = write_questions(
        f",{SHORT},Missing id?,1,An answer,lookup,true",
        f"q2,{SHORT},,1,An answer,lookup,true",
        f"q3,{SHORT},Bad type?,1,An answer,lookpu,true",
        f"q4,{SHORT},Bad flag?,1,An answer,lookup,yes",
    )

    result = load_questions(path, documents_dir=corpus)

    assert not result.ok
    assert len(result.problems) == 4
    assert [p.row for p in result.problems] == [2, 3, 4, 5]
    assert result.questions == []


def test_a_gold_page_beyond_the_document_is_refused(
    corpus: pathlib.Path, write_questions
) -> None:
    """**The check nothing else can make.**

    The row is well-formed, the type is valid, the document exists — and no
    retriever could ever satisfy it, so it would read as an unexplained zero
    in the baseline rather than as a typo.
    """
    path = write_questions(
        f"q1,{SHORT},Beyond the end?,{SHORT_PAGES + 1},An answer,lookup,true",
        f"q2,{LONG},At the end?,{LONG_PAGES},An answer,lookup,true",
    )

    result = load_questions(path, documents_dir=corpus)

    assert [p.id for p in result.problems] == ["q1"]
    assert "beyond" in result.problems[0].message
    assert [q.id for q in result.questions] == ["q2"]


@pytest.mark.parametrize("page", ["0", "-1"])
def test_a_page_that_is_not_one_indexed_is_refused(
    corpus: pathlib.Path, write_questions, page: str
) -> None:
    """`Chunk.page` counts from 1, as a human reads a document."""
    path = write_questions(f"q1,{SHORT},Page zero?,{page},An answer,lookup,true")

    result = load_questions(path, documents_dir=corpus)

    assert not result.ok
    assert "1-indexed" in result.problems[0].message


def test_a_non_numeric_gold_page_is_refused(
    corpus: pathlib.Path, write_questions
) -> None:
    path = write_questions(f"q1,{SHORT},Which page?,two,An answer,lookup,true")

    result = load_questions(path, documents_dir=corpus)

    assert not result.ok
    assert "not a number" in result.problems[0].message


def test_one_typo_produces_one_message(
    corpus: pathlib.Path, write_questions
) -> None:
    """A page beyond the document must not also be reported as "no gold_pages".

    It leaves `gold_pages` empty, so the answerability check would fire as
    well — two messages for one defect, which would make a four-mistake file
    look like eight and bury the half that are real causes.
    """
    path = write_questions(
        f"q1,{SHORT},Beyond the end?,{SHORT_PAGES + 9},An answer,lookup,true"
    )

    result = load_questions(path, documents_dir=corpus)

    assert len(result.problems) == 1
    assert "beyond" in result.problems[0].message


def test_separators_with_no_pages_between_them_are_still_no_gold_pages(
    corpus: pathlib.Path, write_questions
) -> None:
    """The edge the fix above must not open.

    `gold_pages=";"` records no page-level complaint and yields an empty set,
    so a check written as "complain only if no pages were *given*" would let an
    answerable question through with nothing to match against — and it would
    score a permanent, unexplained zero.
    """
    path = write_questions(f"q1,{SHORT},Empty separators?,;,An answer,lookup,true")

    result = load_questions(path, documents_dir=corpus)

    assert not result.ok
    assert "no gold_pages" in result.problems[0].message


def test_a_duplicate_id_is_refused_and_names_the_first_use(
    corpus: pathlib.Path, write_questions
) -> None:
    """Ids are how two baselines are compared question by question.

    Two rows sharing one does not make the file untidy; it makes a baseline
    uncomparable, which is worse and much harder to notice later.
    """
    path = write_questions(
        f"q1,{SHORT},First?,1,An answer,lookup,true",
        f"q1,{SHORT},Second?,2,An answer,lookup,true",
    )

    result = load_questions(path, documents_dir=corpus)

    assert len(result.problems) == 1
    assert "duplicate id" in result.problems[0].message
    assert "line 2" in result.problems[0].message


def test_an_unknown_document_is_refused(
    corpus: pathlib.Path, write_questions
) -> None:
    path = write_questions("q1,nope.pdf,Where?,1,An answer,lookup,true")

    result = load_questions(path, documents_dir=corpus)

    assert not result.ok
    assert "unknown document" in result.problems[0].message


@pytest.mark.parametrize(
    ("row", "fragment"),
    [
        (f"q1,{SHORT},Answerable?,,An answer,lookup,true", "no gold_pages"),
        (f"q1,{SHORT},Answerable?,1,,lookup,true", "no gold_answer"),
        (f"q1,{SHORT},Unanswerable?,1,,near_miss,false", "with gold_pages"),
        (f"q1,{SHORT},Unanswerable?,,An answer,near_miss,false", "with a gold_answer"),
    ],
)
def test_answerability_must_agree_with_the_gold_columns(
    corpus: pathlib.Path, write_questions, row: str, fragment: str
) -> None:
    """Both directions. An answerable question needs a gold page and an answer;
    an unanswerable one must have neither, or it is not the question it claims
    to be."""
    result = load_questions(write_questions(row), documents_dir=corpus)

    assert not result.ok
    assert any(fragment in p.message for p in result.problems)


@pytest.mark.parametrize(
    "row",
    [
        f"q1,{SHORT},Mismatch?,1,An answer,lookup,false",
        f"q1,{SHORT},Mismatch?,,,near_miss,true",
    ],
)
def test_type_and_answerable_must_agree(
    corpus: pathlib.Path, write_questions, row: str
) -> None:
    result = load_questions(write_questions(row), documents_dir=corpus)

    assert not result.ok
    assert any("disagree" in p.message for p in result.problems)


def test_out_of_domain_must_not_name_a_document(
    corpus: pathlib.Path, write_questions
) -> None:
    """No document is relevant to it by definition.

    A `near_miss` *does* name one — it names the document the question is near,
    which is what makes the miss hard.
    """
    named = load_questions(
        write_questions(f"q1,{SHORT},Unrelated?,,,out_of_domain,false"),
        documents_dir=corpus,
    )
    assert not named.ok
    assert "name no document" in named.problems[0].message

    unnamed = load_questions(
        write_questions("q1,,Unrelated?,,,out_of_domain,false"), documents_dir=corpus
    )
    assert unnamed.ok


def test_a_missing_question_file_raises_rather_than_reporting(
    corpus: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Structural, not a row-level problem.

    Nothing can be interpreted, so there is no list of problems to collect and
    the message points at the worksheet instead.
    """
    with pytest.raises(FileNotFoundError, match="README"):
        load_questions(tmp_path / "absent.csv", documents_dir=corpus)


def test_a_wrong_header_raises_and_shows_both(
    corpus: pathlib.Path, write_questions
) -> None:
    """Also structural: fifty identical complaints would not help anyone."""
    path = write_questions(
        "q1,short.pdf,Where?,1,An answer,lookup,true",
        header="id,doc,question,pages,answer,type,answerable",
    )

    with pytest.raises(ValueError, match="Unexpected header"):
        load_questions(path, documents_dir=corpus)
