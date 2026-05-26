from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import re # 텍스트 전체를 스캔하는 정규표현식 모듈

app = FastAPI()

origins = [
    "https://typerecord.web.app",
    "http://localhost:3000",
    "http://localhost:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    
    response = requests.get(url, params=params)
    data = response.json()
    
    if "item" in data:
        for book in data["item"]:
            if "cover" in book:
                high_res_cover = book["cover"].replace("coversum", "cover500").replace("cover200", "cover500").replace("/cover/", "/cover500/")
                book["cover"] = high_res_cover
                
    return data

@app.get("/api/get-book-images")
def get_book_images(item_id: str):
    # 1. 네가 찾아낸 PC 버전 미리보기 URL 접속
    url = f"https://www.aladin.co.kr/shop/book/wletslookViewer.aspx?ItemId={item_id}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    images = {"front": None, "spine": None, "back": None}
    
    # 2. BeautifulSoup으로 <img> 태그 전체 수집
    img_tags = soup.find_all('img')
    img_urls = [img.get('src', '') for img in img_tags]
    
    # 3. HTML 안에 JS 코드로 꽁꽁 숨겨진 이미지 주소까지 정규식으로 추가 싹쓸이
    hidden_urls = re.findall(r'(?:https?:)?//[^"\'\s>]+aladin\.co\.kr[^"\'\s>]+\.jpg', response.text)
    
    # 4. 두 결과를 합치고 중복 제거
    all_urls = list(set(img_urls + hidden_urls))
    
    for src in all_urls:
        if not src: continue
        
        # 보안(CORS) 에러 방지 및 절대 경로 변환
        if src.startswith('//'):
            src = 'https:' + src
        elif src.startswith('/'):
            src = 'https://image.aladin.co.kr' + src
        elif src.startswith('http://'):
            src = src.replace('http://', 'https://')
            
        # [분류 작업] 네가 본 이미지 URL 패턴을 바탕으로 매칭
        # 뒷표지 (보통 _wbl, _bl, _b 로 끝남)
        if re.search(r'_(wbl|bl|b)\.jpg', src):
            images['back'] = src
        # 책등 (보통 Spine 폴더에 있거나 _sl, _s 로 끝남)
        elif re.search(r'(_sl|_s|Spine)\.jpg', src, re.IGNORECASE):
            images['spine'] = src
        # 앞표지 (보통 _wfl, _fl, _f 로 끝남)
        elif re.search(r'_(wfl|fl|f)\.jpg', src) and not images['front']:
            images['front'] = src

    # 5. 혹시라도 PC 버전에서 못 찾았다면 모바일 페이지로 2차 크롤링 (안전장치)
    if not images['front'] or not images['spine'] or not images['back']:
        m_url = f"https://www.aladin.co.kr/m/mletslooks.aspx?ItemId={item_id}"
        m_response = requests.get(m_url)
        m_urls = re.findall(r'(?:https?:)?//[^"\'\s>]+aladin\.co\.kr[^"\'\s>]+\.jpg', m_response.text)
        
        for src in m_urls:
            if not src: continue
            if src.startswith('//'): src = 'https:' + src
            elif src.startswith('/'): src = 'https://image.aladin.co.kr' + src
            elif src.startswith('http://'): src = src.replace('http://', 'https://')
            
            if re.search(r'_(wbl|bl|b)\.jpg', src) and not images['back']:
                images['back'] = src
            elif re.search(r'(_sl|_s|Spine)\.jpg', src, re.IGNORECASE) and not images['spine']:
                images['spine'] = src
            elif re.search(r'_(wfl|fl|f)\.jpg', src) and not images['front']:
                images['front'] = src

    return images
