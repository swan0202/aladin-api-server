from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
from bs4 import BeautifulSoup

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

    # 노드 자체가 이미지이거나 background-image를 가지고 있는 경우
    for attr in ['src', 'data-src', 'data-original', 'data-lazy', 'data-url']:
        candidates.append(node.get(attr))
    style = node.get('style') or ''
    candidates.extend(re.findall(r'url\(([^)]+)\)', style, re.IGNORECASE))

    # 하위 img 태그에 이미지 주소가 들어 있는 경우
    for img in node.select('img'):
        for attr in ['src', 'data-src', 'data-original', 'data-lazy', 'data-url']:
            candidates.append(img.get(attr))
        img_style = img.get('style') or ''
        candidates.extend(re.findall(r'url\(([^)]+)\)', img_style, re.IGNORECASE))

    # 하위 요소의 background-image에 이미지 주소가 들어 있는 경우
    for child in node.select('[style]'):
        child_style = child.get('style') or ''
        candidates.extend(re.findall(r'url\(([^)]+)\)', child_style, re.IGNORECASE))

    for candidate in candidates:
        normalized = normalize_aladin_image_url(candidate)
        if normalized:
            return normalized
    return None


def extract_class_image(soup, class_name):
    # 알라딘 상세페이지 미리보기 영역에서 사용하는 클래스 기반 추출
    # c_front: 책 표지, c_left: 책등, c_back: 책 뒷표지
    for node in soup.select(f'.{class_name}'):
        image_url = extract_image_from_node(node)
        if image_url:
            return image_url
    return None


def extract_preview_page_images(item_id, headers):
    """알라딘 미리보기 페이지(wletslookViewer)에서 책 표지/책등/뒷표지 이미지를 추출한다."""
    preview_url = f"https://www.aladin.co.kr/shop/book/wletslookViewer.aspx?ItemId={item_id}"
    found = {"front": None, "spine": None, "back": None}
    try:
        response = requests.get(preview_url, headers=headers, timeout=5)
        if response.status_code != 200:
            return found
        soup = BeautifulSoup(response.text, 'html.parser')

        # 미리보기 페이지 클래스 기준
        # class="pageType2 rightpage" = 책 표지
        # class="bookspine" = 책등
        # class="pageType3 leftpage" = 책 뒷표지
        selectors = {
            "front": [".pageType2.rightpage", ".pageType2 .rightpage"],
            "spine": [".bookspine"],
            "back": [".pageType3.leftpage", ".pageType3 .leftpage"],
        }

        for key, selector_list in selectors.items():
            for selector in selector_list:
                for node in soup.select(selector):
                    image_url = extract_image_from_node(node)
                    if image_url:
                        found[key] = image_url
                        break
                if found[key]:
                    break
    except Exception as e:
        print(f"알라딘 미리보기 페이지 이미지 추출 실패: {e}")
    return found

@app.get("/api/get-book-images")
def get_book_images(item_id: str):
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={item_id}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    response = requests.get(url, headers=headers)
    html = response.text
    
    images = {"front": None, "spine": None, "back": None}
    soup = BeautifulSoup(html, 'html.parser')

    # 1순위: 알라딘 상세페이지 DOM의 명시적 클래스에서 가져오기
    # class="c_front" = 책 표지 / class="c_left" = 책등 / class="c_back" = 책 뒷표지
    images['front'] = extract_class_image(soup, 'c_front')
    images['spine'] = extract_class_image(soup, 'c_left')
    images['back'] = extract_class_image(soup, 'c_back')

    # 2순위: 알라딘 미리보기 페이지(wletslookViewer)의 명시적 클래스에서 가져오기
    # class="pageType2 rightpage" = 책 표지 / class="bookspine" = 책등 / class="pageType3 leftpage" = 책 뒷표지
    if not all(images.values()):
        preview_images = extract_preview_page_images(item_id, headers)
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

    # 3순위: 알라딘 표지 주소 규칙을 역산하여 책등과 뒷표지 주소 계산
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

    # 4순위: HTML 내부 이미지 URL 전체 스캔
    for src in all_urls:
        src = normalize_aladin_image_url(src)
        if not src:
            continue
        
        if not images['back'] and re.search(r'(/letslook/|_(b|bl|wbl)\.jpg)$', src, re.IGNORECASE):
            images['back'] = src
        elif not images['spine'] and re.search(r'(/spineflip/|_(d|s|sl)\.jpg)$', src, re.IGNORECASE):
            images['spine'] = src
        elif not images['front'] and re.search(r'(/cover500/|_(f|wfl|2)\.jpg)$', src, re.IGNORECASE):
            images['front'] = src

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
