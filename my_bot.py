import threading
import time
import datetime
import requests
import feedparser
import schedule
from bs4 import BeautifulSoup
import re
import os
from flask import Flask
from threading import Thread

# =========================================================================
# [필수 입력]
TELEGRAM_TOKEN = "8997577286:AAHB7GROo32SNA-FapAgQXKapCndviPXGL4"
CHAT_ID = "8212691871"
# 렌더(Render) 금고에서 API 키를 안전하게 꺼내옵니다.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# =========================================================================

# ★ 한국 시간(KST) 설정
KST = datetime.timezone(datetime.timedelta(hours=9))

last_update_id = None
schedule_list = []

# =========================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 비서봇이 Render 서버에서 24시간 정상 작동 중입니다!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.start()
# =========================================================================

def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try: requests.post(url, json=payload, timeout=10)
    except Exception as e: pass

def get_weather():
    try:
        url = "https://wttr.in/Seoul?format=j1&lang=ko"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            current_temp = data['current_condition'][0]['temp_C']
            try: condition = data['current_condition'][0]['lang_ko'][0]['value']
            except: condition = data['current_condition'][0]['weatherDesc'][0]['value']
            min_temp, max_temp = data['weather'][0]['mintempC'], data['weather'][0]['maxtempC']
            
            weather_text = f"상태: {condition}\n현재 기온: {current_temp}°C (최저 {min_temp}°C / 최고 {max_temp}°C)"
            
            need_umbrella = False
            for hour in data['weather'][0]['hourly']:
                if int(hour.get('chanceofrain', '0')) >= 40 or int(hour.get('chanceofsnow', '0')) >= 40:
                    need_umbrella = True
                    break
            if need_umbrella: weather_text += "\n\n☔ **오늘 강수 확률이 40% 이상인 시간대가 있습니다! 우산을 챙기세요!**"
            return weather_text
    except: return "날씨 정보를 불러오지 못했습니다."

def get_snu_menu():
    url, menu_msg = "https://snuco.snu.ac.kr/ko/foodmenu", "\n\n🍽️ [오늘의 학식 메뉴]\n"
    try:
        soup = BeautifulSoup(requests.get(url, timeout=10).text, 'html.parser')
        sm, am = "정보 없음", "정보 없음"
        for tr in soup.find_all('tr'):
            cells = tr.find_all(['td', 'th'])
            if len(cells) < 4: continue
            name = cells[0].get_text(strip=True)
            if "학생회관식당" in name or "예술계식당" in name:
                lunch = cells[2].get_text(separator="\n", strip=True) or "운영 안 함"
                dinner = cells[3].get_text(separator="\n", strip=True) or "운영 안 함"
                formatted = f"☀️ [점심]\n{lunch}\n\n🌙 [저녁]\n{dinner}"
                if "학생회관식당" in name: sm = formatted
                elif "예술계식당" in name: am = formatted
        return menu_msg + f"▶ 학생회관식당\n{sm}\n\n====================\n\n▶ 예술계식당\n{am}"
    except: return menu_msg + "학식 정보를 불러오지 못했습니다."

# [수정됨] 뉴스 수집 단계 및 AI 프롬프트에서 링크(URL)를 완전히 제외!
def get_news_with_ai():
    urls = {"사회/정치": "NATION", "경제": "BUSINESS", "세계": "WORLD"}
    raw_news = ""
    for cat, topic in urls.items():
        try:
            entries = feedparser.parse(f"https://news.google.com/rss/headlines/section/topic/{topic}?hl=ko&gl=KR&ceid=KR:ko").entries[:1]
            for e in entries:
                raw_news += f"[{cat}] {e.title}\n"  # 링크 안 담고 제목만 쏙 가져옵니다.
        except: pass

    if not GEMINI_API_KEY or GEMINI_API_KEY.strip() == "":
        return raw_news + "\n(⚠️ 딥다이브 브리핑을 보려면 Render 환경변수에 GEMINI_API_KEY를 등록해주세요.)"

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
        prompt = f"다음은 오늘의 주요 뉴스 헤드라인입니다:\n\n{raw_news}\n\n이 뉴스들을 바탕으로 향후 연관된 주가 전망, 경제적 파급 효과, 정치적 이슈 등을 포함한 핵심 브리핑을 작성해주세요. 글은 바쁜 아침에 읽기 좋게 핵심만 3~4문장으로 깔끔하게 요약해 주시고, 개별 뉴스 링크나 URL 출처는 절대 본문에 포함하지 마세요."
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        response = requests.post(url, json=payload, timeout=20)
        
        if response.status_code != 200:
            return raw_news + f"\n(🚨 API 거절됨: {response.text})"
            
        res = response.json()
        ai_briefing = res["candidates"][0]["content"]["parts"][0]["text"]
        return ai_briefing
    except Exception as e:
        return raw_news + f"\n(🚨 파이썬 에러: {str(e)})"

# [유지됨] 대학생 꿀정보 쪽 링크는 그대로 살아있습니다!
def get_scholarship_info():
    msg = "\n\n🎓 [대학생 장학금 & 공모전 정보]\n"
    try:
        url = "https://news.google.com/rss/search?q=%EB%8C%80%ED%95%99%EC%83%9D+%EC%9E%A5%ED%95%99%EA%B8%88+OR+%EA%B3%B5%EB%AA%A8%EC%A0%84+when:7d&hl=ko&gl=KR&ceid=KR:ko"
        entries = feedparser.parse(url).entries[:3]
        for e in entries:
            msg += f"💡 {e.title}\n   🔗 {e.link}\n\n"
        return msg
    except:
        return msg + "정보를 불러올 수 없습니다."

def send_morning_briefing():
    now = datetime.datetime.now(KST).strftime("%Y년 %m월 %d일")
    briefing_msg = f"🌅 좋은 아침입니다! ({now})\n💊 잊지 말고 영양제를 챙겨 드세요!\n\n🌤️ [오늘의 서울 날씨]\n{get_weather()}{get_snu_menu()}\n\n📰 [오늘의 AI 딥다이브 브리핑]\n{get_news_with_ai()}{get_scholarship_info()}"
    send_telegram_message(briefing_msg)

def sort_and_reindex_schedules():
    global schedule_list
    schedule_list = [s for s in schedule_list if not s['done']]
    schedule_list.sort(key=lambda x: x['alert_dt'])
    for i, item in enumerate(schedule_list):
        item['id'] = i + 1

def parse_and_add_schedule(command_text):
    parts = command_text.split()
    if len(parts) < 4:
        send_telegram_message("⚠️ 형식: /일정 [제목] [월일4자리] [시간4자리] [몇분전(선택)]")
        return

    title, date_str, time_str = parts[1], parts[2], parts[3]
    now = datetime.datetime.now(KST)
    
    if len(date_str) == 4 and date_str.isdigit() and len(time_str) == 4 and time_str.isdigit():
        month, day = int(date_str[:2]), int(date_str[2:])
        hour, minute = int(time_str[:2]), int(time_str[2:])
    else:
        send_telegram_message("⚠️ 날짜와 시간은 4자리 숫자로 적어주세요. (예: 0520 1430)")
        return

    try: dt = datetime.datetime(now.year, month, day, hour, minute, tzinfo=KST)
    except ValueError:
        send_telegram_message("⚠️ 잘못된 날짜나 시간입니다.")
        return

    lm = 0
    if len(parts) >= 5:
        digits = re.sub(r'[^0-9]', '', parts[4])
        if digits: lm = int(digits) * (60 if "시간" in parts[4] else 1)

    alert_dt = dt - datetime.timedelta(minutes=lm)
    full_time_str = dt.strftime("%Y-%m-%d %H:%M")
    
    schedule_list.append({
        "id": 0, "title": title, "time": full_time_str,
        "alert_dt": alert_dt, "lead_minutes": lm, "done": False
    })
    
    sort_and_reindex_schedules()
    new_id = next(s['id'] for s in schedule_list if s['title'] == title and s['alert_dt'] == alert_dt)
    send_telegram_message(f"✅ 일정 등록!\n번호: [{new_id}]\n📌 {title}\n⏰ {full_time_str}\n🔔 {('정각' if lm == 0 else f'{lm}분 전')} 알림")

def modify_schedule(command_text):
    parts = command_text.split()
    if len(parts) < 5:
        send_telegram_message("⚠️ 형식: /수정 [번호] [새제목] [새월일4자리] [새시간4자리] [몇분전(선택)]")
        return

    if not parts[1].isdigit():
        send_telegram_message("⚠️ 올바른 번호를 입력해주세요. (예: /수정 1 새제목 0620 1300)")
        return

    target_id = int(parts[1])
    title, date_str, time_str = parts[2], parts[3], parts[4]
    now = datetime.datetime.now(KST)
    
    if len(date_str) == 4 and date_str.isdigit() and len(time_str) == 4 and time_str.isdigit():
        month, day = int(date_str[:2]), int(date_str[2:])
        hour, minute = int(time_str[:2]), int(time_str[2:])
    else:
        send_telegram_message("⚠️ 날짜와 시간은 4자리 숫자로 적어주세요. (예: 0520 1430)")
        return

    try: dt = datetime.datetime(now.year, month, day, hour, minute, tzinfo=KST)
    except ValueError:
        send_telegram_message("⚠️ 잘못된 날짜나 시간입니다.")
        return

    lm = 0
    if len(parts) >= 6:
        digits = re.sub(r'[^0-9]', '', parts[5])
        if digits: lm = int(digits) * (60 if "시간" in parts[5] else 1)

    alert_dt = dt - datetime.timedelta(minutes=lm)
    full_time_str = dt.strftime("%Y-%m-%d %H:%M")
    
    for item in schedule_list:
        if item['id'] == target_id:
            item['title'] = title
            item['time'] = full_time_str
            item['alert_dt'] = alert_dt
            item['lead_minutes'] = lm
            item['done'] = False
            
            send_telegram_message(f"✏️ 일정 수정 완료!\n📌 새 제목: {title}\n⏰ 새 시간: {full_time_str}\n🔔 알림 세팅: {('정각' if lm == 0 else f'{lm}분 전')}")
            sort_and_reindex_schedules() 
            return
            
    send_telegram_message(f"⚠️ [{target_id}]번 일정을 찾을 수 없습니다.")

def delete_schedule(command_text):
    parts = command_text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        send_telegram_message("⚠️ 번호를 입력해주세요. (예: /삭제 1)")
        return
    
    target_id = int(parts[1])
    for item in schedule_list:
        if item['id'] == target_id:
            item['done'] = True
            send_telegram_message(f"🗑️ '{item['title']}' 삭제 완료.")
            sort_and_reindex_schedules()
            return
    send_telegram_message(f"⚠️ [{target_id}]번 일정을 찾을 수 없습니다.")

def process_telegram_commands():
    global last_update_id
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 10}
    if last_update_id: params["offset"] = last_update_id + 1
        
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 200:
            for result in response.json().get("result", []):
                last_update_id = result["update_id"]
                message = result.get("message", {})
                text, chat_id_from_msg = message.get("text", ""), str(message.get("chat", {}).get("id", ""))
                
                if chat_id_from_msg == CHAT_ID and text:
                    if text.startswith("/일정"): parse_and_add_schedule(text)
                    elif text.startswith("/삭제"): delete_schedule(text)
                    elif text.startswith("/수정"): modify_schedule(text)
                    elif text == "/브리핑":
                        send_telegram_message("⏳ AI가 오늘의 뉴스와 정보를 분석하고 있습니다. 잠시만 기다려주세요... (약 10~20초 소요)")
                        send_morning_briefing()
                    elif text == "/목록":
                        sort_and_reindex_schedules()
                        if not schedule_list: send_telegram_message("대기 중인 일정이 없습니다.")
                        else: send_telegram_message("📅 [대기 중인 일정]\n" + "".join([f"[{s['id']}] {s['title']} ({s['time']})\n" for s in schedule_list]))
    except: pass

def background_loop():
    schedule.every().day.at("23:00").do(send_morning_briefing)
    while True:
        schedule.run_pending()
        process_telegram_commands()
        
        now = datetime.datetime.now(KST)
        for item in schedule_list:
            if not item['done'] and now >= item['alert_dt']:
                msg = f"⏰ [일정 알림]\n지금은 '{item['title']}' 할 시간입니다!" if item['lead_minutes'] == 0 else f"⏰ [미리 알림]\n{item['lead_minutes']}분 뒤에 '{item['title']}' 일정이 있습니다!"
                send_telegram_message(msg)
                item['done'] = True
                
        if any(item['done'] for item in schedule_list):
            sort_and_reindex_schedules()
            
        time.sleep(10)

if __name__ == "__main__":
    print("🤖 클라우드 서버 세팅 완료! 가동 시작...")
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("result"):
            last_update_id = res["result"][-1]["update_id"]
            print(f"✅ 초기화 완료: 마지막 메시지 번호({last_update_id})부터 시작합니다.")
    except: pass
    
    keep_alive() 
    background_loop()
