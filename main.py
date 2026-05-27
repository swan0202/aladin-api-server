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

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from firebase_admin import messaging

# 1. Firebase Admin 초기화
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("🔥 Firebase Admin 연결 완료! 푸시 알림 감시 시작...")
except ValueError:
    # 서버 재시작 시 이미 초기화된 경우 에러 방지
    db = firestore.client()

# 2. 실시간 데이터 감시를 위한 콜백 함수
def on_snapshot(col_snapshot, changes, read_time):
    for change in changes:
        if change.type.name == 'ADDED':
            notif = change.document.to_dict()
            
            # 이미 읽은 알림이거나 과거 알림이면 패스
            if notif.get('isRead'):
                continue
                
            try:
                # 데이터베이스 경로를 쪼개서 UID(고유 ID) 찾아내기
                # 경로: artifacts/typerecord-app-v1/users/{UID}/notifications/{notifId}
                path_segments = change.document.reference.path.split('/')
                target_uid = path_segments[3]

                # 알림 받을 유저의 정보(토큰) 가져오기
                user_ref = db.document(f"artifacts/typerecord-app-v1/public/data/users/{target_uid}")
                user_snap = user_ref.get()

                if user_snap.exists:
                    user_data = user_snap.to_dict()

                    if user_data.get('pushEnabled') and user_data.get('fcmToken'):
                        title = f"{notif.get('fromName')}님의 알림" if notif.get('fromName') else 'Shelfy'
                        
                        # 푸시 메시지 포장
                        message = messaging.Message(
                            notification=messaging.Notification(
                                title=title,
                                body=notif.get('message')
                            ),
                            token=user_data.get('fcmToken')
                        )
                        
                        # 실제 기기로 발송!
                        messaging.send(message)
                        print(f"✅ 푸시 전송 성공: {user_data.get('displayName')}님에게 발송됨")
            except Exception as e:
                print(f"❌ 푸시 전송 실패: {e}")

# 3. FastAPI 서버가 시작될 때 감시자(Listener) 작동시키기
@app.on_event("startup")
def start_firestore_listener():
    col_query = db.collection_group('notifications')
    col_query.on_snapshot(on_snapshot)
