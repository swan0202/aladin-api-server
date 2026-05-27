from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TTB_KEY = "ttbwldusdydy1845001"

# 🌟 [추가된 부분] cron-job.org가 14분마다 두드릴 빈 페이지(대문)입니다!
@app.get("/")
def keep_alive():
    return {"status": "alive", "message": "Shelfy Aladin API Server is running! 🚀"}

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

# 실제 이미지가 존재하는지 빠르게 확인하는 함수
def check_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, headers=headers, stream=True, timeout=2)
        return res.status_code == 200
    except:
        return False

@app.get("/api/get-book-images")
def get_book_images(item_id: str):
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={item_id}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    response = requests.get(url, headers=headers)
    html = response.text
    
    images = {"front": None, "spine": None, "back": None}

    all_urls = re.findall(r'(?:https?:)?//image\.aladin\.co\.kr/product/[^"\'\s>]+(?:\.jpg|\.png)', html, re.IGNORECASE)
    
    cover_url = None
    for src in all_urls:
        if src.startswith('//'): src = 'https:' + src
        elif src.startswith('http://'): src = src.replace('http://', 'https://')
        
        if 'cover' in src.lower() and re.search(r'_\d\.', src):
            cover_url = src
            break

    # 🌟 핵심 알고리즘: 알라딘 표지 주소 규칙을 역산하여 책등과 뒷표지 주소를 수학적으로 계산해 냄
    if cover_url:
        match = re.search(r'(https?://image\.aladin\.co\.kr/product/\d+/\d+/)(?:[^/]+)/([^/]+?)_\d.*?\.(?:jpg|png)', cover_url, re.IGNORECASE)
        if match:
            base_path = match.group(1)
            base_name = match.group(2)
            
            spine_guess = f"{base_path}spineflip/{base_name}_d.jpg"
            back_guess = f"{base_path}letslook/{base_name}_b.jpg"
            
            # 예측한 주소에 실제로 이미지가 존재하는지 검증
            if check_url(spine_guess): images['spine'] = spine_guess
            if check_url(back_guess): images['back'] = back_guess

    # 만약 예측에 실패했다면 기존 방식으로 HTML 내부 스캔
    for src in all_urls:
        if src.startswith('//'): src = 'https:' + src
        elif src.startswith('http://'): src = src.replace('http://', 'https://')
        
        if not images['back'] and re.search(r'(/letslook/|_(b|bl|wbl)\.jpg)$', src, re.IGNORECASE):
            if check_url(src): images['back'] = src
        elif not images['spine'] and re.search(r'(/spineflip/|_(d|s|sl)\.jpg)$', src, re.IGNORECASE):
            if check_url(src): images['spine'] = src
        elif not images['front'] and re.search(r'(/cover500/|_(f|wfl|2)\.jpg)$', src, re.IGNORECASE):
            images['front'] = src.replace("coversum", "cover500").replace("cover200", "cover500")

    return images
