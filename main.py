import os
import re
import urllib.parse
from typing import Optional

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Aladin API Proxy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

TTB_KEY = os.getenv("ALADIN_TTB_KEY", "").strip()

ALADIN_API_BASE = "https://www.aladin.co.kr/ttb/api"
ALADIN_WEB_BASE = "https://www.aladin.co.kr"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.aladin.co.kr/",
}

# 💡 알라딘의 IP 차단을 우회하기 위한 프록시 터널 함수 추가
def safe_requests_get(url: str, params: dict = None, headers: dict = None, timeout=(5, 15), stream=False):
    if params:
        req_url = url + "?" + urllib.parse.urlencode(params)
    else:
        req_url = url
        
    # 프록시 우회 주소 생성
    proxy_url = "https://api.allorigins.win/raw?url=" + urllib.parse.quote(req_url)
    
    return requests.get(proxy_url, headers=headers, timeout=timeout, stream=stream)

@app.get("/")
def read_root():
    return {
        "message": "알라딘 검색 API 서버가 정상 작동 중입니다!",
        "ttbKeyConfigured": bool(TTB_KEY),
    }

@app.get("/ping")
def keep_awake():
    return {
        "status": "ok",
        "ttbKeyConfigured": bool(TTB_KEY),
    }

def require_ttb_key():
    if not TTB_KEY:
        raise HTTPException(
            status_code=500,
            detail=(
                "ALADIN_TTB_KEY 환경변수가 설정되지 않았습니다. "
                "Render 환경변수에 알라딘 TTB 키를 등록하세요."
            ),
        )

def aladin_api_get(endpoint: str, params: dict, timeout: int = 15) -> dict:
    require_ttb_key()

    url = f"{ALADIN_API_BASE}/{endpoint}"
    request_params = {
        "ttbkey": TTB_KEY,
        "output": "js",
        "Version": "20131101",
        **params,
    }

    try:
        # 💡 기존 requests.get 대신 우회 터널 사용
        response = safe_requests_get(
            url,
            params=request_params,
            headers=DEFAULT_HEADERS,
            timeout=(5, timeout),
        )
    except requests.RequestException as error:
        print(f"알라딘 API 네트워크 오류: {error}")
        raise HTTPException(
            status_code=502,
            detail={
                "message": "알라딘 API에 연결하지 못했습니다.",
                "reason": str(error),
            },
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "알라딘 API가 요청을 거부했습니다.",
                "upstreamStatus": response.status_code,
            },
        )

    try:
        return response.json()
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "알라딘 API가 JSON이 아닌 응답을 반환했습니다.",
                "upstreamStatus": response.status_code,
            },
        )

def normalize_cover_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return url
    return (
        url.replace("http://", "https://", 1)
        .replace("coversum", "cover500")
        .replace("cover200", "cover500")
        .replace("/cover/", "/cover500/")
    )

@app.get("/api/search")
def search_books(
    query: str = Query(..., min_length=1, max_length=200),
    max_results: int = Query(10, ge=1, le=50),
):
    data = aladin_api_get(
        "ItemSearch.aspx",
        {
            "Query": query.strip(),
            "QueryType": "Keyword",
            "MaxResults": max_results,
            "start": 1,
            "SearchTarget": "Book",
        },
    )
    for book in data.get("item", []):
        if book.get("cover"):
            book["cover"] = normalize_cover_url(book["cover"])
    return data

@app.get("/api/ttb/search")
def ttb_search_proxy(
    Query_param: str = Query(..., alias="Query", min_length=1, max_length=200),
):
    data = aladin_api_get(
        "ItemSearch.aspx",
        {
            "Query": Query_param.strip(),
            "QueryType": "Keyword",
            "MaxResults": 10,
            "start": 1,
            "SearchTarget": "Book",
        },
    )
    for book in data.get("item", []):
        if book.get("cover"):
            book["cover"] = normalize_cover_url(book["cover"])
    return data

def clean_text(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"\r", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    remove_words = ["접기", "펼쳐보기", "더보기", "책소개 전체", "공유하기", "보관함", "장바구니", "바로구매", "마이리스트"]
    for word in remove_words:
        value = value.replace(word, "")
    return value.strip()

def extract_text_lines_from_soup(soup: BeautifulSoup) -> list[str]:
    for tag in soup(["script", "style", "noscript", "iframe", "button"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = []
    for line in text.split("\n"):
        line = clean_text(line)
        if not line or len(line) <= 1:
            continue
        lines.append(line)
    return lines

def extract_section_by_heading(lines: list[str], start_headings: list[str], stop_headings: list[str]) -> str:
    start_index = -1
    for index, line in enumerate(lines):
        normalized = line.replace(" ", "")
        for heading in start_headings:
            normalized_heading = heading.replace(" ", "")
            if normalized == normalized_heading or (normalized_heading in normalized and len(normalized) <= 40):
                start_index = index
                break
        if start_index != -1:
            break
    if start_index == -1:
        return ""
    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        normalized = lines[index].replace(" ", "")
        for stop in stop_headings:
            normalized_stop = stop.replace(" ", "")
            if normalized == normalized_stop or (normalized_stop in normalized and len(normalized) <= 40):
                end_index = index
                break
        if end_index != len(lines):
            break
    return clean_text("\n".join(lines[start_index + 1:end_index]))

def split_phrase_list(text: str) -> list[str]:
    if not text:
        return []
    raw_parts = re.split(r"\n{2,}", text)
    phrases = []
    for part in raw_parts:
        part = clean_text(part)
        if not part:
            continue
        if len(part) > 600:
            sub_parts = [clean_text(item) for item in part.split("\n") if clean_text(item)]
            phrases.extend(sub_parts)
        else:
            phrases.append(part)
    phrases = [phrase for phrase in phrases if len(phrase) >= 10]
    result = []
    seen = set()
    for phrase in phrases:
        key = phrase[:80]
        if key in seen:
            continue
        seen.add(key)
        result.append(phrase)
    return result[:20]

def extract_by_original_boxes(soup: BeautifulSoup) -> dict:
    texts = {"story": "", "description": "", "phrases": [], "mdRecommend": ""}
    boxes = soup.select(".Ere_prod_mconts_box")
    for box in boxes:
        title_el = box.select_one(".Ere_prod_mconts_LS")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        content_el = box.select_one(".Ere_prod_mconts_R") or box
        content_soup = BeautifulSoup(str(content_el), "html.parser")
        for unwanted in content_soup(["script", "style", "noscript", "iframe", "button"]):
            unwanted.decompose()
        title_in_content = content_soup.select_one(".Ere_prod_mconts_LS")
        if title_in_content:
            title_in_content.decompose()
        text_content = clean_text(content_soup.get_text("\n"))
        html_content = content_soup.decode_contents().strip()
        if "책소개" in title and "출판사" not in title:
            texts["story"] = text_content or html_content
        elif ("출판사" in title and ("책소개" in title or "상품소개" in title)) or "출판사 제공" in title:
            texts["description"] = text_content or html_content
        elif "책속에서" in title or "밑줄" in title:
            texts["phrases"] = split_phrase_list(text_content)
        elif "편집장의 선택" in title or "편집장" in title:
            texts["mdRecommend"] = text_content or html_content
    return texts

def resolve_aladin_item_id(lookup_id: str, title: str = "", author: str = "", publisher: str = "") -> str:
    if not lookup_id:
        return ""
    raw = str(lookup_id).strip()
    
    # 💡 카카오 API에서 ISBN을 못 찾아서 가짜 UUID나 이상한 값이 넘어오면 제목+저자+출판사로 검색어를 바꿉니다.
    search_query = raw
    if not raw.isdigit() or len(raw) < 10:
        if title or author:
            search_query = f"{title} {author} {publisher}".strip()
        else:
            return raw

    try:
        search_url = f"{ALADIN_WEB_BASE}/search/wsearchresult.aspx"
        params = {"SearchTarget": "Book", "SearchWord": search_query}
        
        response = safe_requests_get(search_url, params=params, headers=DEFAULT_HEADERS, timeout=(5, 10))
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            # 💡 알라딘 검색 결과의 첫 번째 책 링크(a.bo3)에서 정확한 ItemId를 뽑아옵니다.
            first_link = soup.select_one("a.bo3")
            if first_link and first_link.get("href"):
                match = re.search(r"ItemId=(\d+)", first_link["href"], re.IGNORECASE)
                if match:
                    return str(match.group(1))
    except Exception as error:
        print(f"웹 스크래핑 기반 검색 우회 실패: {error}")

    return raw

    # 1️⃣ 먼저 원래 방식인 TTB API 호출을 시도합니다.
    try:
        data = aladin_api_get(
            "ItemLookUp.aspx",
            {
                "ItemId": digits,
                "ItemIdType": "ISBN13" if is_isbn13 else "ISBN",
            },
        )
        items = data.get("item") or []
        if items and items[0].get("itemId"):
            return str(items[0]["itemId"])
    except Exception as error:
        print(f"알라딘 API 접근 실패, 스크래핑으로 우회합니다: {error}")

    # 2️⃣ API가 막혀있다면 스크래핑 우회 로직을 실행합니다.
    try:
        search_url = f"{ALADIN_WEB_BASE}/search/wsearchresult.aspx"
        params = {
            "SearchTarget": "Book",
            "SearchWord": digits
        }
        
        response = safe_requests_get(
            search_url,
            params=params,
            headers=DEFAULT_HEADERS,
            timeout=(5, 10)
        )
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            first_book_link = soup.select_one("a.bo3")
            if first_book_link and first_book_link.get("href"):
                href = first_book_link["href"]
                match = re.search(r"ItemId=(\d+)", href, re.IGNORECASE)
                if match:
                    return str(match.group(1))
                    
    except Exception as error:
        print(f"웹 스크래핑 기반 ISBN -> ItemId 변환 실패: {error}")

    return raw

def scrape_aladin_texts(item_id: str) -> dict:
    resolved_id = resolve_aladin_item_id(item_id)
    url = f"{ALADIN_WEB_BASE}/shop/wproduct.aspx?ItemId={resolved_id}"
    texts = {"story": "", "description": "", "phrases": [], "mdRecommend": "", "sourceUrl": url}
    try:
        # 💡 기존 requests.get 대신 우회 터널 사용
        response = safe_requests_get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=(5, 15),
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        boxed_texts = extract_by_original_boxes(soup)
        for key in ["story", "description", "mdRecommend"]:
            if boxed_texts.get(key):
                texts[key] = boxed_texts[key]
        if boxed_texts.get("phrases"):
            texts["phrases"] = boxed_texts["phrases"]
        lines = extract_text_lines_from_soup(soup)
        stop_headings = ["책소개", "줄거리", "책속에서", "밑줄긋기", "밑줄 긋기", "편집장의 선택", "출판사 제공 책소개", "출판사 제공 상품소개", "출판사 리뷰", "저자소개", "저자 소개", "목차", "추천글", "기본정보", "상품정보", "회원리뷰", "마이리뷰", "리뷰", "이벤트", "관련분류"]
        if not texts["story"]:
            texts["story"] = extract_section_by_heading(lines, ["책소개", "줄거리"], stop_headings)
        if not texts["mdRecommend"]:
            texts["mdRecommend"] = extract_section_by_heading(lines, ["편집장의 선택"], stop_headings)
        if not texts["phrases"]:
            phrase_text = extract_section_by_heading(lines, ["책속에서", "밑줄긋기", "밑줄 긋기"], stop_headings)
            texts["phrases"] = split_phrase_list(phrase_text)
        if not texts["description"]:
            texts["description"] = extract_section_by_heading(lines, ["출판사 제공 상품소개", "출판사 제공 책소개"], stop_headings)
        if not texts["description"]:
            texts["description"] = extract_section_by_heading(lines, ["출판사 리뷰"], stop_headings)
    except requests.RequestException as error:
        print(f"텍스트 스크래핑 실패: {error}")
    return texts

@app.get("/api/ttb/lookup")
def ttb_lookup_proxy(
    ItemId: str = Query(..., min_length=1),
    itemIdType: str = Query("ItemId"),
    OptResult: str = Query(""),
    title: str = Query(""),
    author: str = Query(""),
    publisher: str = Query("")
):
    try:
        data = aladin_api_get("ItemLookUp.aspx", {"ItemId": ItemId, "ItemIdType": itemIdType, "OptResult": OptResult})
        items = data.get("item") or []
        if items:
            return data
    except Exception:
        pass

    resolved_id = ItemId
    # 💡 UUID거나 ISBN일 때 제목+저자+출판사로 검색 진행
    if itemIdType.upper() in ["ISBN", "ISBN13"] or not ItemId.isdigit():
        resolved_id = resolve_aladin_item_id(ItemId, title, author, publisher)
        
    scraped = scrape_aladin_texts(resolved_id)
    
    item_page = 0
    url = f"{ALADIN_WEB_BASE}/shop/wproduct.aspx?ItemId={resolved_id}"
    try:
        response = safe_requests_get(url, headers=DEFAULT_HEADERS, timeout=(5, 10))
        if response.status_code == 200:
            page_match = re.search(r"(\d+)\s*쪽", response.text)
            if page_match:
                item_page = int(page_match.group(1))
    except Exception:
        pass

    return {
        "item": [{
            "itemId": resolved_id,
            "subInfo": {
                "itemPage": item_page,
                "story": scraped.get("story", ""),
                "fulldescription": scraped.get("description", ""),
                "fulldescription2": scraped.get("description", ""),
                "mdrecommend": scraped.get("mdRecommend", ""),
                "phraseList": [{"phrase": p} for p in scraped.get("phrases", [])]
            }
        }]
    }

def check_url(url: str) -> bool:
    try:
        # 💡 우회 터널 사용
        response = safe_requests_get(
            url,
            headers=DEFAULT_HEADERS,
            stream=True,
            timeout=(3, 5),
        )
        return response.status_code == 200
    except requests.RequestException:
        return False

def normalize_aladin_image_url(src: Optional[str]) -> Optional[str]:
    if not src:
        return None
    src = src.strip().strip('"').strip("'")
    if src.startswith("//"):
        src = "https:" + src
    elif src.startswith("http://"):
        src = src.replace("http://", "https://", 1)
    if not src.startswith("https://image.aladin.co.kr/"):
        return None
    return src.replace("coversum", "cover500").replace("cover200", "cover500").replace("/cover/", "/cover500/")

def extract_image_from_node(node) -> Optional[str]:
    candidates = []
    for attr in ["src", "data-src", "data-original", "data-lazy", "data-url"]:
        candidates.append(node.get(attr))
    style = node.get("style") or ""
    candidates.extend(re.findall(r"url\(([^)]+)\)", style, re.IGNORECASE))
    for image in node.select("img"):
        for attr in ["src", "data-src", "data-original", "data-lazy", "data-url"]:
            candidates.append(image.get(attr))
        image_style = image.get("style") or ""
        candidates.extend(re.findall(r"url\(([^)]+)\)", image_style, re.IGNORECASE))
    for child in node.select("[style]"):
        child_style = child.get("style") or ""
        candidates.extend(re.findall(r"url\(([^)]+)\)", child_style, re.IGNORECASE))
    for candidate in candidates:
        normalized = normalize_aladin_image_url(candidate)
        if normalized:
            return normalized
    return None

def extract_class_image(soup: BeautifulSoup, class_name: str) -> Optional[str]:
    # 💡 직접 확인하신 HTML 구조에 맞게 <div class="c_left"> 안의 <img>를 정확히 타겟팅합니다.
    div_node = soup.select_one(f".{class_name}")
    if not div_node:
        return None
        
    img = div_node.select_one("img")
    if img and img.get("src"):
        return normalize_aladin_image_url(img["src"])
        
    style = div_node.get("style", "")
    match = re.search(r"url\(['\"]?([^'\")]+)['\"]?\)", style, re.IGNORECASE)
    if match:
        return normalize_aladin_image_url(match.group(1))
        
    return None

def classify_aladin_image_url(src: str) -> tuple[Optional[str], Optional[str]]:
    normalized = normalize_aladin_image_url(src)
    if not normalized:
        return None, None
    lower = normalized.lower()
    if "/spine/" in lower or "/spineflip/" in lower or re.search(r"_(d|s|sl)\.(jpg|png)$", lower):
        return "spine", normalized
    if re.search(r"_(bl|b|wbl)\.(jpg|png)$", lower):
        return "back", normalized
    if re.search(r"_(fl|f|wfl|1|2)\.(jpg|png)$", lower) or "/cover500/" in lower or "/cover/" in lower:
        return "front", normalized
    return None, normalized

def scan_aladin_image_urls(html: str) -> tuple[dict, list[str]]:
    found = {"front": None, "spine": None, "back": None}
    urls = re.findall(r'(?:https?:)?//image\.aladin\.co\.kr/product/[^"\'\s>)]+(?:\.jpg|\.png)', html, re.IGNORECASE)
    for src in urls:
        key, normalized = classify_aladin_image_url(src)
        if key and not found[key]:
            found[key] = normalized
    return found, urls

def extract_preview_page_images(item_id: str, headers: dict) -> dict:
    preview_url = f"{ALADIN_WEB_BASE}/shop/book/wletslookViewer.aspx?ItemId={item_id}"
    found = {"front": None, "spine": None, "back": None}
    try:
        # 💡 우회 터널 사용
        response = safe_requests_get(
            preview_url,
            headers=headers,
            timeout=(5, 10),
        )
        if response.status_code != 200:
            return found
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        selectors = {"front": [".pageType2.rightpage", ".pageType2 .rightpage"], "spine": [".bookspine"], "back": [".pageType3.leftpage", ".pageType3 .leftpage"]}
        for key, selector_list in selectors.items():
            for selector in selector_list:
                for node in soup.select(selector):
                    image_url = extract_image_from_node(node)
                    if image_url:
                        found[key] = image_url
                        break
                if found[key]:
                    break
        scanned, _ = scan_aladin_image_urls(html)
        for key in ["front", "spine", "back"]:
            if not found[key] and scanned.get(key):
                found[key] = scanned[key]
    except requests.RequestException as error:
        print(f"알라딘 미리보기 이미지 추출 실패: {error}")
    return found

@app.get("/api/get-book-images")
def get_book_images(
    item_id: str = Query(..., min_length=1),
    title: str = Query(""),
    author: str = Query(""),
    publisher: str = Query("")
):
    # 위에서 만든 함수를 통해 최종적으로 올바른 ItemId를 찾아냅니다.
    resolved_item_id = resolve_aladin_item_id(item_id, title, author, publisher)
    url = f"{ALADIN_WEB_BASE}/shop/wproduct.aspx?ItemId={resolved_item_id}"
    
    images = {"front": None, "spine": None, "back": None, "resolvedItemId": resolved_item_id}
    try:
        response = safe_requests_get(url, headers=DEFAULT_HEADERS, timeout=(5, 15))
        response.raise_for_status()
    except requests.RequestException as error:
        raise HTTPException(
            status_code=502,
            detail={"message": "알라딘 상품 페이지를 불러오지 못했습니다.", "reason": str(error)},
        )
        
    html = response.text
    soup = BeautifulSoup(html, "html.parser")
    
    # 💡 짚어주신 c_front, c_left, c_back을 여기서 최우선으로 가져옵니다!
    images["front"] = extract_class_image(soup, "c_front")
    images["spine"] = extract_class_image(soup, "c_left")
    images["back"] = extract_class_image(soup, "c_back")
    
    if not all([images["front"], images["spine"], images["back"]]):
        preview_images = extract_preview_page_images(resolved_item_id, DEFAULT_HEADERS)
        for key in ["front", "spine", "back"]:
            if not images[key] and preview_images.get(key):
                images[key] = preview_images[key]
                
    all_urls = re.findall(r'(?:https?:)?//image\.aladin\.co\.kr/product/[^"\'\s>)]+(?:\.jpg|\.png)', html, re.IGNORECASE)
    cover_url = None
    for src in all_urls:
        normalized_src = normalize_aladin_image_url(src)
        if not normalized_src: continue
        if "cover" in normalized_src.lower() and re.search(r"_\d\.", normalized_src):
            cover_url = normalized_src
            if not images["front"]: images["front"] = normalized_src
            break
    if cover_url:
        match = re.search(r"(https?://image\.aladin\.co\.kr/product/\d+/\d+/)(?:[^/]+)/([^/]+?)_\d.*?\.(?:jpg|png)", cover_url, re.IGNORECASE)
        if match:
            base_path = match.group(1)
            base_name = match.group(2)
            spine_guess = f"{base_path}spineflip/{base_name}_d.jpg"
            back_guess = f"{base_path}letslook/{base_name}_b.jpg"
            if not images["spine"] and check_url(spine_guess): images["spine"] = spine_guess
            if not images["back"] and check_url(back_guess): images["back"] = back_guess
    for src in all_urls:
        normalized_src = normalize_aladin_image_url(src)
        if not normalized_src: continue
        if not images["back"] and re.search(r"(/letslook/|_(b|bl|wbl)\.jpg)$", normalized_src, re.IGNORECASE): images["back"] = normalized_src
        elif not images["spine"] and re.search(r"(/spine/|/spineflip/|_(d|s|sl)\.jpg)$", normalized_src, re.IGNORECASE): images["spine"] = normalized_src
        elif not images["front"] and re.search(r"(/cover500/|_(f|wfl|2)\.jpg)$", normalized_src, re.IGNORECASE): images["front"] = normalized_src
    return images
