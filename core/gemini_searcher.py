"""Gemini API로 사건 관련 정보 검색 및 분석."""

import json
import logging
from typing import Optional

import google.generativeai as genai
from dotenv import load_dotenv
import os

load_dotenv()

logger = logging.getLogger(__name__)


class GeminiSearcher:
    """Gemini로 필요한 정보원 판단 및 검색."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY 환경변수 필수")
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash")

    def search_and_analyze(self, event_text: str) -> dict:
        """
        사건 텍스트를 받아:
        1. 필요한 정보원 판단
        2. 관련 정보 검색
        3. 종합 분석
        """
        try:
            # 1단계: Gemini가 필요한 정보원과 검색어 판단
            sources_prompt = f"""
당신은 투자 분석가입니다. 다음 사건에 대해 필요한 정보원들을 파악하세요.

사건: {event_text}

JSON 형식으로 다음을 반환하세요:
{{
  "event_summary": "사건 요약",
  "key_industries": ["산업1", "산업2"],
  "key_companies": ["기업1", "기업2"],
  "search_queries": ["검색어1", "검색어2", "검색어3"],
  "analysis_focus": "분석 포인트"
}}

JSON만 반환하세요.
"""
            response = self.model.generate_content(sources_prompt)
            sources_info = json.loads(response.text)
            logger.info(f"Gemini 정보원 판단: {sources_info}")

            # 2단계: 각 검색어에 대해 정보 수집
            search_results = {}
            for query in sources_info.get("search_queries", [])[:3]:  # 최대 3개만
                search_prompt = f"""
다음 주제에 대해 최근 정보를 정리하세요: {query}

관련된 주요 뉴스, 공시, 분석을 200자 이내로 간단히 요약하세요.
"""
                search_response = self.model.generate_content(search_prompt)
                search_results[query] = search_response.text
                logger.info(f"검색 완료: {query}")

            # 3단계: 모든 정보를 종합해 최종 분석
            analysis_prompt = f"""
사건: {event_text}

산업: {', '.join(sources_info.get('key_industries', []))}
기업: {', '.join(sources_info.get('key_companies', []))}

수집된 정보:
{json.dumps(search_results, ensure_ascii=False, indent=2)}

이 정보들을 바탕으로:
1. 사건의 영향도 (0~1.0)
2. 영향받을 산업 (1~3개)
3. 영향받을 기업 (1~3개)
4. 투자 관점 (긍정/부정/중립)

JSON 형식으로 답변하세요:
{{
  "impact_score": 0.8,
  "affected_industries": ["산업명"],
  "affected_companies": ["기업명"],
  "outlook": "긍정/부정/중립",
  "reasoning": "분석 근거"
}}

JSON만 반환하세요.
"""
            analysis_response = self.model.generate_content(analysis_prompt)
            analysis = json.loads(analysis_response.text)
            logger.info(f"최종 분석: {analysis}")

            return {
                "sources_info": sources_info,
                "search_results": search_results,
                "analysis": analysis,
            }

        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패: {e}")
            return {
                "sources_info": {},
                "search_results": {},
                "analysis": {"impact_score": 0.0, "affected_industries": [], "affected_companies": []},
            }
        except Exception as e:
            logger.error(f"Gemini 검색 실패: {e}")
            raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    searcher = GeminiSearcher()
    result = searcher.search_and_analyze("미국 금리 인상 0.5%")
    print(json.dumps(result, ensure_ascii=False, indent=2))
