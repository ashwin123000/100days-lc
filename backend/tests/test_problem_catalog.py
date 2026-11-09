import pytest

from backend.app.problem_catalog import (
    ProblemCatalog,
    ProblemLookupError,
    extract_problem_slug,
)


RECORDS = [
    {
        "questionFrontendId": "1",
        "questionTitle": "Two Sum",
        "TitleSlug": "two-sum",
        "content": "<p>Return the indices of two numbers.</p>",
        "difficulty": "Easy",
        "acRate": 49.3,
        "topicTags": [{"name": "Array", "slug": "array"}],
        "codeDefinition": '[{"text":"Python3","defaultCode":"class Solution: pass"}]',
        "sampleTestCase": "[2,7,11,15]",
        "metaData": '{"constraints":["2 <= nums.length <= 10^4"]}',
        "similarQuestions": "[]",
    },
    {
        "questionFrontendId": "2",
        "questionTitle": "Add Two Numbers",
        "TitleSlug": "add-two-numbers",
        "content": "<p>Add two linked-list numbers.</p>",
        "difficulty": "Medium",
    },
]


def create_catalog(semantic_search=None):
    return ProblemCatalog(
        dataset_name="test/dataset",
        embedding_model="test/model",
        records_loader=lambda: RECORDS,
        semantic_search=semantic_search,
        min_score=0.7,
        min_margin=0.05,
    )


def test_extract_problem_slug_accepts_leetcode_problem_url():
    assert extract_problem_slug("https://leetcode.com/problems/two-sum/") == "two-sum"


@pytest.mark.parametrize(
    "url",
    [
        "http://leetcode.com/problems/two-sum/",
        "https://example.com/problems/two-sum/",
        "https://leetcode.com/contest/",
    ],
)
def test_extract_problem_slug_rejects_non_problem_urls(url):
    with pytest.raises(ProblemLookupError):
        extract_problem_slug(url)


def test_lookup_uses_exact_slug_and_returns_dataset_fields():
    problem = create_catalog().lookup("Two Sum", "https://leetcode.com/problems/two-sum/")

    assert problem["problem_id"] == "1"
    assert problem["title"] == "Two Sum"
    assert problem["description"] == "<p>Return the indices of two numbers.</p>"
    assert problem["topic_tags"] == [{"name": "Array", "slug": "array"}]
    assert problem["starter_code"] == [{"language": "Python3", "code": "class Solution: pass"}]


def test_normalizes_python_literal_dataset_tag_lists():
    catalog = ProblemCatalog(
        dataset_name="test/dataset",
        embedding_model="test/model",
        records_loader=lambda: [{
            "questionFrontendId": "1",
            "questionTitle": "Two Sum",
            "TitleSlug": "two-sum",
            "topicTags": "['Array', 'Hash Table']",
        }],
    )

    assert catalog.records[0]["topic_tags"] == ["Array", "Hash Table"]


def test_lookup_rejects_title_that_does_not_match_exact_slug():
    with pytest.raises(ProblemLookupError, match="matches"):
        create_catalog().lookup("Add Two Numbers", "https://leetcode.com/problems/two-sum/")


def test_lookup_rejects_title_and_url_slug_mismatch():
    with pytest.raises(ProblemLookupError) as error:
        create_catalog().lookup(
            "Two Sum",
            "https://leetcode.com/problems/two-sum-typo/",
        )
    assert error.value.code == "slug_mismatch"


def test_semantic_fallback_requires_a_unique_verified_match():
    catalog = create_catalog(
        semantic_search=lambda _query, records: [(records[0], 0.91), (records[1], 0.73)]
    )

    result = catalog.lookup("Two Sums", "https://leetcode.com/problems/two-sum-ish/")
    assert result["problem_id"] == "1"


def test_semantic_fallback_rejects_close_candidates():
    catalog = create_catalog(
        semantic_search=lambda _query, records: [(records[0], 0.91), (records[1], 0.89)]
    )

    with pytest.raises(ProblemLookupError) as error:
        catalog.lookup("Two Sums", "https://leetcode.com/problems/two-sum-ish/")
    assert error.value.code == "ambiguous_semantic_match"


def test_missing_problem_never_returns_an_unrelated_record():
    catalog = create_catalog(
        semantic_search=lambda _query, records: [(records[0], 0.99)]
    )

    with pytest.raises(ProblemLookupError) as error:
        catalog.lookup("Completely Different Problem", "https://leetcode.com/problems/unrelated/")
    assert error.value.code == "problem_not_found"
