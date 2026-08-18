#!/usr/bin/env python3
"""Bộ kiểm thử chất lượng HDS AI: chạy thuần logic hoặc gọi API thật.

Không cần PostgreSQL/Ollama cho ``--mode offline``. Chế độ ``live`` dùng đúng
API người dùng nội bộ, vì vậy nó đồng thời kiểm tra router, dữ liệu, lưu trạng
thái hội thoại, retrieval, citation và thời gian phản hồi end-to-end.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_CASES = SCRIPT_DIR / "quality_eval_cases.json"
CITATION_RE = re.compile(r"\[\s*Nguồn\s+(\d+)\s*\]", re.IGNORECASE)


class EvalConfigError(RuntimeError):
    """Cấu hình eval thiếu hoặc không hợp lệ."""


class ApiError(RuntimeError):
    """API trả lỗi hoặc nội dung không phải JSON."""


@dataclass
class CheckResult:
    case_id: str
    group: str
    passed: bool
    elapsed_ms: float = 0.0
    detail: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"\s+", " ", text).strip().lower()


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def percentile(values: Iterable[float], percent: float) -> float | None:
    """Phân vị tuyến tính, dùng được cả khi chỉ có một mẫu."""
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def load_cases(path: Path = DEFAULT_CASES) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvalConfigError(f"Không thấy file golden cases: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EvalConfigError(f"Golden cases không phải JSON hợp lệ: {exc}") from exc
    if not isinstance(data, dict) or "offline" not in data or "live" not in data:
        raise EvalConfigError("Golden cases phải có hai phần 'offline' và 'live'")
    return data


def _result(case_id: str, group: str, errors: list[str], started: float,
            metrics: dict[str, Any] | None = None) -> CheckResult:
    return CheckResult(
        case_id=case_id,
        group=group,
        passed=not errors,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        detail="; ".join(errors) if errors else "OK",
        metrics=metrics or {},
    )


def run_offline(cases: dict[str, Any]) -> list[CheckResult]:
    """Chạy golden cases không truy cập DB, model hoặc mạng."""
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))
    try:
        from app import company_context, rag
    except Exception as exc:  # pragma: no cover - phụ thuộc môi trường máy chạy
        return [CheckResult(
            "offline_import", "offline.setup", False, 0,
            f"Không import được app: {type(exc).__name__}: {exc}",
        )]

    config = cases["offline"]
    results: list[CheckResult] = []

    for case in config.get("intents", []):
        started = time.perf_counter()
        errors: list[str] = []
        try:
            actual = company_context.infer_intent(
                case["question"], history=case.get("history"), state=case.get("state"))
            if actual != case.get("expected"):
                errors.append(f"intent={actual!r}, cần {case.get('expected')!r}")
        except Exception as exc:  # noqa: BLE001 - mỗi case phải báo riêng
            errors.append(f"{type(exc).__name__}: {exc}")
        results.append(_result(case["id"], "offline.intent", errors, started))

    for case in config.get("followups", []):
        started = time.perf_counter()
        errors = []
        try:
            if "expected_intent" in case:
                actual = company_context.infer_intent(
                    case["question"], history=case.get("history"), state=case.get("state"))
                if actual != case["expected_intent"]:
                    errors.append(
                        f"intent nối tiếp={actual!r}, cần {case['expected_intent']!r}")

            rewritten = rag.resolve_search_question(
                case["question"], case.get("history"), case.get("state"))
            if case.get("rewrite_equals_question") and rewritten != case["question"]:
                errors.append(f"câu mới bị nhiễm lịch sử: {rewritten!r}")
            for expected in case.get("rewrite_contains", []):
                if expected not in rewritten:
                    errors.append(f"câu retrieval thiếu {expected!r}: {rewritten!r}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
        results.append(_result(case["id"], "offline.followup", errors, started))

    for case in config.get("citations", []):
        started = time.perf_counter()
        errors = []
        try:
            chunks = [
                {"chunk_id": n, "document_id": n, "title": f"Nguồn {n}",
                 "content": f"Nội dung kiểm thử {n}."}
                for n in range(1, int(case.get("source_count", 0)) + 1)
            ]
            output, status = rag.validate_grounding(
                case.get("text", ""), chunks, case.get("answer_mode", "grounded"),
                bool(case.get("strict", True)))
            if status != case.get("expected_status"):
                errors.append(f"status={status!r}, cần {case.get('expected_status')!r}")
            if case.get("output_equals_input") and output != case.get("text", ""):
                errors.append("nội dung structured đã bị đổi")
            for expected in case.get("output_contains", []):
                if expected not in output:
                    errors.append(f"đầu ra thiếu {expected!r}")
            for forbidden in case.get("output_excludes", []):
                if forbidden in output:
                    errors.append(f"đầu ra vẫn chứa {forbidden!r}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
        results.append(_result(case["id"], "offline.citation", errors, started))

    return results


class ApiClient:
    def __init__(self, base_url: str, token: str = "", timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.timeout = timeout

    def request(self, method: str, path: str, payload: Any = None,
                query: dict[str, Any] | None = None, authenticated: bool = True) -> Any:
        url = self.base_url + path
        if query:
            url += "?" + urlencode(query, doseq=True)
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        if authenticated:
            if not self.token:
                raise EvalConfigError("Chế độ live cần biến TOKEN hoặc --token")
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"HTTP {exc.code} {path}: {raw[:600]}") from exc
        except (URLError, TimeoutError) as exc:
            raise ApiError(f"Không gọi được {url}: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApiError(f"{path} không trả JSON: {raw[:600]}") from exc

    def login(self, email: str, password: str) -> None:
        data = self.request("POST", "/auth/login",
                            {"email": email, "password": password}, authenticated=False)
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise ApiError("/auth/login không trả access_token")
        self.token = str(token)

    def post_internal(self, question: str, conversation_id: int | None = None,
                      document_ids: list[int] | None = None) -> tuple[dict[str, Any], float]:
        payload: dict[str, Any] = {"question": question}
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id
        if document_ids is not None:
            payload["source_document_ids"] = document_ids
        started = time.perf_counter()
        data = self.request("POST", "/chat/internal", payload)
        elapsed = (time.perf_counter() - started) * 1000
        if not isinstance(data, dict):
            raise ApiError("/chat/internal không trả một JSON object")
        return data, elapsed


def _document_sources(response: dict[str, Any]) -> list[Any]:
    sources = response.get("sources") or []
    if not isinstance(sources, list):
        return [sources]
    result = []
    for source in sources:
        if not isinstance(source, dict):
            result.append(source)  # nguồn kiểu cũ (id) được coi là tài liệu
        elif source.get("kind") == "document" or source.get("document_id") is not None \
                or source.get("chunk_id") is not None:
            result.append(source)
    return result


def _api_metrics(response: dict[str, Any], wall_ms: float) -> dict[str, Any]:
    raw_timings = response.get("timings")
    timings: dict[str, Any] = raw_timings if isinstance(raw_timings, dict) else {}
    end_to_end = _as_number(response.get("end_to_end_ms"))
    if end_to_end is None:
        end_to_end = _as_number(timings.get("tong_ms"))
    return {
        "client_wall_ms": round(wall_ms, 2),
        "api_end_to_end_ms": end_to_end,
        "ai_ms": _as_number(timings.get("ai_ms")),
        "answer_mode": response.get("answer_mode"),
        "grounding_status": response.get("grounding_status"),
        "source_count": len(response.get("sources") or [])
                         if isinstance(response.get("sources") or [], list) else None,
    }


def _direct_errors(response: dict[str, Any], case: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    timings = response.get("timings")
    if not isinstance(timings, dict):
        errors.append("thiếu timings")
    elif _as_number(timings.get("ai_ms")) != 0:
        errors.append(f"direct query có ai_ms={timings.get('ai_ms')!r}, cần 0")
    if _as_number(response.get("latency_ms")) != 0:
        errors.append(f"direct query có latency_ms={response.get('latency_ms')!r}, cần 0")
    documents = _document_sources(response)
    if documents:
        errors.append(f"direct query trả {len(documents)} nguồn tài liệu")
    if response.get("answer_mode") not in case.get("expected_modes", []):
        errors.append(
            f"answer_mode={response.get('answer_mode')!r}, cần {case.get('expected_modes')}")
    if response.get("grounding_status") not in case.get("expected_grounding", []):
        errors.append(
            "grounding_status="
            f"{response.get('grounding_status')!r}, cần {case.get('expected_grounding')}")
    answer_folded = _fold(response.get("answer"))
    wanted = case.get("answer_contains_any", [])
    if wanted and not any(_fold(value) in answer_folded for value in wanted):
        errors.append(f"câu trả lời không chứa chủ đề mong đợi: {wanted}")
    wanted_locators = case.get("source_locator_contains_any", [])
    if wanted_locators:
        sources = response.get("sources") or []
        locators = [
            _fold(source.get("source_locator"))
            for source in sources if isinstance(source, dict)
            and source.get("kind") == "system"
        ] if isinstance(sources, list) else []
        if not any(_fold(wanted_locator) in locator
                   for wanted_locator in wanted_locators for locator in locators):
            errors.append(
                f"nguồn hệ thống không trỏ đúng dữ liệu chuẩn: cần {wanted_locators}, "
                f"nhận {locators}")
    if not response.get("conversation_id"):
        errors.append("thiếu conversation_id")
    return errors


def _retrieval_errors(response: dict[str, Any], case: dict[str, Any],
                      selected_ids: list[int]) -> list[str]:
    errors: list[str] = []
    if response.get("answer_mode") not in case.get("expected_modes", []):
        errors.append(
            f"answer_mode={response.get('answer_mode')!r}, cần {case.get('expected_modes')}")
    if response.get("grounding_status") not in case.get("expected_grounding", []):
        errors.append(
            "grounding_status="
            f"{response.get('grounding_status')!r}, cần {case.get('expected_grounding')}")

    sources = response.get("sources") or []
    documents = _document_sources(response)
    if not documents:
        errors.append("retrieval không trả nguồn tài liệu nào")

    selected = set(selected_ids)
    valid_citation_numbers: set[int] = set()
    leaked: list[Any] = []
    missing_ids = 0
    for index, source in enumerate(sources if isinstance(sources, list) else [], 1):
        if not isinstance(source, dict):
            missing_ids += 1
            continue
        if source in documents:
            raw_id = source.get("document_id")
            try:
                document_id = int(str(raw_id))
            except (TypeError, ValueError):
                missing_ids += 1
                continue
            if document_id not in selected:
                leaked.append(document_id)
            raw_n = source.get("n", index)
            try:
                valid_citation_numbers.add(int(raw_n))
            except (TypeError, ValueError):
                valid_citation_numbers.add(index)
    if missing_ids:
        errors.append(f"{missing_ids} nguồn thiếu document_id")
    if leaked:
        errors.append(f"lọt nguồn ngoài bộ đã chọn: {sorted(set(leaked))}")

    citations = [int(n) for n in CITATION_RE.findall(str(response.get("answer") or ""))]
    if not citations:
        errors.append("câu trả lời retrieval không có [Nguồn n]")
    invalid = sorted({n for n in citations if n not in valid_citation_numbers})
    if invalid:
        errors.append(f"citation không trỏ tới nguồn trả về: {invalid}")
    return errors


def _parse_document_ids(values: list[str] | None) -> list[int]:
    raw_values = list(values or [])
    env_value = os.getenv("QUALITY_EVAL_DOCUMENT_IDS", "")
    if env_value:
        raw_values.extend(part for part in env_value.split(",") if part.strip())
    result: list[int] = []
    for raw in raw_values:
        for part in str(raw).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                value = int(part)
            except ValueError as exc:
                raise EvalConfigError(f"document id không hợp lệ: {part!r}") from exc
            if value <= 0:
                raise EvalConfigError("document id phải là số nguyên dương")
            if value not in result:
                result.append(value)
    if len(result) > 50:
        raise EvalConfigError("API chỉ cho chọn tối đa 50 tài liệu")
    return result


def _discover_documents(client: ApiClient) -> list[dict[str, Any]]:
    data = client.request("GET", "/documents/browse", query={"limit": 300})
    if not isinstance(data, list):
        raise ApiError("/documents/browse không trả danh sách")
    return [item for item in data if isinstance(item, dict)]


def run_live(cases: dict[str, Any], client: ApiClient,
             document_ids: list[int] | None = None,
             retrieval_questions: list[str] | None = None,
             repeat: int = 1, skip_retrieval: bool = False) -> list[CheckResult]:
    """Chạy qua REST API thật và giữ mỗi lỗi trong đúng case của nó."""
    if repeat < 1:
        raise EvalConfigError("--repeat phải >= 1")
    live = cases["live"]
    results: list[CheckResult] = []

    me = client.request("GET", "/auth/me")
    if not isinstance(me, dict) or me.get("role") in {
            "client_free", "client_plus", "client_pro"}:
        raise EvalConfigError("TOKEN phải thuộc tài khoản nội bộ, không phải tài khoản khách")

    documents: list[dict[str, Any]] = []
    selected_ids = list(document_ids or [])
    if not skip_retrieval:
        documents = _discover_documents(client)
        accessible = [doc for doc in documents if doc.get("can_open")]
        if not selected_ids and accessible:
            selected_ids = [int(accessible[0]["id"])]

    for round_no in range(1, repeat + 1):
        suffix = f"#r{round_no}" if repeat > 1 else ""
        for case in live.get("direct", []):
            started = time.perf_counter()
            errors: list[str] = []
            response: dict[str, Any] = {}
            wall_ms = 0.0
            try:
                response, wall_ms = client.post_internal(case["question"])
                errors.extend(_direct_errors(response, case))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")
            results.append(CheckResult(
                case["id"] + suffix, "live.direct", not errors,
                round(wall_ms or (time.perf_counter() - started) * 1000, 2),
                "; ".join(errors) if errors else "OK",
                _api_metrics(response, wall_ms) if response else {},
            ))

        followup = live.get("followup") or {}
        if followup:
            conversation_id = None
            for step, question in (
                    ("setup", followup["first_question"]),
                    ("detail", followup["followup_question"])):
                started = time.perf_counter()
                errors = []
                response = {}
                wall_ms = 0.0
                try:
                    if step == "detail" and conversation_id is None:
                        raise ApiError("không có conversation_id từ lượt setup")
                    response, wall_ms = client.post_internal(question, conversation_id)
                    errors.extend(_direct_errors(response, followup))
                    conversation_id = response.get("conversation_id") or conversation_id
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{type(exc).__name__}: {exc}")
                results.append(CheckResult(
                    f"{followup['id']}_{step}{suffix}", "live.followup", not errors,
                    round(wall_ms or (time.perf_counter() - started) * 1000, 2),
                    "; ".join(errors) if errors else "OK",
                    _api_metrics(response, wall_ms) if response else {},
                ))

        if skip_retrieval:
            continue
        retrieval = live.get("retrieval") or {}
        questions = list(retrieval_questions or [])
        if not questions:
            title = "tài liệu đã chọn"
            by_id = {int(doc["id"]): doc for doc in documents if doc.get("id") is not None}
            if selected_ids and selected_ids[0] in by_id:
                title = str(by_id[selected_ids[0]].get("title") or title)
            questions = [retrieval.get("question_template", "Tóm tắt tài liệu đã chọn.").format(
                title=title.replace("{", "(").replace("}", ")"))]
        if not selected_ids:
            results.append(CheckResult(
                retrieval.get("id", "live_selected_source_retrieval") + suffix,
                "live.retrieval", False, 0,
                "Không có tài liệu can_open; hãy ingest/duyệt tài liệu hoặc truyền --document-id",
            ))
            continue
        for question_index, question in enumerate(questions, 1):
            case_suffix = f"_q{question_index}" if len(questions) > 1 else ""
            started = time.perf_counter()
            errors = []
            response = {}
            wall_ms = 0.0
            try:
                response, wall_ms = client.post_internal(
                    question, document_ids=selected_ids)
                errors.extend(_retrieval_errors(response, retrieval, selected_ids))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")
            metrics = _api_metrics(response, wall_ms) if response else {}
            metrics["selected_document_ids"] = selected_ids
            results.append(CheckResult(
                retrieval.get("id", "live_selected_source_retrieval")
                + case_suffix + suffix,
                "live.retrieval", not errors,
                round(wall_ms or (time.perf_counter() - started) * 1000, 2),
                "; ".join(errors) if errors else "OK",
                metrics,
            ))

    return results


def summarize(results: list[CheckResult]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for result in results:
        item = groups.setdefault(result.group, {"passed": 0, "total": 0, "pass_rate": 0.0})
        item["total"] += 1
        item["passed"] += int(result.passed)
    for item in groups.values():
        item["pass_rate"] = round(100.0 * item["passed"] / item["total"], 2)

    live = [result for result in results if result.group.startswith("live.")]
    wall_values: list[float] = []
    api_values: list[float] = []
    for result in live:
        wall_value = _as_number(result.metrics.get("client_wall_ms"))
        api_value = _as_number(result.metrics.get("api_end_to_end_ms"))
        if wall_value is not None:
            wall_values.append(wall_value)
        if api_value is not None:
            api_values.append(api_value)
    total = len(results)
    passed = sum(result.passed for result in results)
    return {
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "pass_rate": round(100.0 * passed / total, 2) if total else 0.0,
        "groups": groups,
        "latency_ms": {
            "client_wall": {
                "samples": len(wall_values),
                "p50": percentile(wall_values, 50),
                "p95": percentile(wall_values, 95),
            },
            "api_end_to_end": {
                "samples": len(api_values),
                "p50": percentile(api_values, 50),
                "p95": percentile(api_values, 95),
            },
        },
    }


def _ms(value: Any) -> str:
    number = _as_number(value)
    return "n/a" if number is None else f"{number:.1f}ms"


def print_report(results: list[CheckResult], summary: dict[str, Any]) -> None:
    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        print(f"[{marker}] {result.group}/{result.case_id} "
              f"({_ms(result.elapsed_ms)}): {result.detail}")
    print()
    print(f"TỔNG: {summary['passed']}/{summary['total']} đạt "
          f"({summary['pass_rate']:.2f}%), {summary['failed']} lỗi")
    for name, item in summary["groups"].items():
        print(f"  {name}: {item['passed']}/{item['total']} ({item['pass_rate']:.2f}%)")
    latency = summary["latency_ms"]
    if latency["client_wall"]["samples"]:
        print("  Live client wall: "
              f"p50={_ms(latency['client_wall']['p50'])}, "
              f"p95={_ms(latency['client_wall']['p95'])}, "
              f"n={latency['client_wall']['samples']}")
    if latency["api_end_to_end"]["samples"]:
        print("  Live API end-to-end: "
              f"p50={_ms(latency['api_end_to_end']['p50'])}, "
              f"p95={_ms(latency['api_end_to_end']['p95'])}, "
              f"n={latency['api_end_to_end']['samples']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Golden/live quality eval cho HDS AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Ví dụ trên máy chủ (đứng tại ~/hds-ai):
  python scripts/quality_eval.py --mode offline

  export TOKEN="$(curl -fsS http://127.0.0.1:8000/auth/login \\
    -H 'Content-Type: application/json' \\
    -d '{\"email\":\"admin@hdslaw.vn\",\"password\":\"<MAT_KHAU>\"}' \\
    | python -c 'import json,sys; print(json.load(sys.stdin)[\"access_token\"])')"
  python scripts/quality_eval.py --mode live --base-url http://127.0.0.1:8000

  # Ép retrieval chỉ được dùng tài liệu 123 và đo nhiều mẫu hơn:
  python scripts/quality_eval.py --mode live --document-id 123 --repeat 3 \\
    --json-out quality-eval-report.json

Biến môi trường: TOKEN, QUALITY_EVAL_BASE_URL, QUALITY_EVAL_DOCUMENT_IDS,
QUALITY_EVAL_EMAIL, QUALITY_EVAL_PASSWORD, QUALITY_EVAL_RETRIEVAL_QUESTION.
""",
    )
    parser.add_argument("--mode", choices=("offline", "live", "all"), default="offline")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--base-url", default=os.getenv(
        "QUALITY_EVAL_BASE_URL", os.getenv("BASE_URL", "http://127.0.0.1:8000")))
    parser.add_argument("--token", default=os.getenv("TOKEN", ""),
                        help="JWT nội bộ; mặc định đọc biến TOKEN")
    parser.add_argument("--email", default=os.getenv("QUALITY_EVAL_EMAIL", ""),
                        help="tùy chọn: đăng nhập lấy token thay cho --token")
    parser.add_argument("--password", default=os.getenv("QUALITY_EVAL_PASSWORD", ""),
                        help="tùy chọn: mật khẩu đi cùng --email")
    parser.add_argument("--document-id", action="append", default=[],
                        help="ID nguồn cho case retrieval; lặp flag hoặc dùng 1,2,3")
    parser.add_argument("--retrieval-question", action="append", default=[],
                        help="câu retrieval riêng phù hợp tài liệu đã chọn; có thể lặp")
    parser.add_argument("--skip-retrieval", action="store_true",
                        help="chỉ kiểm direct/follow-up trong live mode")
    parser.add_argument("--repeat", type=int, default=1,
                        help="số lượt chạy live suite để đo p50/p95 (mặc định 1)")
    parser.add_argument("--timeout", type=float, default=180.0,
                        help="timeout mỗi HTTP request, giây (mặc định 180)")
    parser.add_argument("--json-out", type=Path,
                        help="ghi báo cáo máy đọc được; không chứa token/mật khẩu")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cases = load_cases(args.cases)
        results: list[CheckResult] = []
        if args.mode in {"offline", "all"}:
            results.extend(run_offline(cases))
        if args.mode in {"live", "all"}:
            client = ApiClient(args.base_url, args.token, args.timeout)
            if not client.token:
                if not args.email or not args.password:
                    raise EvalConfigError(
                        "Live mode cần TOKEN/--token, hoặc cả --email và --password")
                client.login(args.email, args.password)
            questions = list(args.retrieval_question)
            env_question = os.getenv("QUALITY_EVAL_RETRIEVAL_QUESTION", "").strip()
            if env_question:
                questions.append(env_question)
            results.extend(run_live(
                cases, client, document_ids=_parse_document_ids(args.document_id),
                retrieval_questions=questions, repeat=args.repeat,
                skip_retrieval=args.skip_retrieval,
            ))
        report_summary = summarize(results)
        print_report(results, report_summary)
        if args.json_out:
            report = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "mode": args.mode,
                "base_url": args.base_url if args.mode in {"live", "all"} else None,
                "cases_file": str(args.cases),
                "summary": report_summary,
                "results": [asdict(result) for result in results],
            }
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"Đã ghi JSON: {args.json_out}")
        return 0 if report_summary["failed"] == 0 else 1
    except (EvalConfigError, ApiError) as exc:
        print(f"LỖI CẤU HÌNH: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Đã dừng theo yêu cầu.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
