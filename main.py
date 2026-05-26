from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
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
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={item_id}"
    response = requests.get(url)
    html = response.text
    
    images = {"front": None, "spine": None, "back": None}

    # 💡 핵심: item_id가 포함되어야 한다는 조건을 지우고, 알라딘 이미지 주소를 전부 찾아냄
    all_urls = re.findall(r'(?:https?:)?//image\.aladin\.co\.kr/product/[^"\'\s>]+(?:\.jpg|\.png)', html, re.IGNORECASE)

    for src in all_urls:
        src = format_url(src)

        # 뒷표지: 캡처에서 본 letslook 폴더나 _b.jpg 우선 낚아채기
        if re.search(r'(/letslook/|_(b|bl|wbl)\.jpg)$', src, re.IGNORECASE) and not images['back']:
            images['back'] = src

        # 책등: 캡처에서 본 spineflip 폴더나 _d.jpg 우선 낚아채기
        elif re.search(r'(/spineflip/|_(d|s|sl)\.jpg)$', src, re.IGNORECASE) and not images['spine']:
            images['spine'] = src

        # 앞표지: 고화질 덮어쓰기용 백업
        elif re.search(r'(/cover500/|_(f|wfl|2)\.jpg)$', src, re.IGNORECASE) and not images['front']:
            images['front'] = src.replace("coversum", "cover500").replace("cover200", "cover500")

    return images
