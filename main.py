from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import re

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
                book["cover"] = book["cover"].replace("coversum", "cover500").replace("cover200", "cover500").replace("/cover/", "/cover500/")
                
    return data

def format_url(src):
    if not src: return None
    if src.startswith('//'): return 'https:' + src
    if src.startswith('/'): return 'https://image.aladin.co.kr' + src
    if src.startswith('http://'): return src.replace('http://', 'https://')
    return src

@app.get("/api/get-book-images")
def get_book_images(item_id: str):
    # 1. 네가 제보해준 도서 상세페이지(wproduct.aspx)를 메인 타겟으로 씁니다!
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={item_id}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    images = {"front": None, "spine": None, "back": None}
    
    # 2. 캡처 화면에서 확인한 HTML 클래스명으로 핀포인트 저격 🔫
    c_front = soup.select_one('.c_front img')
    c_spine = soup.select_one('.c_left img')
    c_back = soup.select_one('.c_back img')
    
    if c_front and c_front.get('src'):
        images['front'] = format_url(c_front.get('src'))
    if c_spine and c_spine.get('src'):
        images['spine'] = format_url(c_spine.get('src'))
    if c_back and c_back.get('src'):
        images['back'] = format_url(c_back.get('src'))

    # 3. 혹시나 클래스명이 렌더링되지 않았을 경우를 대비한 2차 안전장치
    # (네가 알려준 /spineflip/ 폴더와 _d.jpg 패턴을 정규식에 추가했어!)
    if not images['spine'] or not images['back']:
        all_urls = re.findall(r'(?:https?:)?//image\.aladin\.co\.kr/[^"\'\s>]*\.(?:jpg|png)', response.text, re.IGNORECASE)
        
        for src in all_urls:
            src = format_url(src)
            # 뒷표지 (_b.jpg)
            if re.search(r'_(wbl|bl|b)\.jpg$', src, re.IGNORECASE) and not images['back']:
                images['back'] = src
            # 책등 (/spineflip/ 폴더 또는 _d.jpg)
            elif re.search(r'(/spineflip/|_(sl|s|d)\.jpg$)', src, re.IGNORECASE) and not images['spine']:
                images['spine'] = src
            # 앞표지
            elif re.search(r'_(wfl|fl|f)\.jpg$', src, re.IGNORECASE) and not images['front']:
                images['front'] = src

    for k in images:
        if not images[k]: images[k] = None

    return images
