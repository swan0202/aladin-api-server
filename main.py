from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

app = FastAPI()

origins = [
    "https://typerecord.web.app",
    "http://localhost:3000",
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TTB_KEY = "ttbwldusdydy1845001"

ALADIN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.aladin.co.kr/home/welcome.aspx",
}


def format_url(src: str | None) -> str | None:
    """알라딘 이미지 주소를 브라우저에서 바로 열 수 있는 https 절대경로로 변환."""
    if not src:
        return None

    src = src.strip().strip('"').strip("'")

    if src.startswith("//"):
        return "https:" + src
    if src.startswith("http://"):
        return src.replace("http://", "https://", 1)
    if src.startswith("https://"):
        return src
    if src.startswith("/"):
        # /product/... 로 오는 경우와 /shop/... 로 오는 경우 모두 처리
        if src.startswith("/product/"):
            return "https://image.aladin.co.kr" + src
        return urljoin("https://www.aladin.co.kr", src)

    return src


def improve_cover_url(src: str | None) -> str | None:
    """검색 API의 작은 표지를 가능하면 큰 표지 주소로 보정."""
    if not src:
        return None
    src = format_url(src)
    return (
        src.replace("coversum", "cover500")
        .replace("cover200", "cover500")
        .replace("/cover/", "/cover500/")
    )


def first_img_from_selector(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    """c_front/c_back/c_left 영역에서 가장 먼저 발견되는 이미지 주소 반환."""
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue

        # 선택자가 div일 수도 있고 img일 수도 있으므로 둘 다 처리
        candidates = []
        if node.name == "img":
            candidates.append(node)
        candidates.extend(node.select("img"))

        for img in candidates:
            for attr in ("src", "data-src", "data-original", "data-lazy"):
                src = img.get(attr)
                if src:
                    return format_url(src)

        # background-image 형태로 들어가는 경우
        style = node.get("style", "")
        bg_match = re.search(r"url\((['\"]?)(.*?)\1\)", style, re.I)
        if bg_match:
            return format_url(bg_match.group(2))

    return None


def collect_product_image_urls(html: str) -> list[str]:
    """HTML/스크립트 안에 숨어 있는 알라딘 product 이미지 주소를 수집."""
    urls = re.findall(
        r"(?:https?:)?//image\.aladin\.co\.kr/product/[^\"'\s<>\\)]+?\.(?:jpg|jpeg|png|webp)",
        html,
        re.I,
    )
    # HTML 엔티티/이스케이프 간단 정리
    cleaned = []
    for url in urls:
        url = url.replace("\\/", "/").replace("&amp;", "&")
        formatted = format_url(url)
        if formatted and formatted not in cleaned:
            cleaned.append(formatted)
    return cleaned


@app.get("/api/search")
def search_books(query: str):
    url = "https://www.aladin.co.kr/ttb/api/ItemSearch.aspx"
    params = {
        "ttbkey": TTB_KEY,
        "Query": query,
        "QueryType": "Keyword",
        "MaxResults": 10,
        "start": 1,
        "SearchTarget": "Book",
        "output": "js",
        "Version": "20131101",
        "Cover": "Big",
    }

    response = requests.get(url, params=params, headers=ALADIN_HEADERS, timeout=10)
    response.raise_for_status()
    data = response.json()

    if "item" in data:
        for book in data["item"]:
            book["cover"] = improve_cover_url(book.get("cover"))
            # 프론트에서 상세페이지 크롤링용으로 반드시 itemId를 쓰게 하기 위한 안전 필드
            book["aladinItemId"] = book.get("itemId")
            book["detailUrl"] = (
                f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={book.get('itemId')}"
                if book.get("itemId")
                else book.get("link")
            )

    return data


@app.get("/api/get-book-images")
def get_book_images(item_id: str):
    """
    알라딘 상세페이지에서 3면 이미지를 추출.
    - c_front: 앞표지
    - c_back: 뒷표지
    - c_left: 책등
    """
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id is required")

    detail_url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={item_id}"

    try:
        response = requests.get(detail_url, headers=ALADIN_HEADERS, timeout=12)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch Aladin page: {exc}") from exc

    response.encoding = response.apparent_encoding or "utf-8"
    html = response.text
    soup = BeautifulSoup(html, "html.parser")

    images = {
        "front": None,
        "spine": None,
        "back": None,
        "detailUrl": detail_url,
    }

    # 1순위: 사용자가 F12에서 확인한 클래스명 기준으로 직접 추출
    images["front"] = first_img_from_selector(
        soup,
        [
            ".c_front img",
            "img.c_front",
            "div.c_front img",
            "[class*='c_front'] img",
        ],
    )
    images["back"] = first_img_from_selector(
        soup,
        [
            ".c_back img",
            "img.c_back",
            "div.c_back img",
            "[class*='c_back'] img",
        ],
    )
    images["spine"] = first_img_from_selector(
        soup,
        [
            ".c_left img",
            "img.c_left",
            "div.c_left img",
            "[class*='c_left'] img",
        ],
    )

    # 2순위: HTML/스크립트 전체에서 product 이미지 주소 찾기
    all_urls = collect_product_image_urls(html)

    for src in all_urls:
        low = src.lower()

        if not images["back"] and ("/letslook/" in low or re.search(r"_(b|bl|wbl)\.(jpg|jpeg|png|webp)$", low)):
            images["back"] = src

        if not images["spine"] and ("/spineflip/" in low or re.search(r"_(d|s|sl)\.(jpg|jpeg|png|webp)$", low)):
            images["spine"] = src

        if not images["front"] and (
            "/cover500/" in low
            or "/cover/" in low
            or re.search(r"_(f|wfl|1|2)\.(jpg|jpeg|png|webp)$", low)
        ):
            images["front"] = improve_cover_url(src)

    # 3순위: og:image 메타태그
    if not images["front"]:
        og = soup.select_one("meta[property='og:image'], meta[name='og:image']")
        if og and og.get("content"):
            images["front"] = improve_cover_url(og.get("content"))

    # 주소 최종 정리
    images["front"] = improve_cover_url(images["front"])
    images["spine"] = format_url(images["spine"])
    images["back"] = format_url(images["back"])

    return images
