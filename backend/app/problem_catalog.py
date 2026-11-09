import ast
import json
import re
import unicodedata
from difflib import SequenceMatcher
from functools import cached_property
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlparse


class ProblemLookupError(Exception):
    def __init__(self, message: str, code: str = "problem_not_found", status_code: int = 404):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text))


def extract_problem_slug(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.hostname not in {"leetcode.com", "www.leetcode.com"}:
        raise ProblemLookupError(
            "Enter a valid HTTPS LeetCode problem URL.",
            code="invalid_leetcode_url",
            status_code=422,
        )
    match = re.fullmatch(r"/problems/([a-z0-9-]+)/?", unquote(parsed.path), re.IGNORECASE)
    if not match:
        raise ProblemLookupError(
            "The URL must point to a LeetCode problem, such as https://leetcode.com/problems/two-sum/.",
            code="invalid_leetcode_url",
            status_code=422,
        )
    return match.group(1).lower()


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "item"):
        try:
            return _decode(value.item())
        except (ValueError, TypeError):
            pass
    if isinstance(value, dict):
        return {str(key): _decode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_decode(item) for item in value]
    return value


def _parse_json(value: Any) -> Any:
    decoded = _decode(value)
    if not isinstance(decoded, str):
        return decoded
    try:
        return json.loads(decoded)
    except (json.JSONDecodeError, TypeError):
        try:
            return ast.literal_eval(decoded)
        except (ValueError, SyntaxError):
            return decoded


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _as_list(value: Any) -> list[Any]:
    parsed = _parse_json(value)
    if parsed is None or parsed == "":
        return []
    return parsed if isinstance(parsed, list) else [parsed]


def _as_tags(value: Any) -> list[dict[str, Any] | str]:
    tags = _as_list(value)
    return [
        tag if isinstance(tag, (dict, str)) else _as_text(tag)
        for tag in tags
    ]


def _get(row: dict[str, Any], *names: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered:
            return _decode(lowered[name.lower()])
    return None


def _extract_sections(description: str) -> tuple[list[str], list[str]]:
    try:
        from html.parser import HTMLParser
    except ImportError:
        return [], []

    class SectionParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.heading_depth = 0
            self.heading: list[str] = []
            self.current_section = ""
            self.sections: dict[str, list[str]] = {}

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag.lower() in {"h1", "h2", "h3", "h4"}:
                self.heading_depth += 1
                self.heading = []

        def handle_endtag(self, tag: str) -> None:
            if tag.lower() in {"h1", "h2", "h3", "h4"} and self.heading_depth:
                heading = " ".join("".join(self.heading).split()).lower()
                self.current_section = heading.rstrip(":")
                self.sections.setdefault(self.current_section, [])
                self.heading_depth -= 1

        def handle_data(self, data: str) -> None:
            if self.heading_depth:
                self.heading.append(data)
            elif self.current_section and data.strip():
                self.sections[self.current_section].append(data.strip())

    parser = SectionParser()
    try:
        parser.feed(description)
    except Exception:
        return [], []

    examples: list[str] = []
    constraints: list[str] = []
    for heading, values in parser.sections.items():
        if heading.startswith("example"):
            examples.extend(values)
        elif heading == "constraints":
            constraints.extend(values)
    return examples, constraints


def _normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    row = _decode(row)
    problem_id = _get(row, "questionFrontendId", "problem_id", "id")
    title = _as_text(_get(row, "questionTitle", "title", "question_title")).strip()
    slug = _as_text(_get(row, "TitleSlug", "titleSlug", "slug")).strip().lower()
    description = _as_text(_get(row, "content", "description", "statement"))
    difficulty = _as_text(_get(row, "difficulty")).strip() or None

    raw_rate = _get(row, "acRate", "acceptance_rate", "acceptanceRate")
    acceptance_rate: float | None = None
    if raw_rate is not None:
        try:
            acceptance_rate = float(str(raw_rate).replace("%", "").strip())
        except (ValueError, TypeError):
            acceptance_rate = None
    total_accepted = _get(row, "totalAccepted", "total_accepted")
    total_submissions = _get(row, "totalSubmission", "total_submissions")
    if acceptance_rate is None and total_accepted is not None and total_submissions:
        try:
            acceptance_rate = float(total_accepted) / float(total_submissions) * 100
        except (ValueError, TypeError, ZeroDivisionError):
            acceptance_rate = None

    metadata = _parse_json(_get(row, "metaData", "metadata"))
    if isinstance(metadata, dict):
        input_output = {
            key: metadata[key]
            for key in ("input", "output", "params", "return", "constraints")
            if key in metadata
        }
        raw_constraints = metadata.get("constraints")
    else:
        input_output = {}
        raw_constraints = None

    examples, content_constraints = _extract_sections(description)
    constraints = raw_constraints if raw_constraints is not None else content_constraints or None
    raw_code = _parse_json(_get(row, "codeDefinition", "code_definition"))
    starter_code: list[dict[str, str]] = []
    if isinstance(raw_code, list):
        for item in raw_code:
            if not isinstance(item, dict):
                continue
            language = item.get("text") or item.get("lang") or item.get("language")
            code = item.get("defaultCode") or item.get("default_code")
            if language and code:
                starter_code.append({"language": str(language), "code": str(code)})

    return {
        "problem_id": _as_text(problem_id).strip(),
        "title": title,
        "slug": slug,
        "description": description,
        "difficulty": difficulty,
        "acceptance_rate": acceptance_rate,
        "total_accepted": total_accepted,
        "total_submissions": total_submissions,
        "topic_tags": _as_tags(_get(row, "topicTags", "topic_tags", "topics")),
        "category": _as_text(_get(row, "category")).strip() or None,
        "examples": examples,
        "constraints": constraints,
        "input_output_information": input_output,
        "starter_code": starter_code,
        "code_definition": raw_code,
        "solution": _decode(_get(row, "solution", "referenceSolution", "reference_solution")),
        "similar_questions": _as_list(_get(row, "similarQuestions", "similar_questions")),
        "sample_test_case": _as_text(_get(row, "sampleTestCase", "sample_test_case")) or None,
        "metadata": metadata,
        "environment_info": _as_text(_get(row, "envInfo", "environment_info")) or None,
        "original_url": f"https://leetcode.com/problems/{slug}/" if slug else "",
    }


class ProblemCatalog:
    def __init__(
        self,
        dataset_name: str,
        embedding_model: str,
        hf_token: str | None = None,
        records_loader: Callable[[], Iterable[dict[str, Any]]] | None = None,
        semantic_search: Callable[[str, list[dict[str, Any]]], list[tuple[dict[str, Any], float]]] | None = None,
        min_score: float = 0.72,
        min_margin: float = 0.04,
    ) -> None:
        self.dataset_name = dataset_name
        self.embedding_model = embedding_model
        self.hf_token = hf_token
        self.records_loader = records_loader
        self.semantic_search_override = semantic_search
        self.min_score = min_score
        self.min_margin = min_margin
        self._records: list[dict[str, Any]] | None = None
        self._semantic_store: Any = None

    @property
    def records(self) -> list[dict[str, Any]]:
        if self._records is None:
            if self.records_loader is not None:
                source = self.records_loader()
            else:
                try:
                    from datasets import load_dataset
                except ImportError as exc:
                    raise RuntimeError(
                        "The Hugging Face Datasets package is not installed. Install backend/requirements.txt."
                    ) from exc

                loaded = load_dataset(self.dataset_name, token=self.hf_token)
                source = (
                    (row for split in loaded.values() for row in split)
                    if hasattr(loaded, "values")
                    else iter(loaded)
                )
            normalized = [_normalize_record(dict(row)) for row in source]
            self._records = [
                record for record in normalized
                if record["problem_id"] and record["title"] and record["slug"]
            ]
            if not self._records:
                raise RuntimeError(f"No usable problem records were loaded from {self.dataset_name}.")
        return self._records

    def lookup(self, title: str, leetcode_url: str) -> dict[str, Any]:
        slug = extract_problem_slug(leetcode_url)
        requested_title = normalize_title(title)
        if not requested_title:
            raise ProblemLookupError(
                "Enter a problem title.",
                code="invalid_title",
                status_code=422,
            )

        slug_matches = [record for record in self.records if record["slug"].lower() == slug]
        if len(slug_matches) > 1:
            raise ProblemLookupError(
                "This LeetCode URL matches multiple dataset records. Please check the problem link.",
                code="ambiguous_slug",
                status_code=409,
            )
        if slug_matches:
            record = slug_matches[0]
            if normalize_title(record["title"]) != requested_title:
                raise ProblemLookupError(
                    f"The URL matches “{record['title']}”, not “{title.strip()}”. Please correct the title or URL.",
                    code="title_mismatch",
                    status_code=422,
                )
            return record

        title_matches = [
            record for record in self.records
            if normalize_title(record["title"]) == requested_title
        ]
        if len(title_matches) == 1:
            record = title_matches[0]
            if record["slug"].lower() != slug:
                raise ProblemLookupError(
                    f"The title matches “{record['title']}”, but its dataset URL uses a different slug. Please correct the LeetCode URL.",
                    code="slug_mismatch",
                    status_code=422,
                )
            return record
        if len(title_matches) > 1:
            raise ProblemLookupError(
                "This title matches multiple dataset records. Please use the exact LeetCode problem URL.",
                code="ambiguous_title",
                status_code=409,
            )

        semantic_matches = self._semantic_search(f"{title.strip()} {slug}")
        accepted = [
            (record, score)
            for record, score in semantic_matches
            if score >= self.min_score and self._verify_semantic_candidate(record, requested_title, slug)
        ]
        accepted.sort(key=lambda result: result[1], reverse=True)
        if not accepted:
            raise ProblemLookupError(
                "No matching problem was found in the dataset. Please check the problem title and LeetCode URL.",
                code="problem_not_found",
                status_code=404,
            )
        if len(accepted) > 1 and accepted[0][1] - accepted[1][1] < self.min_margin:
            raise ProblemLookupError(
                "Several dataset records are similarly relevant. Please provide the exact problem title and URL.",
                code="ambiguous_semantic_match",
                status_code=409,
            )
        return accepted[0][0]

    def get_by_id(self, problem_id: str) -> dict[str, Any]:
        matches = [record for record in self.records if record["problem_id"] == str(problem_id)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ProblemLookupError(
                "The dataset contains multiple records with this problem ID.",
                code="ambiguous_problem_id",
                status_code=409,
            )
        raise ProblemLookupError(
            f"Problem {problem_id} was not found in the dataset.",
            code="problem_not_found",
            status_code=404,
        )

    @staticmethod
    def _verify_semantic_candidate(
        record: dict[str, Any],
        requested_title: str,
        requested_slug: str,
    ) -> bool:
        if not record.get("problem_id") or not record.get("title") or not record.get("slug"):
            return False
        title_similarity = SequenceMatcher(
            None,
            requested_title,
            normalize_title(record["title"]),
        ).ratio()
        slug_similarity = SequenceMatcher(
            None,
            requested_slug,
            record["slug"].lower(),
        ).ratio()
        return title_similarity >= 0.55 or slug_similarity >= 0.72

    def _semantic_search(self, query: str) -> list[tuple[dict[str, Any], float]]:
        if self.semantic_search_override is not None:
            return self.semantic_search_override(query, self.records)

        try:
            from langchain_core.documents import Document
            from langchain_core.vectorstores import InMemoryVectorStore
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as exc:
            raise RuntimeError(
                "LangChain semantic retrieval dependencies are missing. Install backend/requirements.txt."
            ) from exc

        if self._semantic_store is None:
            model_kwargs = {"token": self.hf_token} if self.hf_token else {}
            embeddings = HuggingFaceEmbeddings(
                model_name=self.embedding_model,
                model_kwargs=model_kwargs,
            )
            documents = [
                Document(
                    page_content=f"{record['title']}. {record['slug']}. {record['description'][:2500]}",
                    metadata={"problem_id": record["problem_id"]},
                )
                for record in self.records
            ]
            self._semantic_store = InMemoryVectorStore.from_documents(documents, embeddings)

        by_id = {record["problem_id"]: record for record in self.records}
        results = self._semantic_store.similarity_search_with_score(query, k=3)
        return [
            (by_id[document.metadata["problem_id"]], float(score))
            for document, score in results
            if document.metadata.get("problem_id") in by_id
        ]
