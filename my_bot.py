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

def get_news():
    urls = {"사회": "NATION", "경제": "BUSINESS", "연예": "ENTERTAINMENT"}
    msg = ""
    for cat, topic in urls.items():
        msg += f"\n[{cat}]\n"
        try:
            entries = feedparser.parse(f"https://news.google.com/rss/headlines/section/topic/{topic}?hl=ko&gl=KR&ceid=KR:ko").entries[:2]
            msg += "\n".join([f" - {e.title}" for e in entries]) + "\n"
        except: msg += " - 오류 발생\n"
    return msg

def send_morning_briefing():
    now = datetime.datetime.now(KST).strftime("%Y년 %m월 %d일")
    briefing_msg = f"🌅 좋은 아침입니다! ({now})\n\n🌤️ [오늘의 서울 날씨]\n{get_weather()}{get_snu_menu()}\n\n📰 [오늘의 주요 뉴스]{get_news()}"
    send_telegram_message(briefing_msg)

# =========================================================================
# [핵심 추가] 목록을 깨끗하게 청소하고, 시간순으로 줄 세우고, 번호를 1번부터 다시 매기는 함수
def sort_and_reindex_schedules():
    global schedule_list
    # 1. 완료된(done=True) 일정 아예 리스트에서 삭제
    schedule_list = [s for s in schedule_list if not s['done']]
    # 2. 알람 시간(alert_dt) 기준으로 가까운 시간부터 오름차순 정렬
    schedule_list.sort(key=lambda x: x['alert_dt'])
    # 3. 번호를 1번부터 깔끔하게 다시 부여
    for i, item in enumerate(schedule_list):
        item['id'] = i + 1
# =========================================================================

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
    
    # 0번(임시)으로 먼저 넣고
    schedule_list.append({
        "id": 0, "title": title, "time": full_time_str,
        "alert_dt": alert_dt, "lead_minutes": lm, "done": False
    })
    
    # 정렬 함수 돌리면 알아서 자기 자리(시간순) 찾아가고 올바른 번호가 부여됨
    sort_and_reindex_schedules()
    
    # 부여된 새 번호 찾아서 메시지 전송
    new_id = next(s['id'] for s in schedule_list if s['title'] == title and s['alert_dt'] == alert_dt)
    send_telegram_message(f"✅ 일정 등록!\n번호: [{new_id}]\n📌 {title}\n⏰ {full_time_str}\n🔔 {('정각' if lm == 0 else f'{lm}분 전')} 알림")

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
            sort_and_reindex_schedules() # 삭제 후 다시 번호 1번부터 예쁘게 정렬
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
                    elif text == "/목록":
                        sort_and_reindex_schedules() # 보여주기 직전에 한 번 더 깔끔하게 정리
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
                
        # 알림이 울려서 완료(done)된 일정이 하나라도 생겼다면, 목록 청소 및 번호 재정렬
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
