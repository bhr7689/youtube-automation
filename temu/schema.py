"""테무 한국 셀러 제품 등록 스키마.

가이드 1~5단계의 필드를 dataclass 로 모델링.
한 곳에서 스키마를 정의하고, generator/excel/uploader 가 공유한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# 가이드의 제목 권장 템플릿 5단 구조
TITLE_PARTS = ("brand", "details", "applicable", "product_type", "features")

# 상품 세금 코드
ITC_OPTIONS = [
    ("Gen Standard", "과세 상품 (대부분의 일반 상품)"),
    ("Gen Exempt", "영세율·면세 상품"),
]

# 카테고리 권장값 (가이드는 셀러센터 트리를 따르므로, 여기서는 흔한 1depth 만 제공)
CATEGORY_PRESETS = [
    "여성 패션", "남성 패션", "신발", "가방·잡화", "주얼리·시계",
    "뷰티·퍼스널케어", "헬스·웰니스",
    "가전·전자", "휴대폰·액세서리", "컴퓨터·태블릿",
    "홈·키친", "가구·인테리어", "공구·자동차",
    "유아·아동·완구", "반려동물",
    "스포츠·아웃도어", "취미·공예",
    "식품·음료",  # 한국은 위생 인증 필요 — 가이드 5단계 참조
    "기타",
]


@dataclass
class TitleParts:
    """가이드 제목 권장 템플릿: [브랜드]+[세부정보]+[적용범위]+[제품유형]+[주요특징]"""
    brand: str = ""        # 예: ABC
    details: str = ""      # 예: 듀얼 존 와인 쿨러 및 음료 냉장고
    applicable: str = ""   # 예: 독립형 또는 카운터탑 냉장고
    product_type: str = "" # 예: 78캔 및 20병 용량, 24인치
    features: str = ""     # 예: 스테인리스 스틸

    def joined(self, sep: str = " + ") -> str:
        parts = [getattr(self, k).strip() for k in TITLE_PARTS]
        return sep.join(p for p in parts if p)

    def flat(self) -> str:
        """제목용 자연스러운 한 줄 (공백 구분, 500자 이내)."""
        parts = [getattr(self, k).strip() for k in TITLE_PARTS]
        s = " ".join(p for p in parts if p)
        return s[:500]


@dataclass
class SkuRow:
    """옵션 변형 1행 (색상/사이즈/추가 옵션)."""
    color: str = ""
    size: str = ""
    sku_code: str = ""          # 셀러 자체 SKU 코드 (선택)
    qty: int = 0
    price_krw: float = 0.0      # 한국 셀러 기준 KRW
    weight_g: float = 0.0       # 그램
    length_cm: float = 0.0      # 박스 치수
    width_cm: float = 0.0
    height_cm: float = 0.0
    image_filename: str = ""    # SKU 이미지 파일명(패키지 ZIP 내 참조)


@dataclass
class AttributeRow:
    """제품 세부 정보 한 줄 (재질/스타일/관리법 등 키-값)."""
    label: str = ""
    value: str = ""


@dataclass
class ShippingInfo:
    processing_days: int = 2                  # 처리 시간(일)
    template_name: str = "기본 배송 템플릿"   # 셀러센터에서 미리 만든 템플릿명
    method: str = "표준 배송"


@dataclass
class TemuListing:
    """가이드 1~5단계 + 이미지/영상까지 한 제품의 전체 양식."""
    # 시작 단계
    category: str = ""

    # 1단계: 제품 설명
    title_parts: TitleParts = field(default_factory=TitleParts)
    title_override: str = ""                  # 직접 작성한 제목이 있으면 우선
    brand_name: str = ""                      # 브랜드명 (없으면 비워둠)
    description: str = ""                     # 상세 설명
    itc_code: str = "Gen Standard"            # ITC 선택

    # 2단계: 제품 세부 정보 (재질, 스타일, 관리)
    attributes: list[AttributeRow] = field(default_factory=list)

    # 3단계: 옵션/SKU
    option_axis_1: str = "색상"               # 1차 옵션 축
    option_axis_2: str = "사이즈"             # 2차 옵션 축 (없으면 빈 문자열)
    skus: list[SkuRow] = field(default_factory=list)
    size_chart_csv: str = ""                  # 의류용 사이즈 차트 (CSV 텍스트)

    # 이미지/영상 (실제 파일은 ZIP 패키지로 별도 보관)
    main_image_filename: str = ""             # 메인 이미지
    gallery_filenames: list[str] = field(default_factory=list)
    video_filename: str = ""                  # 동영상 1개 (가이드: 상단에 표시)

    # 4단계: 배송
    shipping: ShippingInfo = field(default_factory=ShippingInfo)

    # 5단계: 안전·규정 준수 (체크 항목 + 업로드 서류 파일명)
    compliance_notes: str = ""
    compliance_filenames: list[str] = field(default_factory=list)

    def final_title(self) -> str:
        if self.title_override.strip():
            return self.title_override.strip()[:500]
        return self.title_parts.flat()

    def to_dict(self) -> dict:
        return asdict(self)
