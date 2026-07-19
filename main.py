from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
from bs4 import BeautifulSoup

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "알라딘 검색 API 서버가 정상 작동 중입니다!"}

@app.get("/ping")
def keep_awake():
    return {"status": "ok"}

TTB_KEY = "ttbwldusdydy1845001"

@app.get("/api/search")
def search_books(query: str):
    url = "http://www.aladin.co.kr/ttb/api/ItemSearch.aspx"
    params = {
        "ttbkey": TTB_KEY,
        "Query": query,
        "QueryType": "Keyword",
        "MaxResults": 10,
        "start": 1,
        "SearchTarget": "Book",
        "output": "js",
        "Version": "20131101"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    
    response = requests.get(url, params=params, headers=headers)
    
    try:
        data = response.json()
    except Exception as e:
        print("🚨 알라딘 API 에러 발생:", response.text)
        return {"item": []}
        
    if "item" in data:
        for book in data["item"]:
            if "cover" in book:
                book["cover"] = book["cover"].replace("coversum", "cover500").replace("cover200", "cover500").replace("/cover/", "/cover500/")
    return data

@app.get("/api/ttb/search")
def ttb_search_proxy(Query: str):
    """프론트엔드의 corsproxy.io 우회를 위한 검색 대리 호출 API"""
    url = "http://www.aladin.co.kr/ttb/api/ItemSearch.aspx"
    params = {
        "ttbkey": TTB_KEY,
        "Query": Query,
        "QueryType": "Keyword",
        "MaxResults": 1,
        "start": 1,
        "output": "js",
        "Version": "20131101"
    }
    response = requests.get(url, params=params)
    return response.json()


# ==========================================
# 알라딘 텍스트 (책소개, 책속에서) 스크래핑 로직
# ==========================================
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

def extract_text_lines_from_soup(soup):
    for tag in soup(["script", "style", "noscript", "iframe", "button"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = []
    for line in text.split("\n"):
        line = clean_text(line)
        if not line:
            continue
        if len(line) <= 1:
            continue
        lines.append(line)
    return lines

def extract_section_by_heading(lines, start_headings, stop_headings):
    start_index = -1
    for i, line in enumerate(lines):
        normalized = line.replace(" ", "")
        for heading in start_headings:
            normalized_heading = heading.replace(" ", "")
            if normalized == normalized_heading:
                start_index = i
                break
            if normalized_heading in normalized and len(normalized) <= 40:
                start_index = i
                break
        if start_index != -1:
            break
    if start_index == -1:
        return ""
    end_index = len(lines)
    for j in range(start_index + 1, len(lines)):
        normalized = lines[j].replace(" ", "")
        for stop in stop_headings:
            normalized_stop = stop.replace(" ", "")
            if normalized == normalized_stop:
                end_index = j
                break
            if normalized_stop in normalized and len(normalized) <= 40:
                end_index = j
                break
        if end_index != len(lines):
            break
    content = "\n".join(lines[start_index + 1:end_index])
    return clean_text(content)

def split_phrase_list(text: str):
    if not text:
        return []
    raw_parts = re.split(r"\n{2,}", text)
    phrases = []
    for part in raw_parts:
        part = clean_text(part)
        if not part:
            continue
        if len(part) > 600:
            sub_parts = [clean_text(x) for x in part.split("\n") if clean_text(x)]
            phrases.extend(sub_parts)
        else:
            phrases.append(part)
    phrases = [p for p in phrases if len(p) >= 10]
    result = []
    seen = set()
    for phrase in phrases:
        key = phrase[:80]
        if key in seen:
            continue
        seen.add(key)
        result.append(phrase)
    return result[:20]

def extract_by_original_boxes(soup):
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

def scrape_aladin_texts(item_id):
    resolved_id = resolve_aladin_item_id(item_id)
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={resolved_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://www.aladin.co.kr/",
    }
    texts = {"story": "", "description": "", "phrases": [], "mdRecommend": "", "sourceUrl": url}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
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
    except Exception as e:
        print(f"❌ 텍스트 스크래핑 실패: {e}")
    return texts

@app.get("/api/ttb/lookup")
def ttb_lookup_proxy(ItemId: str, itemIdType: str = "ItemId", OptResult: str = ""):
    url = "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    params = {
        "ttbkey": TTB_KEY,
        "ItemId": ItemId,
        "itemIdType": itemIdType,
        "OptResult": OptResult,
        "output": "js",
        "Version": "20131101"
    }
    try:
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
    except Exception as e:
        print(f"알라딘 API 호출 에러: {e}")
        data = {"item": [{"itemId": ItemId, "subInfo": {}}]}
    try:
        if "item" in data and len(data["item"]) > 0:
            item = data["item"][0]
            sub_info = item.get("subInfo", {})
            if (not sub_info.get("story") or not sub_info.get("phraseList") or not sub_info.get("fulldescription2") or not sub_info.get("mdrecommend")):
                scraped = scrape_aladin_texts(ItemId)
                if not sub_info.get("story") and scraped['story']:
                    sub_info['story'] = scraped['story']
                if not sub_info.get("fulldescription2") and scraped['description']:
                    sub_info['fulldescription2'] = scraped['description']
                if not sub_info.get("mdrecommend") and scraped['mdRecommend']:
                    sub_info['mdrecommend'] = scraped['mdRecommend']
                if not sub_info.get("phraseList") and scraped['phrases']:
                    sub_info['phraseList'] = [{"phrase": p} for p in scraped['phrases']]
            item["subInfo"] = sub_info
            data["item"][0] = item
    except Exception as e:
        print(f"크롤링 데이터 병합 에러: {e}")
    return data

def check_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, stream=True, timeout=2)
        return res.status_code == 200
    except:
        return False

def normalize_aladin_image_url(src):
    if not src:
        return None
    src = src.strip().strip('"').strip("'")
    if src.startswith('//'):
        src = 'https:' + src
    elif src.startswith('http://'):
        src = src.replace('http://', 'https://', 1)
    if not src.startswith('https://image.aladin.co.kr/'):
        return None
    return src.replace('coversum', 'cover500').replace('cover200', 'cover500').replace('/cover/', '/cover500/')

def extract_image_from_node(node):
    candidates = []
    for attr in ['src', 'data-src', 'data-original', 'data-lazy', 'data-url']:
        candidates.append(node.get(attr))
    style = node.get('style') or ''
    candidates.extend(re.findall(r'url\(([^)]+)\)', style, re.IGNORECASE))
    for img in node.select('img'):
        for attr in ['src', 'data-src', 'data-original', 'data-lazy', 'data-url']:
            candidates.append(img.get(attr))
        img_style = img.get('style') or ''
        candidates.extend(re.findall(r'url\(([^)]+)\)', img_style, re.IGNORECASE))
    for child in node.select('[style]'):
        child_style = child.get('style') or ''
        candidates.extend(re.findall(r'url\(([^)]+)\)', child_style, re.IGNORECASE))
    for candidate in candidates:
        normalized = normalize_aladin_image_url(candidate)
        if normalized:
            return normalized
    return None

def extract_class_image(soup, class_name):
    for node in soup.select(f'.{class_name}'):
        image_url = extract_image_from_node(node)
        if image_url:
            return image_url
    return None

def resolve_aladin_item_id(lookup_id):
    if not lookup_id:
        return None
    raw = str(lookup_id).strip()
    digits = re.sub(r'[^0-9Xx]', '', raw)
    is_isbn13 = len(digits) == 13 and digits.startswith(('978', '979'))
    is_isbn10 = len(digits) == 10
    if not is_isbn13 and not is_isbn10:
        return raw
    try:
        url = "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
        params = {"ttbkey": TTB_KEY, "ItemId": digits, "ItemIdType": "ISBN13" if is_isbn13 else "ISBN", "output": "js", "Version": "20131101"}
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        items = data.get("item") or []
        if items and items[0].get("itemId"):
            return str(items[0]["itemId"])
    except Exception as e:
        print(f"알라딘 ItemId 변환 실패: {e}")
    return raw

def classify_aladin_image_url(src):
    normalized = normalize_aladin_image_url(src)
    if not normalized:
        return None, None
    lower = normalized.lower()
    if '/spine/' in lower or '/spineflip/' in lower or re.search(r'_(d|s|sl)\.(jpg|png)$', lower):
        return 'spine', normalized
    if re.search(r'_(bl|b|wbl)\.(jpg|png)$', lower):
        return 'back', normalized
    if re.search(r'_(fl|f|wfl|1|2)\.(jpg|png)$', lower) or '/cover500/' in lower or '/cover/' in lower:
        return 'front', normalized
    return None, normalized

def scan_aladin_image_urls(html):
    found = {"front": None, "spine": None, "back": None}
    urls = re.findall(r"(?:https?:)?//image\.aladin\.co\.kr/product/[^\"'\s>)]+(?:\.jpg|\.png)", html, re.IGNORECASE)
    for src in urls:
        key, normalized = classify_aladin_image_url(src)
        if key and not found[key]:
            found[key] = normalized
    return found, urls

def extract_preview_page_images(item_id, headers):
    preview_url = f"https://www.aladin.co.kr/shop/book/wletslookViewer.aspx?ItemId={item_id}"
    found = {"front": None, "spine": None, "back": None}
    try:
        response = requests.get(preview_url, headers=headers, timeout=8)
        if response.status_code != 200:
            return found
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
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
        for key in ['front', 'spine', 'back']:
            if not found[key] and scanned.get(key):
                found[key] = scanned[key]
    except Exception as e:
        print(f"알라딘 미리보기 페이지 이미지 추출 실패: {e}")
    return found

@app.get("/api/get-book-images")
def get_book_images(item_id: str):
    resolved_item_id = resolve_aladin_item_id(item_id)
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={resolved_item_id}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    html = response.text
    images = {"front": None, "spine": None, "back": None}
    soup = BeautifulSoup(html, 'html.parser')
    images['front'] = extract_class_image(soup, 'c_front')
    images['spine'] = extract_class_image(soup, 'c_left')
    images['back'] = extract_class_image(soup, 'c_back')
    if not all(images.values()):
        preview_images = extract_preview_page_images(resolved_item_id, headers)
        for key in ['front', 'spine', 'back']:
            if not images[key] and preview_images.get(key):
                images[key] = preview_images[key]
    all_urls = re.findall(r'(?:https?:)?//image\.aladin\.co\.kr/product/[^"\'\s>)]+(?:\.jpg|\.png)', html, re.IGNORECASE)
    cover_url = None
    for src in all_urls:
        src = normalize_aladin_image_url(src)
        if not src:
            continue
        if 'cover' in src.lower() and re.search(r'_\d\.', src):
            cover_url = src
            if not images['front']:
                images['front'] = src
            break
    if cover_url:
        match = re.search(r'(https?://image\.aladin\.co\.kr/product/\d+/\d+/)(?:[^/]+)/([^/]+?)_\d.*?\.(?:jpg|png)', cover_url, re.IGNORECASE)
        if match:
            base_path = match.group(1)
            base_name = match.group(2)
            spine_guess = f"{base_path}spineflip/{base_name}_d.jpg"
            back_guess = f"{base_path}letslook/{base_name}_b.jpg"
            if not images['spine'] and check_url(spine_guess):
                images['spine'] = spine_guess
            if not images['back'] and check_url(back_guess):
                images['back'] = back_guess
    for src in all_urls:
        src = normalize_aladin_image_url(src)
        if not src:
            continue
        if not images['back'] and re.search(r'(/letslook/|_(b|bl|wbl)\.jpg)$', src, re.IGNORECASE):
            images['back'] = src
        elif not images['spine'] and re.search(r'(/spine/|/spineflip/|_(d|s|sl)\.jpg)$', src, re.IGNORECASE):
            images['spine'] = src
        elif not images['front'] and re.search(r'(/cover500/|_(f|wfl|2)\.jpg)$', src, re.IGNORECASE):
            images['front'] = src
    images["resolvedItemId"] = resolved_item_id
    return images
