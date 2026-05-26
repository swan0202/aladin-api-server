from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup

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
    
    # 🌟 [고화질 마법 1] 알라딘 기본 썸네일을 초고화질(cover500)로 강제 변환
    if "item" in data:
        for book in data["item"]:
            if "cover" in book:
                # URL 주소에서 작은 사이즈 폴더를 고화질 폴더로 글자 교체
                high_res_cover = book["cover"].replace("coversum", "cover500").replace("cover200", "cover500").replace("/cover/", "/cover500/")
                book["cover"] = high_res_cover
                
    return data

@app.get("/api/get-book-images")
def get_book_images(item_id: str):
    # PC 버전을 쓰면 차단당하므로 빠른 모바일 주소 유지
    url = f"https://www.aladin.co.kr/m/mletslooks.aspx?ItemId={item_id}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    images = {"front": None, "spine": None, "back": None}
    
    for img in soup.find_all('img'):
        src = img.get('src', '')
        full_src = src if src.startswith('http') else 'https:' + src
        
        # 🌟 [고화질 마법 2] _fl(일반) 대신 _wfl(와이드/고화질) 이미지를 1순위
        if '_wfl.jpg' in src:
            images['front'] = full_src
        elif '_fl.jpg' in src and not images['front']:
            images['front'] = full_src
            
        elif '/Spine/' in src:
            # 책등 이미지는 보통 단일 사이즈로 제공됨
            images['spine'] = full_src
            
        elif '_wbl.jpg' in src:
            images['back'] = full_src
        elif '_bl.jpg' in src and not images['back']:
            images['back'] = full_src
            
    return images
