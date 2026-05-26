from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup

app = FastAPI()

# 보안 설정
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
    return response.json()

@app.get("/api/get-book-images")
def get_book_images(item_id: str):
    url = f"https://www.aladin.co.kr/m/mletslooks.aspx?ItemId={item_id}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    images = {"front": None, "spine": None, "back": None}
    
    for img in soup.find_all('img'):
        src = img.get('src', '')
        full_src = src if src.startswith('http') else 'https:' + src
        
        if '_fl.jpg' in src:
            images['front'] = full_src
        elif '/Spine/' in src:
            images['spine'] = full_src
        elif '_bl.jpg' in src:
            images['back'] = full_src
            
    return images